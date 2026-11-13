"""
Agent loop: LLM <-> tools ka chakkar.

Is file mein:
  api_call()     chat/completions call, retry+backoff (429/5xx/network), tokens+seconds log
  compact()      context bhar raha ho toh purane tool results / images / bade arguments hatao
  run_task()     asli loop: API -> tools (ek ek karke) -> image message -> dobara
  controller rule (code mein, LLM pe nahi): notes PDF ke akhri badlav ke baad inspect_document
                 nahi chala toh final jawab accept nahi hota (jab tak inspect_document tool registered hai)
"""
from __future__ import annotations

import json
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import requests

import config
import events
import tools  # noqa: F401  (import se saare tools registry mein register hote hain)
from tools import registry
from session import Session


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# ---------- settings (.env mein badal sakte ho) ----------
MAX_RETRIES = _env_int("AGENT_MAX_RETRIES", 5)
READ_TIMEOUT = _env_int("AGENT_READ_TIMEOUT", 600)        # ek API call ka max intezaar (seconds)
CONTEXT_LIMIT = _env_int("AGENT_CONTEXT_TOKENS", 120000)  # isse upar jaye toh compaction (verify nahi: model ki asli limit)
KEEP_RECENT = 8                                            # akhri itne messages compaction se bachte hain
STUB_KEEP_CHARS = 300                                      # purane tool result ke itne chars bachte hain
IMAGE_TOKENS = 1600   # andaza, har image ke liye
BYTES_LIMIT = 3_000_000      # API limit 5_242_880 hai, margin ke saath


def payload_bytes(messages: list[dict]) -> int:
    return len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
MAX_INSPECT_REMINDERS = 3
OUTPUT_SUFFIX_MUST_INSPECT = {".pdf", ".docx", ".pptx"}


# =================================================================== API
class ApiError(Exception):
    def __init__(self, status: int, text: str):
        super().__init__(f"HTTP {status}: {text}")
        self.status = status
        self.text = text


@dataclass
class Reply:
    message: dict
    finish_reason: str
    prompt_tokens: int | None
    completion_tokens: int | None
    seconds: float


def _parse(resp: requests.Response, seconds: float) -> Reply | None:
    try:
        data = resp.json()
        choice = data["choices"][0]
        raw = choice["message"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    content = raw.get("content")
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    msg: dict = {"role": "assistant", "content": content or ""}
    calls = []
    for tc in raw.get("tool_calls") or []:
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        if not isinstance(args, str):
            args = json.dumps(args or {}, ensure_ascii=False)
        calls.append({"id": tc.get("id") or f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                      "function": {"name": fn.get("name", ""), "arguments": args or "{}"}})
    if calls:
        msg["tool_calls"] = calls
    usage = data.get("usage") or {}
    return Reply(msg, choice.get("finish_reason") or "", usage.get("prompt_tokens"),
                 usage.get("completion_tokens"), seconds)


def _retry_after(resp: requests.Response) -> float | None:
    try:
        return float(resp.headers.get("Retry-After", ""))
    except ValueError:
        return None


def api_call(messages: list[dict], use_tools: bool = True) -> Reply:
    url = f"{config.BASE_URL}/chat/completions"
    payload: dict = {"model": config.MODEL, "messages": messages, "max_tokens": config.MAX_TOKENS}
    if use_tools:
        payload["tools"] = registry.schemas()
    headers = {"Authorization": f"Bearer {config.API_KEY}"}
    last = "unknown"

    for attempt in range(MAX_RETRIES + 1):
        t0 = time.time()
        wait: float | None = None
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=(15, READ_TIMEOUT))
        except (requests.ConnectionError, requests.Timeout) as e:
            last = f"network: {type(e).__name__}"
        else:
            if resp.status_code == 200:
                reply = _parse(resp, time.time() - t0)
                if reply:
                    return reply
                last = "response ka format galat: " + resp.text[:200]
            elif resp.status_code in RETRY_STATUS:
                last = f"HTTP {resp.status_code}: {resp.text[:200]}"
                wait = _retry_after(resp)
            else:
                raise ApiError(resp.status_code, resp.text[:1500])

        if attempt < MAX_RETRIES:
            delay = min(wait, 90) if wait else min(60, 2 ** (attempt + 1)) + random.random()
            events.info(f"  [API dikkat: {last[:150]}] {delay:.0f}s baad dobara ({attempt + 1}/{MAX_RETRIES})")
            events.log_event({"event": "api_retry", "attempt": attempt + 1, "reason": last[:200], "wait": round(delay, 1)})
            time.sleep(delay)
    raise ApiError(0, f"{MAX_RETRIES + 1} koshish ke baad bhi fail: {last}")


