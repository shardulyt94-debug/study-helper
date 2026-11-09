import os
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

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

courses = service.courses().list(courseStates=["ACTIVE"]).execute().get("courses", [])
print(f"{len(courses)} courses mile\n")

for c in courses:
    print("=", c["name"], "| id:", c["id"])
    work = service.courses().courseWork().list(courseId=c["id"]).execute().get("courseWork", [])
    for w in work[:5]:
        print("   - [assignment]", w["title"], "| due:", w.get("dueDate"), "| attachments:", len(w.get("materials", [])))
    mats = service.courses().courseWorkMaterials().list(courseId=c["id"]).execute().get("courseWorkMaterial", [])
    for m in mats[:5]:
        print("   - [material]", m["title"], "| attachments:", len(m.get("materials", [])))

import io
from googleapiclient.http import MediaIoBaseDownload

os.makedirs("downloads", exist_ok=True)
print("\n--- ATTACHMENT TEST ---")
downloaded = 0
for c in courses:
    items = service.courses().courseWork().list(courseId=c["id"]).execute().get("courseWork", [])
    items += service.courses().courseWorkMaterials().list(courseId=c["id"]).execute().get("courseWorkMaterial", [])
    for it in items:
        for m in it.get("materials", []):
            if "driveFile" in m:
                f = m["driveFile"]["driveFile"]
                print("  [drive file]", f["title"])
                if downloaded <1000 :
                    try:
                        meta = drive.files().get(fileId=f["id"], fields="name,mimeType").execute()
                        exported = meta["mimeType"].startswith("application/vnd.google-apps")
                        if exported:
                            req = drive.files().export_media(fileId=f["id"], mimeType="application/pdf")
                        else:
                            req = drive.files().get_media(fileId=f["id"])
                        buf = io.BytesIO()
                        dl = MediaIoBaseDownload(buf, req)
                        done = False
                        while not done:
                            _, done = dl.next_chunk()
                        name = meta["name"].replace("/", "_") + (".pdf" if exported else "")
                        with open(os.path.join("downloads", name), "wb") as out:
                            out.write(buf.getvalue())
                        print("     -> download ho gayi:", name)
                        downloaded += 1
                    except Exception as e:
                        print("     -> download FAIL:", e)
            elif "link" in m:
                print("  [link]", m["link"].get("title"))
            elif "youtubeVideo" in m:
                print("  [youtube]", m["youtubeVideo"].get("title"))
            elif "form" in m:
                print("  [form]", m["form"].get("title"))