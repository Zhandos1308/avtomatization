"""YouTube Data API v3 (бесплатно). Секреты: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN.
Необязательно: YT_PRIVACY = public | unlisted | private (по умолчанию public)."""
import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .common import log


def configured():
    return all(os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))


def upload(video, meta):
    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    title = meta["title"]
    if "#shorts" not in title.lower():
        title += " #Shorts"
    body = {
        "snippet": {
            "title": title[:100],
            "description": f'{meta["description"]}\n\n{meta["hashtags"]}',
            "tags": meta["tags"],
            "categoryId": "10",
        },
        "status": {
            "privacyStatus": os.environ.get("YT_PRIVACY", "public"),
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video, mimetype="video/mp4", resumable=True, chunksize=8 * 1024 * 1024)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    log("YouTube: https://youtube.com/shorts/" + resp["id"])
    return resp["id"]
