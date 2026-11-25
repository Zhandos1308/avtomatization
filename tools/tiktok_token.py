#!/usr/bin/env python3
"""Один раз на своём компьютере: получить TT_REFRESH_TOKEN.
    TT_CLIENT_KEY=... TT_CLIENT_SECRET=... TT_REDIRECT_URI=https://твой-адрес/callback python tools/tiktok_token.py
Redirect URI должен совпадать с тем, что указан в настройках приложения на developers.tiktok.com."""
import os
import urllib.parse

import requests

key, secret, redirect = os.environ["TT_CLIENT_KEY"], os.environ["TT_CLIENT_SECRET"], os.environ["TT_REDIRECT_URI"]
scope = "user.info.basic,video.upload"
url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
    "client_key": key, "scope": scope, "response_type": "code", "redirect_uri": redirect, "state": "x"})
print("1) Открой ссылку, войди в TikTok и разреши доступ:\n", url)
back = input("\n2) Вставь сюда полный адрес, на который тебя перекинуло: ").strip()
code = urllib.parse.parse_qs(urllib.parse.urlparse(back).query)["code"][0]
r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", data={
    "client_key": key, "client_secret": secret, "code": code,
    "grant_type": "authorization_code", "redirect_uri": redirect}, timeout=30).json()
print("\nTT_REFRESH_TOKEN =", r.get("refresh_token") or r)
