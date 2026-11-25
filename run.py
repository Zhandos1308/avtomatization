#!/usr/bin/env python3
"""Полный цикл для пачки видео: сгенерировать -> залить на включённые платформы.

Переменные окружения:
  COUNT      сколько видео за запуск (10-15 для «хит-потока»), по умолчанию 1
  STYLE      hard (по умолчанию) | hop | piano | midi | mix
               hard  = плитки + хаотичный бит в стиле случайного года 1990-2026
               hop   = плитки + спокойная мелодия
               piano = стикмен за пианино
               midi  = плитки по вашим MIDI из songs/ (права на них ваши!)
               mix   = случайная смесь
  YEARS      диапазон годов для hard, например 1990-2026 (по умолчанию)
  PLATFORMS  youtube,tiktok,instagram (по умолчанию все, где есть секреты)
  UPLOAD_GAP пауза между загрузками, сек (по умолчанию 20)
  DRY_RUN=1  только сгенерировать, ничего не заливать
  SEED       зафиксировать зерно; DURATION длина в секундах (по умолчанию 90 = полный трек)
"""
import glob
import importlib
import json
import os
import random
import subprocess
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))


def pick_year(rng, lo, hi):
    """40% свежие годы (последние 4), остальное равномерно по всему диапазону."""
    if rng.random() < 0.4:
        return rng.randint(max(lo, hi - 3), hi)
    return rng.randint(lo, hi)


def build_cmd(style, rng, seed, episode, out, idx):
    dur = os.environ.get("DURATION", "90")
    base = ["--seed", str(seed), "--episode", str(episode), "--duration", dur, "--out", out]
    if style == "piano":
        return "piano", [sys.executable, os.path.join(HERE, "generate.py")] + base
    if style == "midi":
        songs = sorted(glob.glob(os.path.join(HERE, os.environ.get("SONGS_DIR", "songs"), "*.mid")))
        if not songs:
            raise SystemExit("STYLE=midi, но в songs/ нет .mid файлов")
        f = songs[idx % len(songs)]
        beat = os.environ.get("MIDI_BEAT", "random")        # none | four | electro | edm | trap | random
        if beat == "random":
            beat = rng.choice(["", "four", "electro", "edm", "trap"])
        extra = ["--beat", beat] if beat not in ("", "none") else []
        return f"midi:{os.path.basename(f)}+{beat or 'none'}", [
            sys.executable, os.path.join(HERE, "generate_hop.py"), "--midi", f] + extra + base
    if style == "hop":
        return "hop", [sys.executable, os.path.join(HERE, "generate_hop.py")] + base
    lo, hi = (int(x) for x in os.environ.get("YEARS", "1990-2026").split("-"))
    year = pick_year(rng, lo, hi)
    return f"hard:{year}", [sys.executable, os.path.join(HERE, "generate_hop.py"),
                            "--style", "hard", "--year", str(year)] + base


def main():
    count = int(os.environ.get("COUNT", "1"))
    seed0 = int(os.environ.get("SEED") or time.time())
    day_n = (date.today() - date(2026, 1, 1)).days + 1
    ep0 = int(os.environ.get("EPISODE") or day_n * count)
    gap = float(os.environ.get("UPLOAD_GAP", "20"))
    dry = os.environ.get("DRY_RUN") == "1"
    wanted = [p.strip() for p in os.environ.get("PLATFORMS", "youtube,tiktok,instagram").split(",") if p.strip()]
    style0 = os.environ.get("STYLE", "hard")

    ok_total, fail_total = 0, 0
    for k in range(count):
        seed = seed0 + k * 7919
        episode = ep0 + k + 1
        rng = random.Random(seed)
        style = rng.choice(["hard", "hard", "hard", "hop", "piano"]) if style0 == "mix" else style0
        out = os.path.join(HERE, "out", f"v{episode}_{seed}.mp4")
        label, cmd = build_cmd(style, rng, seed, episode, out, k)
        print(f"\n=== {k + 1}/{count}: {label} (episode {episode}) ===", flush=True)
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError:
            print("ошибка генерации, пропускаю", file=sys.stderr)
            fail_total += 1
            continue
        if dry:
            continue

        with open(os.path.splitext(out)[0] + ".json", encoding="utf-8") as fh:
            meta = json.load(fh)
        ok = []
        for name in wanted:
            mod = importlib.import_module(f"uploaders.{name}")
            if not mod.configured():
                print(f"[{name}] пропущено: нет секретов")
                continue
            try:
                mod.upload(out, meta)
                ok.append(name)
            except Exception as e:                  # одна платформа не должна ронять остальные
                print(f"[{name}] ОШИБКА: {e}", file=sys.stderr)
        ok_total += bool(ok)
        fail_total += not ok
        if k < count - 1:
            time.sleep(gap)

    print(f"\nИтог: видео с успешной загрузкой {ok_total}, без загрузки/с ошибкой {fail_total}")
    if not dry and ok_total == 0 and fail_total:
        sys.exit(1)


if __name__ == "__main__":
    main()
