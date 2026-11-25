#!/usr/bin/env python3
"""Режим HOP: два стикмена (левая и правая рука) прыгают по падающим плиткам-нотам.
    python generate_hop.py --seed 5 --duration 30 --out out/hop.mp4
"""
import argparse
import bisect
import json
import math
import os
import random
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from generate import (FPS, H, W, WHITE_PCS, compose, compose_hard, era_params, load_font, mix,
                      synth, write_wav)

V = 520.0                       # скорость падения плиток, px/сек
LINE = 1250                     # линия, на которой плитка «играет»
LANE_X = {"L": 270, "R": 810}
COL = {"L": (46, 112, 238), "R": (232, 70, 42)}
SKIN = (255, 228, 205)
OUT = (18, 18, 28)
BG_C = (150, 141, 132)

LABEL = {"L": "LEFT HAND", "R": "RIGHT HAND"}
HOOK = "FIND THIS MUSIC"
HOOK_SUB = "Name the song in the comments"

# ---------------------------------------------------------------- спрайты
KINDS = {
    "dark":   ((30, 36, 72), (240, 140, 50), (196, 100, 34)),
    "white":  ((248, 248, 250), (205, 205, 212), (166, 166, 176)),
    "purple": ((132, 84, 224), (100, 58, 180), (78, 42, 148)),
}


TS = 1.4                          # масштаб плиток


def make_tile(top, s1, s2):
    Z = 4                         # рисуем в 4x и уменьшаем: гладкие края
    cv = Image.new("RGBA", (140 * Z, 130 * Z), (0, 0, 0, 0))
    d = ImageDraw.Draw(cv)

    def z(p):
        return (p[0] * Z, p[1] * Z)

    P0, P1, P2, P3 = (18, 84), (64, 68), (104, 84), (58, 100)
    th = 13
    d.polygon([z(P0), z(P3), z((P3[0], P3[1] + th)), z((P0[0], P0[1] + th))], fill=s1)
    d.polygon([z(P3), z(P2), z((P2[0], P2[1] + th)), z((P3[0], P3[1] + th))], fill=s2)
    d.polygon([z(P0), z(P1), z(P2), z(P3)], fill=top)
    d.line([z((70, 80)), z((90, 16))], fill=(26, 26, 36), width=6 * Z)
    return cv.resize((int(140 * TS), int(130 * TS)), Image.LANCZOS)


def make_shadow():
    m = Image.new("L", (170, 110), 0)
    ImageDraw.Draw(m).polygon([(24, 40), (72, 22), (116, 38), (68, 58)], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(7))
    m = m.resize((int(170 * TS), int(110 * TS)), Image.LANCZOS)
    cv = Image.new("RGBA", m.size, (0, 0, 0, 0))
    cv.putalpha(m.point(lambda p: int(p * 0.30)))
    return cv


def make_soft_ellipse(alpha):
    m = Image.new("L", (110, 44), 0)
    ImageDraw.Draw(m).ellipse((10, 8, 100, 34), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(6))
    cv = Image.new("RGBA", m.size, (0, 0, 0, 0))
    cv.putalpha(m.point(lambda p: int(p * alpha)))
    return cv


TILE_ANCHOR = (61 * TS, 84 * TS)


# ---------------------------------------------------------------- стикмен
def lerp(a, b, k):
    return a + (b - a) * k