# =================================================================== compaction
def _has_image(m: dict) -> bool:
    c = m.get("content")
    return isinstance(c, list) and any(isinstance(p, dict) and p.get("type") == "image_url" for p in c)


def estimate_tokens(messages: list[dict]) -> int:
    """Mota andaza (chars/3, image ~1600). Asli count API ke usage se aata hai, ye uska backup hai."""
    total = 0.0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += len(c) / 3
        elif isinstance(c, list):
            for p in c:
                if p.get("type") == "image_url":
                    total += IMAGE_TOKENS
                else:
                    total += len(p.get("text", "")) / 3
        for tc in m.get("tool_calls") or []:
            total += len(tc["function"]["arguments"]) / 3
    return int(total)


def _strip_images(m: dict, note: str) -> None:
    m["content"] = [{"type": "text", "text": note} if p.get("type") == "image_url" else p for p in m["content"]]


def _shrink_args(tc: dict, keep: int) -> None:
    """Bade write/append arguments chhote karo (file disk pe hai). JSON valid rehna chahiye."""
    raw = tc["function"]["arguments"]
    if len(raw) <= keep * 2:
        return
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        tc["function"]["arguments"] = json.dumps({"_note": "bada argument hata diya gaya"})
        return
    if isinstance(args, dict):
        for k, v in args.items():
            if isinstance(v, str) and len(v) > keep:
                args[k] = v[:keep] + f"...[{len(v) - keep} chars hata diye, file disk pe hai]"
        tc["function"]["arguments"] = json.dumps(args, ensure_ascii=False)


def compact(messages: list[dict], limit: int) -> tuple[int, int]:
    """In-place. Pehla user message (prompt + photos) tab tak nahi chhoota jab tak zaroori na ho. Returns (pehle, baad)."""
    before = estimate_tokens(messages)
    protected_from = max(2, len(messages) - KEEP_RECENT)

    def old_tool_results(keep_chars: int, args_keep: int) -> None:
        for i in range(2, protected_from):
            m = messages[i]
            if m.get("role") == "tool" and isinstance(m.get("content"), str):
                c = m["content"]
                if len(c) > keep_chars + 200 and "[purana tool result hata diya" not in c:
                    m["content"] = (c[:keep_chars] + f"\n...[purana tool result hata diya gaya, {len(c)} chars. "
                                    "Zarurat ho toh tool dobara chalao.]")
            for tc in m.get("tool_calls") or []:
                _shrink_args(tc, args_keep)

    # 1) purani view_image wali images (pehla message nahi)
    for i in range(2, protected_from):
        if messages[i].get("role") == "user" and _has_image(messages[i]):
            _strip_images(messages[i], "[purani image context bachane ke liye hata di gayi. Zarurat ho toh view_image dobara]")
    # 2) purane tool results + bade arguments
    old_tool_results(STUB_KEEP_CHARS, 600)
    # 3) abhi bhi bada: aur sakht, aur user ki original photos bhi
    if estimate_tokens(messages) > limit or payload_bytes(messages) > BYTES_LIMIT:
        old_tool_results(100, 200)
        if len(messages) > 1 and _has_image(messages[1]):
            _strip_images(messages[1], "[user ki photo context bachane ke liye hata di gayi. Originals container mein hain, view_image se dekh sakta hai]")
    return before, estimate_tokens(messages)


# =================================================================== controller rule: inspect_document
def _output_files_since(session: Session) -> list[Path]:
    out = config.WORKSPACE_HOST / "output"
    if not out.exists():
        return []
    cutoff = session.started - 1
    return sorted(p for p in out.rglob("*") if p.is_file() and not p.name.startswith(".") and p.stat().st_mtime >= cutoff)


def _uninspected(session: Session) -> list[Path]:
    if "inspect_document" not in registry.REGISTRY:    # tool abhi bana nahi (step 3), rule tab tak off
        return []
    return [f for f in _output_files_since(session)
            if f.suffix.lower() in OUTPUT_SUFFIX_MUST_INSPECT and not session.inspected_after(f)]


# =================================================================== loop
@dataclass
class RunResult:
    status: str                     # done | done_unchecked | step_limit | interrupted | api_error
    files: list[Path] = field(default_factory=list)


def _first_line(text: str, n: int = 160) -> str:
    return (text.splitlines() or [""])[0][:n]


