"""TikTok Content Posting API (бесплатно).
Секреты: TT_CLIENT_KEY, TT_CLIENT_SECRET, TT_REFRESH_TOKEN.
TT_MODE = inbox (по умолчанию: видео попадает в черновики, публикуешь одним тапом в приложении)
        | direct (сразу публикация; пока приложение не прошло аудит TikTok — только приватно).
TT_PRIVACY (для direct) = PUBLIC_TO_EVERYONE | MUTUAL_FOLLOW_FRIENDS | SELF_ONLY."""
import os
import time

import requests

from .common import caption, log, save_secret

API = "https://open.tiktokapis.com"


def configured():
    return all(os.environ.get(k) for k in ("TT_CLIENT_KEY", "TT_CLIENT_SECRET", "TT_REFRESH_TOKEN"))


def _access_token():
    old = os.environ["TT_REFRESH_TOKEN"]
    r = requests.post(f"{API}/v2/oauth/token/", data={
        "client_key": os.environ["TT_CLIENT_KEY"],
        "client_secret": os.environ["TT_CLIENT_SECRET"],
        "grant_type": "refresh_token",
        "refresh_token": old,
    }, timeout=30)
    j = r.json()
    if "access_token" not in j:
        raise RuntimeError(f"TikTok token error: {j.get('error')} {j.get('error_description')}")
    new = j.get("refresh_token")
    if new and new != old:
        if not save_secret("TT_REFRESH_TOKEN", new):
            log("ВНИМАНИЕ: TikTok выдал новый refresh-токен. Добавь секрет GH_PAT, "
                "чтобы он обновлялся автоматически, иначе перевыпусти токен вручную.")
    return j["access_token"]


def _check(j):
    err = j.get("error", {})
    if err.get("code") not in ("ok", None):
        raise RuntimeError(f"TikTok API: {err}")


def upload(video, meta):
    token = _access_token()
    hdr = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    size = os.path.getsize(video)
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}

    if os.environ.get("TT_MODE", "inbox") == "direct":
        ci = requests.post(f"{API}/v2/post/publish/creator_info/query/", headers=hdr, timeout=30).json()
        _check(ci)
        opts = ci["data"]["privacy_level_options"]
        want = os.environ.get("TT_PRIVACY", "PUBLIC_TO_EVERYONE")
        body = {
            "post_info": {"title": caption(meta, 2200), "privacy_level": want if want in opts else opts[0],
                          "disable_duet": False, "disable_comment": False, "disable_stitch": False},
            "source_info": source,
        }
        endpoint = "/v2/post/publish/video/init/"
    else:
        body, endpoint = {"source_info": source}, "/v2/post/publish/inbox/video/init/"

    j = requests.post(API + endpoint, headers=hdr, json=body, timeout=60).json()
    _check(j)
    publish_id, upload_url = j["data"]["publish_id"], j["data"]["upload_url"]

    with open(video, "rb") as fh:
        data = fh.read()
    r = requests.put(upload_url, data=data, timeout=600, headers={
        "Content-Type": "video/mp4", "Content-Length": str(size),
        "Content-Range": f"bytes 0-{size - 1}/{size}"})
    r.raise_for_status()

    status = "?"
    for _ in range(40):
        time.sleep(5)
        s = requests.post(f"{API}/v2/post/publish/status/fetch/", headers=hdr,
                          json={"publish_id": publish_id}, timeout=30).json()
        status = s.get("data", {}).get("status", "?")
        if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            break
        if status == "FAILED":
            raise RuntimeError(f'TikTok: FAILED {s["data"].get("fail_reason")}')
    log(f"TikTok: {status} (publish_id={publish_id})")
    return publish_id