def figure(d, X, Y, col, crouch, air, flip, up=0.0, S=1.35):
    """X,Y = точка под ногами. crouch/air in 0..1, flip = угол (рад)."""
    hip = np.array([0.0, -44.0 + 14 * crouch])
    neck = hip + [0, -46]
    sh = neck + [0, 6]
    head = neck + [0, -17]
    legs, arms = [], []
    for side in (-1, 1):
        g_foot = np.array([side * 13.0, 0.0])
        a_foot = hip + ([-24, 32] if side < 0 else [22, 14])
        foot = g_foot + (a_foot - g_foot) * air
        knee = (hip + foot) / 2 + [side * (6 + 12 * crouch + 10 * air), -5 * air]
        legs.append([hip, knee, foot])
        g_hand = sh + [side * 20, 34]
        a_hand = sh + [side * 40, -30]
        hand = g_hand + (a_hand - g_hand) * max(air, up)
        elbow = (sh + hand) / 2 + [side * 10, 4 * (1 - air)]
        arms.append([sh, elbow, hand])
    center = hip + [0, -22]
    c, s = math.cos(flip), math.sin(flip)

    def T(p):
        x, y = p[0] - center[0], p[1] - center[1]
        return (X + (center[0] + c * x - s * y) * S, Y + (center[1] + s * x + c * y) * S)

    def limb(pts):
        P = [T(p) for p in pts]
        d.line(P, fill=OUT, width=int(7 * S + 6), joint="curve")
        for p in (P[0], P[-1]):
            r = (7 * S + 6) / 2
            d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=OUT)
        d.line(P, fill=col, width=int(7 * S), joint="curve")
        for p in (P[0], P[-1]):
            r = 7 * S / 2
            d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=col)

    for l in legs:
        limb(l)
    limb([neck, hip])
    for a in arms:
        limb(a)
    hx, hy = T(head)
    r = 15 * S
    d.ellipse((hx - r - 3, hy - r - 3, hx + r + 3, hy + r + 3), fill=OUT)
    d.ellipse((hx - r, hy - r, hx + r, hy + r), fill=SKIN)
    deg = math.degrees(flip)
    d.pieslice((hx - r, hy - r, hx + r, hy + r), 180 + deg, 360 + deg, fill=col)


# ---------------------------------------------------------------- рендер
def build_tiles(events, step):
    tiles = {}
    for h in "LR":
        seen, lst = set(), []
        for e in events:
            if e["hand"] != h:
                continue
            k = round(e["t"], 4)
            if k in seen:
                continue
            seen.add(k)
            lst.append(e)
        lst.sort(key=lambda e: e["t"])
        lo, hi = min(e["m"] for e in lst), max(e["m"] for e in lst)
        out = []
        for e in lst:
            norm = (e["m"] - lo) / max(1, hi - lo)
            bar = e["t"] / (8 * step)
            frac = bar - math.floor(bar + 1e-6)
            if abs(bar - round(bar)) < 1e-6:
                kind = "white"                      # первая доля такта
            elif abs(frac - 0.5) < 1e-6:
                kind = "purple"                     # середина такта
            else:
                kind = "dark"
            out.append({"t": e["t"], "x": LANE_X[h] + (norm - 0.5) * 300,
                        "kind": kind, "finger": 1 + int(round(norm * 3.0)) + (1 if h == "R" else 0)})
        tiles[h] = out
    return tiles


