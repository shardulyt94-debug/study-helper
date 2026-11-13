import os, io, re, json, sys
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
from datetime import datetime
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

ROOT = "classroom"

# Apne course ke naam ke saamne chhota naam likh. Key = Classroom ka asli naam YA uska folder-naam
# (jo classroom\ mein dikhta hai). Jo yahan nahi hoga, uska asli naam hi folder ban jayega.
# DHYAN: naam badalne se naya folder banta hai; purane folder + sync_state.json hata ke dobara sync kar.
# Example:
# "Q- div OOP F.Y 2026-27": "OOP",
SHORT_NAMES = {
}

# Controller (classroom.py) isse chalata hai: token expire ho toh browser mat kholo, exit code 3 do.
NON_INTERACTIVE = ("--non-interactive" in sys.argv) or os.environ.get("SYNC_NON_INTERACTIVE") == "1"
EXIT_RELOGIN = 3
EXIT_NO_CREDENTIALS = 4


def relogin_needed(why):
    print(f"RELOGIN NEEDED: {why}. Terminal mein `python sync.py` khud chala (browser login).")
    sys.exit(EXIT_RELOGIN)


def save_token(creds):
    with open("token.json", "w") as f:
        f.write(creds.to_json())


def login():
    creds = None
    if os.path.exists("token.json"):
        try:
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        except (ValueError, KeyError):
            creds = None  # token.json kharab hai
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_token(creds)
            return creds
        except RefreshError as e:  # token expire/revoke (testing mode mein ~7 din)
            if NON_INTERACTIVE:
                relogin_needed(f"token refresh fail ({e})")
            print("Token refresh fail, browser login chalega:", e)
    elif NON_INTERACTIVE:
        relogin_needed("token.json nahi hai ya valid nahi hai")
    if not os.path.exists("credentials.json"):
        print("credentials.json nahi mili (project folder mein honi chahiye).")
        sys.exit(EXIT_NO_CREDENTIALS)
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    creds = flow.run_local_server(port=0)
    save_token(creds)
    return creds


creds = login()
service = build("classroom", "v1", credentials=creds)
drive = build("drive", "v3", credentials=creds)

state = json.load(open("sync_state.json", encoding="utf-8")) if os.path.exists("sync_state.json") else {}
index = []   # classroom/index.json ke rows (list_materials isse padhta hai)
counts = {"new": 0, "same": 0, "fail": 0}


def safe(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()[:80] or "untitled"


def rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def write_json(path, obj, ascii_only):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=ascii_only)
    os.replace(tmp, path)


def fetch_all(fn, key, **kwargs):
    items, token = [], None
    while True:
        resp = fn(pageToken=token, **kwargs).execute()
        items += resp.get(key, [])
        token = resp.get("nextPageToken")
        if not token:
            return items


def download(file_id, folder):
    meta = drive.files().get(fileId=file_id, fields="name,mimeType,modifiedTime").execute()
    old = state.get(file_id)
    if old and old["modified"] == meta["modifiedTime"] and os.path.exists(old["path"]):
        return old["path"], "pehle se hai"
    native = meta["mimeType"].startswith("application/vnd.google-apps")
    if native:
        req = drive.files().export_media(fileId=file_id, mimeType="application/pdf")
    else:
        req = drive.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    name = safe(meta["name"]) + (".pdf" if native else "")
    path = os.path.join(folder, name)
    if os.path.exists(path) and (not old or old["path"] != path):
        base, ext = os.path.splitext(name)
        path = os.path.join(folder, f"{base}_{file_id[:6]}{ext}")
    with open(path, "wb") as out:
        out.write(buf.getvalue())
    state[file_id] = {"path": path, "modified": meta["modifiedTime"]}
    return path, "naya/update"


def handle(a, folder, notes):
    """Attachment handle karo. Drive file ka local path wapas deta hai (baaki sab ke liye None)."""
    if "driveFile" in a:
        f = a["driveFile"]["driveFile"]
        try:
            path, how = download(f["id"], folder)
            if how == "naya/update":
                counts["new"] += 1
                print("   ", how, ":", os.path.basename(path))   # sirf naya/update dikhao
            else:
                counts["same"] += 1
            notes.append(f"- File: {os.path.basename(path)}")
            return path
        except Exception as e:
            counts["fail"] += 1
            print("    FAIL:", f["title"], "|", e)
            notes.append(f"- File (download fail): {f['title']}")
    elif "link" in a:
        notes.append(f"- Link: {a['link'].get('title', '')} {a['link']['url']}")
    elif "youtubeVideo" in a:
        notes.append(f"- YouTube: {a['youtubeVideo'].get('title', '')} {a['youtubeVideo'].get('alternateLink', '')}")
    elif "form" in a:
        notes.append(f"- Form: {a['form'].get('title', '')} {a['form'].get('formUrl', '')}")
    return None


