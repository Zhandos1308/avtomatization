import os
import subprocess


def log(*a):
    print("[upload]", *a, flush=True)


def save_secret(name, value):
    """Обновляет секрет репозитория через gh CLI, если задан GH_PAT.
    Нужно, когда платформа выдаёт новый refresh/access-токен."""
    pat, repo = os.environ.get("GH_PAT"), os.environ.get("GITHUB_REPOSITORY")
    if not (pat and repo):
        return False
    env = dict(os.environ, GH_TOKEN=pat)
    r = subprocess.run(["gh", "secret", "set", name, "--repo", repo, "--body", value],
                       env=env, capture_output=True, text=True)
    return r.returncode == 0


def caption(meta, limit):
    text = f'{meta["title"]}\n\n{meta["description"]}\n\n{meta["hashtags"]}'
    return text[:limit]
