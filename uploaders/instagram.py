"""Instagram Reels через Instagram API (бесплатно, нужен Professional-аккаунт).
Секреты: IG_TOKEN (долгоживущий токен), IG_USER_ID.
Необязательно: IG_API_VERSION (по умолчанию v25.0), IG_GRAPH_HOST (по умолчанию https://graph.instagram.com;
для входа через Facebook Login поставь https://graph.facebook.com)."""
import os
import time

import requests

from .common import caption, log, save_secret

VER = os.environ.get("IG_API_VERSION", "v25.0")
GRAPH = os.environ.get("IG_GRAPH_HOST", "https://graph.instagram.com")
RUPLOAD = "https://rupload.facebook.com/ig-api-upload"


def configured():
    return all(os.environ.get(k) for k in ("IG_TOKEN", "IG_USER_ID"))


def _refresh(tok):
    """Продлевает долгоживущий токен ещё на 60 дней (работает для токенов Instagram Login)."""
    try:
        j = requests.get("https://graph.instagram.com/refresh_access_token", timeout=30,
                         params={"grant_type": "ig_refresh_token", "access_token": tok}).json()
        new = j.get("access_token")
        if new and new != tok:
            save_secret("IG_TOKEN", new)
            return new
    except Exception:
        pass
    return tok


def _json(r):
    j = r.json()
    if "error" in j:
        raise RuntimeError(f"Instagram API: {j['error']}")
    return j


def upload(video, meta):
    tok = _refresh(os.environ["IG_TOKEN"])
    uid = os.environ["IG_USER_ID"]
    auth = {"Authorization": f"Bearer {tok}"}

    c = _json(requests.post(f"{GRAPH}/{VER}/{uid}/media", headers=auth, timeout=60, data={
        "media_type": "REELS", "upload_type": "resumable",
        "caption": caption(meta, 2200), "share_to_feed": "true"}))
    cid = c["id"]

    size = os.path.getsize(video)
    with open(video, "rb") as fh:
        data = fh.read()
    _json(requests.post(f"{RUPLOAD}/{VER}/{cid}", data=data, timeout=600, headers={
        "Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)}))

    code = "?"
    for _ in range(60):
        time.sleep(5)
        s = _json(requests.get(f"{GRAPH}/{VER}/{cid}", headers=auth, timeout=30,
                               params={"fields": "status_code"}))
        code = s.get("status_code", "?")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram: контейнер в статусе {code}: {s}")
    else:
        raise RuntimeError(f"Instagram: видео не обработалось вовремя (статус {code})")

    pub = _json(requests.post(f"{GRAPH}/{VER}/{uid}/media_publish", headers=auth, timeout=60,
                              data={"creation_id": cid}))
    log(f'Instagram: опубликовано, media id {pub["id"]}')
    return pub["id"]