def run_task(session: Session, max_steps: int | None = None) -> RunResult:
    max_steps = max_steps or config.MAX_STEPS
    last_prompt: int | None = None       # pichli API call ka asli prompt token count
    count_at_call = 0                    # us waqt messages kitne the
    reminders = 0
    nudged_length = 0
    nudged_empty = 0

    for step in range(1, max_steps + 1):
        # ---- context
        if last_prompt is not None:
            used = last_prompt + estimate_tokens(session.messages[count_at_call:])
        else:
            used = estimate_tokens(session.messages)
        if used > CONTEXT_LIMIT or payload_bytes(session.messages) > BYTES_LIMIT:
            t0 = time.time()
            before, after = compact(session.messages, CONTEXT_LIMIT)
            events.info(f"  [context compaction: ~{before} -> ~{after} tokens (andaza)]")
            events.log_event({"event": "compaction", "tokens_before": before, "tokens_after": after,
                              "seconds": round(time.time() - t0, 2)})
            session.log_note("compaction", tokens_before=before, tokens_after=after)
            last_prompt = None

        # ---- API
        try:
            reply = api_call(session.messages)
        except KeyboardInterrupt:
            events.info("\n[ruk gaya (Ctrl+C)]")
            return RunResult("interrupted")
        except ApiError as e:
            events.info(f"\n[API error {e.status}] {e.text[:800]}")
            if e.status == 400:
                events.info("  (400 aaye toh: image/format/max_tokens ka issue ho sakta hai. messages.jsonl aur ye text dekh.)")
            return RunResult("api_error")
        count_at_call = len(session.messages)
        last_prompt = reply.prompt_tokens

        msg = reply.message
        session.add(msg)
        events.log_event({"event": "api_call", "step": step, "model": config.MODEL,
                          "prompt_tokens": reply.prompt_tokens, "completion_tokens": reply.completion_tokens,
                          "seconds": round(reply.seconds, 1), "finish_reason": reply.finish_reason})
        events.info(f"  (step {step}: in {reply.prompt_tokens}, out {reply.completion_tokens} tokens, {reply.seconds:.1f}s)")
        if msg["content"].strip():
            events.info(f"\nAI: {msg['content']}")

        calls = msg.get("tool_calls") or []

        # ---- tool call nahi: jawab khatam ya koi dikkat
        if not calls:
            if reply.finish_reason == "length" and nudged_length < 3:
                nudged_length += 1
                session.add({"role": "user", "content": "[controller] Tera jawab max_tokens pe kat gaya. Jahan ruka wahin se aage chal, "
                                                         "aur bada kaam chhote tukdon mein kar (append_file)."})
                continue
            if not msg["content"].strip() and nudged_empty < 2:
                nudged_empty += 1
                session.add({"role": "user", "content": "[controller] Tera jawab khali aaya. Kaam aage badha ya bata ki kya hua."})
                continue
            missing = _uninspected(session)
            if missing:
                if reminders < MAX_INSPECT_REMINDERS:
                    reminders += 1
                    names = ", ".join(f.name for f in missing)
                    events.info(f"  [controller rule: inspect_document baaki hai -> {names}]")
                    session.add({"role": "user", "content": (
                        f"[controller] Ye output file(s) ke akhri badlav ke baad inspect_document nahi chala: {names}. "
                        "Pehle inspect_document chala, jo issue aaye theek kar, phir final jawab de. "
                        "(Fix ke baad file badli toh dobara chalana padega.)")})
                    continue
                events.info("\n[controller] inspect_document ke bina file present nahi karunga: " +
                            ", ".join(f.name for f in missing))
                return RunResult("done_unchecked")
            return RunResult("done", _output_files_since(session))

        # ---- tools, ek ek karke
        answered: set[str] = set()
        try:
            for tc in calls:
                name, raw = tc["function"]["name"], tc["function"]["arguments"]
                result = registry.run_tool(name, raw)
                session.add({"role": "tool", "tool_call_id": tc["id"], "content": result})
                answered.add(tc["id"])
                if name == "inspect_document" and (result.startswith("STATUS: ok") or result.startswith("STATUS: partial")):
                    session.note_inspect(raw)
                events.info(f"  [{step}] {name} -> {_first_line(result)}")
        except KeyboardInterrupt:
            for tc in calls:                      # API ko har tool_call ka jawab chahiye
                if tc["id"] not in answered:
                    session.add({"role": "tool", "tool_call_id": tc["id"],
                                 "content": "STATUS: error\nUser ne beech mein rok diya (Ctrl+C)."})
            events.info("\n[ruk gaya (Ctrl+C)]")
            return RunResult("interrupted")

        # tool results ke TURANT baad image message (view_image ne queue ki thi)
        try:
            img_msg = registry.drain_image_message()
        except Exception as e:  # noqa: BLE001
            img_msg = None
            events.info(f"  [image message nahi ban paya: {e}]")
        if img_msg:
            session.add(img_msg)

    events.info(f"\n[controller] {max_steps} steps ho gaye, ruk raha hu. Aage badhna ho toh 'continue' likh.")
    return RunResult("step_limit")