courses = service.courses().list(courseStates=["ACTIVE"]).execute().get("courses", [])

for c in courses:
    cid = c["id"]
    short = safe(SHORT_NAMES.get(c["name"]) or SHORT_NAMES.get(safe(c["name"])) or c["name"])
    print("\n==", c["name"], "->", short)
    mat_dir = os.path.join(ROOT, short, "materials")
    os.makedirs(mat_dir, exist_ok=True)
    status = {"pending": [], "done": [], "materials": []}

    for m in fetch_all(service.courses().courseWorkMaterials().list, "courseWorkMaterial", courseId=cid):
        notes = []
        title = m.get("title", "untitled")
        posted = (m.get("creationTime") or m.get("updateTime") or "")[:10]
        for a in m.get("materials", []):
            path = handle(a, mat_dir, notes)
            if path:
                index.append({"course": short, "title": title, "posted": posted,
                              "kind": "material", "path": rel(path)})
        status["materials"].append(f"{title} -> " + (", ".join(n[2:] for n in notes) if notes else "no attachments"))

    used_folders = set()
    # id se sort: do assignments ka title same ho toh har baar wahi folder-naam mile
    for w in sorted(fetch_all(service.courses().courseWork().list, "courseWork", courseId=cid), key=lambda x: x["id"]):
        fname = safe(w["title"])
        if fname.lower() in used_folders:          # same/lamba title: folder takrana
            fname = f"{fname[:70]}_{w['id'][-6:]}"
        used_folders.add(fname.lower())
        folder = os.path.join(ROOT, short, "assignments", fname)
        os.makedirs(folder, exist_ok=True)
        d = w.get("dueDate")
        due = f"{d['year']}-{d['month']:02d}-{d['day']:02d}" if d else "no due date"
        posted = (w.get("creationTime") or w.get("updateTime") or "")[:10]
        subs = service.courses().courseWork().studentSubmissions().list(
            courseId=cid, courseWorkId=w["id"], userId="me").execute().get("studentSubmissions", [])
        sub_state = subs[0]["state"] if subs else "UNKNOWN"
        notes = []
        for a in w.get("materials", []):
            path = handle(a, folder, notes)
            if path:
                index.append({"course": short, "title": w["title"], "posted": posted,
                              "kind": "assignment", "path": rel(path)})
        details = os.path.join(folder, "details.md")
        with open(details, "w", encoding="utf-8") as f:
            f.write(f"# {w['title']}\n\nDue: {due}\nSubmission state: {sub_state}\n\n")
            f.write(f"## Description\n{w.get('description', '(koi description nahi)')}\n\n")
            f.write("## Attachments\n" + ("\n".join(notes) if notes else "(koi nahi)") + "\n")
        index.append({"course": short, "title": f"{w['title']} [details, due {due}, {sub_state}]",
                      "posted": posted, "kind": "assignment", "path": rel(details)})
        line = f"{w['title']} (due {due})"
        (status["done"] if sub_state in ("TURNED_IN", "RETURNED") else status["pending"]).append(line)

    with open(os.path.join(ROOT, short, "STATUS.md"), "w", encoding="utf-8") as f:
        f.write(f"# {short} status\nLast sync: {datetime.now():%Y-%m-%d %H:%M}\n\n")
        f.write("## Pending\n" + "\n".join("- " + x for x in sorted(status["pending"])) + "\n\n")
        f.write("## Done\n" + "\n".join("- " + x for x in sorted(status["done"])) + "\n\n")
        f.write("## Materials\n" + "\n".join("- " + x for x in status["materials"]) + "\n")

write_json("sync_state.json", state, ascii_only=True)
write_json(os.path.join(ROOT, "index.json"),
           {"generated": f"{datetime.now():%Y-%m-%d %H:%M}", "items": index}, ascii_only=False)
print(f"\nSync complete: {counts['new']} naya/update, {counts['same']} pehle se the (skip), "
      f"{counts['fail']} fail. index.json mein {len(index)} entries.")