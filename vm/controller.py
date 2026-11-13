"""
Controller (host pe, Windows): CLI chat. Saara dimaag agent_loop.py mein, yahan sirf user se baat.

Chalana (cd D:\\classroom-test\\vm):
    python controller.py                          -> interactive chat (notes mode)
    python controller.py --mode doubts            -> doubts session
    python controller.py --vision-test "D:\\pic.png"   -> sirf check: model image dekh paata hai ya nahi
    python controller.py --resume 20261111-1530   -> purana session aage badhao
    python controller.py --audio "D:\\lec.mp3" --photo "D:\\n1.jpg" --photo "D:\\n2.jpg" "in notes bana"

Chat ke andar:
    /photo <path>   agle message ke saath photo jode
    /audio <path>   agle message ke saath lecture recording jode
    /status         kya jodna baaki hai
    exit            band
"""
from __future__ import annotations

import argparse
import subprocess
import sys

import config
import events
from agent_loop import ApiError, api_call, run_task, RunResult
from session import Session, build_user_message, image_to_part
from tools import registry

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODES = ["notes", "doubts", "assignments"]


# ---------------------------------------------------------------- setup check
def check_setup(need_docker: bool = True, need_constitution: bool = True) -> None:
    problems = []
    if not config.BASE_URL:
        problems.append("AICREDITS_BASE_URL set nahi hai (vm\\.env)")
    if not config.API_KEY:
        problems.append("AICREDITS_API_KEY set nahi hai (vm\\.env)")
    if not config.MODEL:
        problems.append("AGENT_MODEL khali hai. vm\\.env mein likh: AGENT_MODEL=anthropic/claude-sonnet-5.5")
    if need_constitution and not config.CONSTITUTION_PATH.exists():
        problems.append(f"constitution nahi mili: {config.CONSTITUTION_PATH}")
    if need_docker:
        try:
            r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", config.CONTAINER],
                               capture_output=True, text=True)
            if r.returncode != 0 or r.stdout.strip() != "true":
                problems.append(f"container '{config.CONTAINER}' chal nahi raha (Docker Desktop kholke `docker compose up -d`)")
        except FileNotFoundError:
            problems.append("docker command nahi mili")
    if problems:
        print("Setup problem:")
        for p in problems:
            print(" -", p)
        sys.exit(1)


# ---------------------------------------------------------------- vision test
def vision_test(path: str) -> None:
    part, why = image_to_part(__import__("pathlib").Path(path.strip().strip('"')))
    if part is None:
        print("Image taiyar nahi hui:", why)
        return
    content = [
        {"type": "text", "text": "Ye image dhyan se dekh. 1) isme kya dikh raha hai (2-3 line), "
                                 "2) agar text hai toh 2-3 line jaisa dikhe waisa padh ke likh, "
                                 "3) agar diagram hai toh describe kar."},
        part,
    ]
    print(f"Model: {config.MODEL}\nImage bhej raha hu...")
    try:
        reply = api_call([{"role": "user", "content": content}], use_tools=False)
    except ApiError as e:
        print(f"\n[API error {e.status}] {e.text}")
        print("-> Image accept nahi hui (ya model string/format ka issue). Ye poora error mujhe bhej.")
        return
    print(f"\nModel ka jawab:\n{reply.message['content']}")
    print(f"\n(tokens: in {reply.prompt_tokens}, out {reply.completion_tokens}, {reply.seconds:.1f}s)")
    print("Check: agar 'in' tokens sirf ~100 se kam hain toh image ignore hui hai. Photo ke saath aam taur pe 1000+ aate hain (verify nahi kiya).")


# ---------------------------------------------------------------- session helpers
def sync_at_start() -> None:
    events.info("Classroom sync check...")
    out = registry.run_tool("sync_classroom", {})
    lines = out.splitlines()
    events.info("  " + " | ".join(lines[:3])[:300])


def send(session: Session, text: str, photos: list[str], audios: list[str]) -> RunResult:
    first = not session.has_user_message()
    msg, warnings = build_user_message(session, text, photos, audios, first)
    for w in warnings:
        events.info(f"  [warning] {w}")
    session.add(msg)
    res = run_task(session)
    report(res)
    return res


def report(res: RunResult) -> None:
    if res.status == "done" and res.files:
        events.info("\nOutput files:")
        for f in res.files:
            events.info(f"  {f}")
    elif res.status == "done_unchecked":
        events.info("Output file inspect nahi hui, isliye present nahi ki. Model ko 'inspect_document chala' bol ke dekh.")
    elif res.status == "api_error":
        events.info("API error aaya. Dobara try karne ke liye 'continue' likh.")


def parse_cmd(line: str, cmd: str) -> str:
    return line[len(cmd):].strip().strip('"').strip("'")


def main() -> None:
    ap = argparse.ArgumentParser(description="Classroom + Notes agent")
    ap.add_argument("prompt", nargs="*", help="pehla message (optional)")
    ap.add_argument("--mode", choices=MODES, default="notes")
    ap.add_argument("--photo", action="append", default=[], help="photo path (kai baar de sakta hai)")
    ap.add_argument("--audio", action="append", default=[], help="lecture recording path")
    ap.add_argument("--resume", metavar="SESSION_ID")
    ap.add_argument("--vision-test", metavar="IMAGE")
    ap.add_argument("--no-sync", action="store_true", help="Classroom sync skip")
    ap.add_argument("--once", action="store_true", help="prompt dene par ek task ke baad exit")
    args = ap.parse_args()

    if args.vision_test:
        check_setup(need_docker=False, need_constitution=False)
        vision_test(args.vision_test)
        return

    check_setup()
    if args.resume:
        session = Session.load(args.resume)
        events.info(f"Session {session.id} wapas khola ({len(session.messages)} messages). Photos purani wapas nahi aati.")
    else:
        session = Session.new(args.mode)
        if not args.no_sync:
            sync_at_start()

    events.info(f"Model: {config.MODEL} | mode: {session.mode} | session: {session.id}")
    events.info(f"Messages log: {session.log_path}")
    if "inspect_document" not in registry.REGISTRY:
        events.info("(note: inspect_document tool abhi bana nahi, isliye 'inspect zaroori' rule off hai)")

    photos, audios = list(args.photo), list(args.audio)

    if args.prompt:
        send(session, " ".join(args.prompt), photos, audios)
        photos, audios = [], []
        if args.once:
            return

    events.info("Chat shuru. /photo <path>, /audio <path>, /status, exit")
    while True:
        try:
            line = input("\nTu: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        low = line.lower()
        if low in {"exit", "quit"}:
            break
        if low.startswith("/photo "):
            photos.append(parse_cmd(line, "/photo"))
            events.info(f"  photo jodi ({len(photos)} total). Ab message likh.")
            continue
        if low.startswith("/audio "):
            audios.append(parse_cmd(line, "/audio"))
            events.info(f"  audio jodi ({len(audios)} total). Ab message likh.")
            continue
        if low == "/status":
            events.info(f"  photos: {photos or '-'}\n  audio: {audios or '-'}")
            continue
        send(session, line, photos, audios)
        photos, audios = [], []


if __name__ == "__main__":
    main()