def render(events, step, audio, out, total, seed, episode, sub_text=HOOK_SUB):
    rng = random.Random(seed * 13 + 5)
    tiles = build_tiles(events, step)

    # фон: бежевый градиент + радиальное свечение
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.sqrt(((xx - 540) / 700.0) ** 2 + ((yy - 900) / 900.0) ** 2)
    k = np.clip(1 - r, 0, 1)[..., None] ** 1.5
    arr = np.array(BG_C)[None, None, :] * (1 - k) + np.array((205, 195, 180))[None, None, :] * k
    arr[:, 539:541] += 14
    bg_arr = np.clip(arr, 0, 255).astype(np.uint8)
    bg = Image.fromarray(bg_arr)

    sprites, hit_sprites = {}, {}
    for kind, (t, s1, s2) in KINDS.items():
        sprites[kind] = make_tile(t, s1, s2)
        for h in "LR":
            hit_sprites[(kind, h)] = make_tile(mix(COL[h], (10, 20, 50), 0.45), s1, s2)
    shadow = make_shadow()
    ell = [make_soft_ellipse(a) for a in (0.10, 0.18, 0.26, 0.34)]

    f_sub, f_pill, f_num = load_font(38), load_font(46), load_font(24)
    hook_fonts = {s: load_font(s) for s in (84, 85, 86, 87)}
    t_end = max(tl["t"] for h in "LR" for tl in tiles[h])      # после финального аккорда экран замирает
    nframes = int(total * FPS)
    dt = 1.0 / FPS
    beat = step * 2

    # для стикменов: список (время, x) с «виртуальной» плиткой перед первой
    path = {}
    for h in "LR":
        ts = [t["t"] for t in tiles[h]]
        xs = [t["x"] for t in tiles[h]]
        ts = [ts[0] - 0.6] + ts
        xs = [xs[0]] + xs
        path[h] = (ts, xs)

    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-i", audio, "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out],
        stdin=subprocess.PIPE)

    for f in range(nframes):
        t = f * dt
        img = bg.copy()
        d = ImageDraw.Draw(img)

        te = min(t, t_end)                                   # время прокрутки
        # --- плитки ---
        for h in "LR":
            for i, tl in enumerate(tiles[h]):
                y = LINE - V * (tl["t"] - te)
                if y < -160 or y > H + 140:
                    continue
                img.paste(shadow, (int(tl["x"] + (36 - 70) * TS), int(y + (28 - 40) * TS)), shadow)
        for h in "LR":
            for i, tl in enumerate(tiles[h]):
                y = LINE - V * (tl["t"] - te)
                if y < -160 or y > H + 140:
                    continue
                spr = hit_sprites[(tl["kind"], h)] if t >= tl["t"] else sprites[tl["kind"]]
                img.paste(spr, (int(tl["x"] - TILE_ANCHOR[0]), int(y - TILE_ANCHOR[1])), spr)
                bx, by = tl["x"], y + 58
                d.ellipse((bx - 16, by - 16, bx + 16, by + 16), fill=COL[h])
                d.text((bx, by), str(tl["finger"]), font=f_num, fill=(255, 255, 255), anchor="mm")

        # --- стикмены ---
        for h in "LR":
            ts, xs = path[h]
            i = bisect.bisect_right(ts, t) - 1
            i = max(i, 0)
            if i >= len(ts) - 1:                            # финал: радостно подпрыгивают на месте
                X = xs[-1]
                k = (t - ts[-1]) / 0.55
                Y = LINE - 2 - 55 * abs(math.sin(math.pi * k))
                figure(d, X, Y, COL[h], 0.0, 0.45, 0.0, up=1.0)
                continue
            dur = ts[i + 1] - ts[i]
            u = min(max((t - ts[i]) / dur, 0.0), 1.0)
            su = u * u * (3 - 2 * u)
            X = lerp(xs[i], xs[i + 1], su)
            hop = min(300.0, 60 + 190 * dur)
            arc = 4 * u * (1 - u)
            Y = LINE - 2 - hop * arc
            crouch = max(0.0, (0.12 - u) / 0.12, (u - 0.88) / 0.12) * 0.9
            air = min(1.0, arc * 1.5)
            flip = 0.0
            if dur >= 0.5 and i % 3 == 0 and i > 0:
                flip = (1 if (i // 3) % 2 == 0 else -1) * 2 * math.pi * su
            lvl = min(3, int(max(0, 1 - arc) * 4))
            sp = ell[lvl]
            img.paste(sp, (int(X - 55 + 24), int(LINE + 4)), sp)
            figure(d, X, Y, COL[h], crouch, air, flip)

        # --- кольца и конфетти при ударе ---
        for h in "LR":
            for tl in tiles[h]:
                age = t - tl["t"]
                if 0 <= age < 0.40:
                    y = LINE + V * (min(t, t_end) - tl["t"])
                    kk = age / 0.40
                    rad = 28 + 62 * kk
                    ring = mix(COL[h], BG_C, kk)
                    d.ellipse((tl["x"] - rad, y - rad, tl["x"] + rad, y + rad), outline=ring, width=4)
                    for j in range(8):
                        a = j * math.pi / 4 + tl["t"] * 7
                        rr = 18 + 66 * kk
                        cx, cy = tl["x"] + math.cos(a) * rr, y + math.sin(a) * rr * 0.8 - 8
                        d.ellipse((cx - 6, cy - 3, cx + 6, cy + 3), fill=mix((240, 205, 90), BG_C, kk))

        # --- подписи ---
        pulse = 1 + 0.04 * math.exp(-((t % beat) / beat) * 5)
        d.text((W / 2, 80), HOOK, font=hook_fonts[int(round(84 * pulse))], fill=(255, 255, 255), anchor="mm",
               stroke_width=8, stroke_fill=(24, 24, 36))
        d.text((W / 2, 150), sub_text, font=f_sub, fill=(255, 255, 255), anchor="mm",
               stroke_width=5, stroke_fill=(24, 24, 36))
        for h in "LR":
            tw = d.textlength(LABEL[h], font=f_pill)
            cx, cy = LANE_X[h], 235
            d.rounded_rectangle((cx - tw / 2 - 32, cy - 30, cx + tw / 2 + 32, cy + 30), radius=30, fill=COL[h])
            d.text((cx, cy), LABEL[h], font=f_pill, fill=(255, 255, 255), anchor="mm")

        proc.stdin.write(img.tobytes())

    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg завершился с ошибкой")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--bpm", type=int, default=0)
    ap.add_argument("--episode", type=int, default=1)
    ap.add_argument("--out", default="out/hop.mp4")
    ap.add_argument("--style", choices=["calm", "hard"], default="calm")
    ap.add_argument("--year", type=int, default=2026, help="эпоха для стиля hard (1990-2026)")
    ap.add_argument("--midi", default="", help="путь к своему MIDI-файлу (права на него ваши)")
    ap.add_argument("--midi-start", type=float, default=0.0)
    ap.add_argument("--speed", type=float, default=0.0, help="скорость падения плиток, px/с")
    ap.add_argument("--beat", choices=["", "four", "electro", "edm", "trap"], default="",
                    help="добавить барабаны поверх MIDI (для режима --midi)")
    a = ap.parse_args()

    global V
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    rng = random.Random(a.seed)
    drums, sub = [], HOOK_SUB
    title = f"Can you find this song? #{a.episode}"
    desc = "Two stickmen, two hands, one melody. Do you know this music? Name it in the comments!"
    tags = "#guessthesong #piano #music #stickman #shorts #satisfying"
    if a.midi:
        from midi_import import load_midi
        events, drums, step, bpm, total, pass_len = load_midi(a.midi, a.midi_start, a.duration)
        mode, bars = "midi", 0
        V = a.speed or 700.0
        if a.beat:                      # бит входит со второго прохода мелодии
            from generate import make_drums
            s16 = 60.0 / bpm / 4
            off = pass_len if total - 1.5 > pass_len * 1.5 else 0.0
            nb = int((total - off) / (16 * s16)) + 1
            drums = [dict(d, t=d["t"] + off) for d in make_drums(rng, a.beat, nb, s16)]
    elif a.style == "hard":
        era = era_params(a.year)
        bpm = a.bpm or rng.randint(*era["bpm"])
        s16 = 60.0 / bpm / 4
        bars = max(4, math.ceil((a.duration - 1.5) / (16 * s16) / 4) * 4)
        events, drums, step, mode = compose_hard(rng, bpm, bars, era)
        total = bars * 16 * s16 + 1.5
        V = a.speed or 700.0
        sub = f"{a.year}-style original beat"
        title = f"{a.year} vibes: can you find this music? #{a.episode}"
        desc = (f"An original {a.year}-style beat played by two stickmen, left hand vs right hand. "
                "Can you find this music? Guess in the comments!")
        tags = f"#guessthesong #{a.year} #beat #piano #stickman #shorts"
    else:
        bpm = a.bpm or rng.randrange(92, 117, 4)
        step = 60.0 / bpm / 2
        bars = max(4, round((a.duration - 1.5) / (8 * step) / 4) * 4)
        events, step, mode = compose(rng, bpm, bars, lh_step=2)
        total = bars * 8 * step + 1.5
        V = a.speed or 520.0

    wav = os.path.splitext(a.out)[0] + ".wav"
    print(f"[hop] seed={a.seed} bpm={bpm:.0f} mode={mode} bars={bars} notes={len(events)} "
          f"drums={len(drums)} length={total:.1f}s", flush=True)
    write_wav(wav, synth(events, total, a.seed, drums))
    render(events, step, wav, a.out, total, a.seed, a.episode, sub)
    os.remove(wav)

    meta = {
        "title": title,
        "description": desc,
        "tags": ["piano", "stickman", "shorts", "guessthesong", "music", "beat", "animation"],
        "hashtags": tags,
        "seed": a.seed, "bpm": bpm, "mode": mode, "duration": round(total, 1),
    }
    with open(os.path.splitext(a.out)[0] + ".json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    print("готово:", a.out, flush=True)


if __name__ == "__main__":
    main()
