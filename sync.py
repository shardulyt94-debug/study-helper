import os, io, re, json
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
from datetime import datetime
from google.auth.transport.requests import Request
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

# Apne course ke asli naam ke saamne chhota naam likh. Jo yahan nahi hoga,
# uska asli naam hi folder ban jayega. Example:
# "FY AIDS Div-B OOP 2026": "OOP",
SHORT_NAMES = {
}

def login():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return creds

creds = login()
service = build("classroom", "v1", credentials=creds)
drive = build("drive", "v3", credentials=creds)

state = json.load(open("sync_state.json")) if os.path.exists("sync_state.json") else {}

def safe(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()[:80] or "untitled"

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
    if "driveFile" in a:
        f = a["driveFile"]["driveFile"]
        try:
            path, how = download(f["id"], folder)
            print("   ", how, ":", os.path.basename(path))
            notes.append(f"- File: {os.path.basename(path)}")
        except Exception as e:
            print("    FAIL:", f["title"], "|", e)
            notes.append(f"- File (download fail): {f['title']}")
    elif "link" in a:
        notes.append(f"- Link: {a['link'].get('title', '')} {a['link']['url']}")
    elif "youtubeVideo" in a:
        notes.append(f"- YouTube: {a['youtubeVideo'].get('title', '')} {a['youtubeVideo'].get('alternateLink', '')}")
    elif "form" in a:
        notes.append(f"- Form: {a['form'].get('title', '')} {a['form'].get('formUrl', '')}")

courses = service.courses().list(courseStates=["ACTIVE"]).execute().get("courses", [])

for c in courses:
    cid = c["id"]
    short = safe(SHORT_NAMES.get(c["name"], c["name"]))
    print("\n==", c["name"], "->", short)
    mat_dir = os.path.join(ROOT, short, "materials")
    os.makedirs(mat_dir, exist_ok=True)
    status = {"pending": [], "done": [], "materials": []}

    for m in fetch_all(service.courses().courseWorkMaterials().list, "courseWorkMaterial", courseId=cid):
        notes = []
        for a in m.get("materials", []):
            handle(a, mat_dir, notes)
        status["materials"].append(f"{m['title']} -> " + (", ".join(n[2:] for n in notes) if notes else "no attachments"))

    for w in fetch_all(service.courses().courseWork().list, "courseWork", courseId=cid):
        folder = os.path.join(ROOT, short, "assignments", safe(w["title"]))
        os.makedirs(folder, exist_ok=True)
        d = w.get("dueDate")
        due = f"{d['year']}-{d['month']:02d}-{d['day']:02d}" if d else "no due date"
        subs = service.courses().courseWork().studentSubmissions().list(
            courseId=cid, courseWorkId=w["id"], userId="me").execute().get("studentSubmissions", [])
        sub_state = subs[0]["state"] if subs else "UNKNOWN"
        notes = []
        for a in w.get("materials", []):
            handle(a, folder, notes)
        with open(os.path.join(folder, "details.md"), "w", encoding="utf-8") as f:
            f.write(f"# {w['title']}\n\nDue: {due}\nSubmission state: {sub_state}\n\n")
            f.write(f"## Description\n{w.get('description', '(koi description nahi)')}\n\n")
            f.write("## Attachments\n" + ("\n".join(notes) if notes else "(koi nahi)") + "\n")
        line = f"{w['title']} (due {due})"
        (status["done"] if sub_state in ("TURNED_IN", "RETURNED") else status["pending"]).append(line)

    with open(os.path.join(ROOT, short, "STATUS.md"), "w", encoding="utf-8") as f:
        f.write(f"# {short} status\nLast sync: {datetime.now():%Y-%m-%d %H:%M}\n\n")
        f.write("## Pending\n" + "\n".join("- " + x for x in sorted(status["pending"])) + "\n\n")
        f.write("## Done\n" + "\n".join("- " + x for x in sorted(status["done"])) + "\n\n")
        f.write("## Materials\n" + "\n".join("- " + x for x in status["materials"]) + "\n")

with open("sync_state.json", "w") as f:
    json.dump(state, f, indent=1)
print("\nSync complete")