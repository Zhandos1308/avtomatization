#!/usr/bin/env python3
"""Stickman Piano: синтезирует музыку и рисует вертикальное видео 1080x1920.

Зависимости: numpy, Pillow, ffmpeg. Всё детерминировано по --seed.
    python generate.py --seed 42 --duration 30 --out out/video.mp4
"""
import argparse
import colorsys
import json
import math
import os
import random
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS, SR = 1080, 1920, 30, 44100
LOW, HIGH = 48, 84                      # C3 .. C6
WHITE_PCS = {0, 2, 4, 5, 7, 9, 11}
KY = 1400                               # верх клавиш
KEY_H, BLACK_H = 250, 155
FALL_TOP = KY - 100                     # верх пианино (стикмен стоит за ним)

# --------------------------------------------------------------------------
# МУЗЫКА
# --------------------------------------------------------------------------
SCALES = {"major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10]}
PROGS = {
    "major": [[0, 4, 5, 3], [0, 5, 3, 4], [0, 3, 4, 4], [5, 3, 0, 4], [0, 2, 3, 4]],
    "minor": [[0, 5, 2, 6], [0, 3, 6, 5], [0, 5, 3, 4], [0, 6, 5, 4]],
}
RHYTHMS = [
    [(0, 2), (2, 2), (4, 2), (6, 2)],
    [(0, 3), (3, 1), (4, 2), (6, 2)],
    [(0, 1), (1, 1), (2, 2), (4, 4)],
    [(0, 4), (4, 2), (6, 2)],
    [(0, 2), (2, 1), (3, 1), (4, 4)],
    [(0, 1), (1, 1), (2, 1), (3, 1), (4, 2), (6, 2)],
    [(0, 2), (2, 2), (4, 1), (5, 1), (6, 2)],
]


def deg2midi(root, scale, d):
    return root + scale[d % 7] + 12 * (d // 7)


def clampm(m):
    while m > HIGH:
        m -= 12
    while m < LOW:
        m += 12
    return m


def chord_tones(c, lo=7, hi=15):
    return sorted({c + o + 7 * k for o in (0, 2, 4) for k in (-1, 0, 1, 2) if lo <= c + o + 7 * k <= hi})


def make_bar(rng, c, deg):
    notes = []
    for s, ln in rng.choice(RHYTHMS):
        if s in (0, 4):
            cands = sorted(chord_tones(c), key=lambda x: abs(x - deg) + rng.random() * 1.5)
            deg = cands[0]
        else:
            deg = max(7, min(15, deg + rng.choice([-2, -1, -1, 0, 1, 1, 2])))
        notes.append((s, ln, deg))
    return notes, deg


def compose(rng, bpm, bars, lh_step=1):
    mode = rng.choice(list(SCALES))
    scale = SCALES[mode]
    root = 48 + rng.choice([0, 2, 3, 5, 7])
    prog = rng.choice(PROGS[mode])
    step = 60.0 / bpm / 2

    def phrase():
        deg, out = rng.choice([7, 9, 11]), []
        for c in prog:
            notes, deg = make_bar(rng, c, deg)
            out.append(notes)
        return out

    A, B = phrase(), phrase()
    A2 = A[:3] + [make_bar(rng, prog[3], 9)[0]]
    blocks = [A, A2, B, A]

    ev = []

    def add(t, dur, m, hand, vel):
        ev.append({"t": t, "dur": dur, "m": clampm(m), "hand": hand, "vel": vel})

    for b in range(bars):
        t0 = b * 8 * step
        c = prog[b % 4]
        if b == bars - 1:                                   # финальный аккорд
            add(t0, step * 7, root, "L", 0.7)
            add(t0, step * 7, root + 7, "L", 0.6)
            add(t0, step * 7, deg2midi(root, scale, 7), "R", 0.85)
            add(t0, step * 7, deg2midi(root, scale, 9), "R", 0.75)
            continue
        for i, dd in enumerate([c, c + 4, c + 2, c + 4, c, c + 4, c + 2, c + 4]):
            if i % lh_step:
                continue
            m = deg2midi(root, scale, dd)
            while m > 67:
                m -= 12
            add(t0 + i * step, step * 1.7 * lh_step, m, "L", 0.62 if i % 4 == 0 else 0.42)
        for s, ln, d in blocks[(b // 4) % 4][b % 4]:
            add(t0 + s * step, ln * step * 0.95, deg2midi(root, scale, d), "R", 0.9 if s in (0, 4) else 0.7)
    ev.sort(key=lambda e: e["t"])
    return ev, step, mode


SOFT_AMPS = (1.0, .55, .32, .2, .12, .07, .04)
BRIGHT_AMPS = (1.0, .75, .55, .42, .3, .2, .12)

LH_PATS = [(0, 3, 6, 8, 11, 14), (0, 6, 8, 14), (0, 2, 4, 6, 8, 10, 12, 14),
           (0, 3, 8, 11), (0, 4, 7, 10, 12, 15)]


def era_params(year):
    """Общие черты эпохи (темп, лад, плотность, тип ударных). Не копирует конкретные песни."""
    if year <= 1999:
        return dict(bpm=(122, 140), minor=0.70, density=0.55, drums="four", bright=False)
    if year <= 2009:
        return dict(bpm=(118, 134), minor=0.60, density=0.60, drums="electro", bright=True)
    if year <= 2019:
        return dict(bpm=(122, 150), minor=0.50, density=0.70, drums="edm", bright=True)
    return dict(bpm=(136, 172), minor=0.85, density=0.85, drums="trap", bright=True)


def make_drums(rng, kind, bars, s16):
    hits = []

    def h(b, s, k, v):
        hits.append({"t": (b * 16 + s) * s16, "kind": k, "vel": v})

    for b in range(bars):
        if b == bars - 1:
            h(b, 0, "kick", 1.0)
            continue
        n0 = len(hits)
        if kind == "four":
            for s in (0, 4, 8, 12):
                h(b, s, "kick", 1.0)
            for s in (4, 12):
                h(b, s, "snare", 0.8)
            for s in (2, 6, 10, 14):
                h(b, s, "hat", 0.5)
        elif kind == "electro":
            for s in (0, 4, 8, 10, 12):
                h(b, s, "kick", 0.95)
            for s in (4, 12):
                h(b, s, "snare", 0.85)
            for s in range(0, 16, 2):
                h(b, s, "hat", 0.4)
        elif kind == "edm":
            for s in (0, 4, 8, 12):
                h(b, s, "kick", 1.0)
            for s in (4, 12):
                h(b, s, "snare", 0.9)
            for s in range(16):
                h(b, s, "hat", 0.55 if s % 4 == 2 else 0.25)
        else:                                               # trap
            h(b, 0, "kick", 1.0)
            for s in rng.sample([3, 6, 7, 10, 11, 14], rng.choice([1, 2, 2])):
                h(b, s, "kick", 0.85)
            h(b, 8, "snare", 0.95)
            for s in range(16):
                if rng.random() > 0.22:
                    h(b, s, "hat", rng.uniform(0.25, 0.55))
        if rng.random() < 0.35:                             # хаос: лишний удар бочки
            h(b, rng.choice([3, 7, 11, 15]), "kick", 0.6)
        if b % 4 == 3:                                      # хаос: подводка в конце фразы
            for s in (12, 13, 14, 15):
                h(b, s, "snare", 0.5 + 0.1 * (s - 12))
        if bars > 12:
            if b < 4:                                       # вступление: только хэты
                hits[n0:] = [x for x in hits[n0:] if x["kind"] == "hat"]
            elif b % 16 == 15:                              # брейк: рол снейра перед новой секцией
                hits[n0:] = [{"t": (b * 16 + s) * s16, "kind": "snare", "vel": 0.3 + 0.045 * s}
                             for s in range(6, 16)]
    return hits


def compose_hard(rng, bpm, bars, era):
    """Хаотичный быстрый жанр: синкопы, скачки, трели, повтор фразы с мутациями."""
    mode = "minor" if rng.random() < era["minor"] else "major"
    scale = SCALES[mode]
    root = 48 + rng.choice([0, 1, 2, 3, 5, 7, 8])
    base_root = root
    prog = rng.choice(PROGS[mode])
    s16 = 60.0 / bpm / 4
    dens = era["density"]
    ev = []

    def add(t, dur, m, hand, vel, br):
        ev.append({"t": t, "dur": dur, "m": clampm(m), "hand": hand, "vel": vel, "bright": br})

    def phrase():
        steps, consec = [0], 0
        for s in range(1, 64):
            p = (0.55 if s % 4 == 0 else 0.30 if s % 2 == 0 else 0.16) * dens * 1.5
            if rng.random() < p:
                if s - steps[-1] == 1:
                    if consec >= 2:
                        continue
                    consec += 1
                else:
                    consec = 0
                steps.append(s)
        out, deg = [], rng.choice([8, 10, 12])
        for s in steps:
            r = rng.random()
            if r < 0.16:
                deg += rng.choice([-7, -5, -4, 4, 5, 7])
            elif r < 0.50:
                deg += rng.choice([-2, -1, 1, 2])
            elif r >= 0.72:
                deg += rng.choice([-3, 3])
            deg = max(7, min(16, deg))
            if s % 8 == 0:
                c = prog[(s // 16) % 4]
                deg = min(chord_tones(c, 7, 16), key=lambda x: abs(x - deg))
            out.append((s, deg))
        return out

    def mutate(ph):
        out = []
        for s, d in ph:
            if s and rng.random() < 0.08:
                continue
            if rng.random() < 0.20:
                d = max(7, min(16, d + rng.choice([-2, -1, 1, 2])))
            out.append((s, d))
        for _ in range(3):
            s = rng.randrange(1, 64)
            if all(s != x for x, _ in out):
                out.append((s, rng.randint(8, 15)))
        return sorted(out)

    A, B, C = phrase(), phrase(), phrase()
    blocks = [A, mutate(A), B, mutate(A), C, mutate(B), A, mutate(C)]
    for b in range(bars):
        t0 = b * 16 * s16
        root = base_root + (2 if bars > 16 and b >= bars * 2 // 3 else 0)   # подъём тональности к финалу
        if b == bars - 1:                                   # финальный аккорд
            d = s16 * 10
            add(t0, d, root, "L", 0.8, False)
            add(t0, d, root + 7, "L", 0.7, False)
            add(t0, d, deg2midi(root, scale, 7), "R", 0.95, True)
            add(t0, d, deg2midi(root, scale, 9), "R", 0.85, True)
            continue
        blk = blocks[(b // 4) % len(blocks)]
        for i, (s, deg) in enumerate(blk):
            if s // 16 != b % 4:
                continue
            nxt = blk[i + 1][0] if i + 1 < len(blk) else 64
            dur = min(nxt - s, 4) * s16 * 0.92
            add(t0 + (s % 16) * s16, max(dur, s16 * 0.8), deg2midi(root, scale, deg),
                "R", 0.95 if s % 4 == 0 else 0.7, True)
        if b % 4 == 0:
            lh_pat = rng.choice(LH_PATS)
        c = prog[b % 4]
        for s in lh_pat:
            m = deg2midi(root, scale, c + (4 if s % 8 == 6 else 0))
            while m > 62:
                m -= 12
            add(t0 + s * s16, s16 * 2.2, m, "L", 0.75, False)
    ev.sort(key=lambda e: e["t"])
    return ev, make_drums(rng, era["drums"], bars, s16), s16 * 2, mode


def drum_sample(kind, nrng):
    if kind == "kick":
        t = np.arange(int(0.28 * SR)) / SR
        ph = 2 * np.pi * np.cumsum(45 + 110 * np.exp(-t * 28)) / SR
        return np.sin(ph) * np.exp(-t * 13) * 0.75
    if kind == "snare":
        t = np.arange(int(0.22 * SR)) / SR
        return (0.6 * nrng.standard_normal(len(t)) * np.exp(-t * 22)
                + 0.45 * np.sin(2 * np.pi * 185 * t) * np.exp(-t * 30)) * 0.7
    t = np.arange(int(0.07 * SR)) / SR
    return np.diff(nrng.standard_normal(len(t) + 1)) * np.exp(-t * 70) * 0.28


def add_drums(L, R, drums, nrng):
    cache = {k: drum_sample(k, nrng) for k in ("kick", "snare", "hat")}
    for d in drums:
        s = cache.get(d["kind"])
        if s is None:
            continue
        i0 = int(d["t"] * SR)
        seg = s * d["vel"]
        L[i0:i0 + len(seg)] += seg[:len(L) - i0]
        R[i0:i0 + len(seg)] += seg[:len(R) - i0]


def synth(events, total, seed, drums=None):
    nrng = np.random.default_rng(seed)
    n = int((total + 3) * SR)
    L, R = np.zeros(n), np.zeros(n)
    for e in events:
        f = 440.0 * 2 ** ((e["m"] - 69) / 12)
        d = e["dur"]
        length = int((d + 1.5) * SR)
        t = np.arange(length) / SR
        r0 = 0.9 + f / 450
        sig = np.zeros(length)
        for h, a in enumerate(BRIGHT_AMPS if e.get("bright") else SOFT_AMPS, 1):
            fh = f * h * (1 + 0.0003 * h * h)
            if fh > 9000:
                break
            sig += a * np.sin(2 * np.pi * fh * t + h) * np.exp(-t * r0 * (1 + 0.55 * (h - 1)))
        sig += 0.35 * np.sin(2 * np.pi * f * 1.0015 * t) * np.exp(-t * r0)
        sig *= np.minimum(1, t / 0.004) * np.where(t > d, np.exp(-(t - d) * 5), 1.0) * e["vel"]
        k = int(0.01 * SR)
        sig[:k] += nrng.standard_normal(k) * np.exp(-np.arange(k) / (0.002 * SR)) * 0.04 * e["vel"]
        p = 0.3 + 0.4 * (e["m"] - LOW) / (HIGH - LOW)
        i0 = int(e["t"] * SR)
        L[i0:i0 + length] += sig * math.cos(p * math.pi / 2)
        R[i0:i0 + length] += sig * math.sin(p * math.pi / 2)

    def reverb(x):
        m = int(1.4 * SR)
        ir = nrng.standard_normal(m) * np.exp(-np.arange(m) / SR * 3.5)
        ir /= math.sqrt(np.sum(ir ** 2))
        size = 1 << int(math.ceil(math.log2(len(x) + m)))
        return np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[:len(x)]

    L = L + 0.30 * reverb(L)
    R = R + 0.30 * reverb(R)
    if drums:
        add_drums(L, R, drums, nrng)
    n_out = int(total * SR)
    L, R = L[:n_out], R[:n_out]
    fade = int(0.8 * SR)
    ramp = np.linspace(1, 0, fade)
    L[-fade:] *= ramp
    R[-fade:] *= ramp
    peak = max(np.abs(L).max(), np.abs(R).max(), 1e-9)
    st = np.stack([L, R], axis=1) / peak * 0.9
    return (st * 32767).astype(np.int16)


def write_wav(path, data):
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


# --------------------------------------------------------------------------
# ВИДЕО
# --------------------------------------------------------------------------
def load_font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


WHITES = [m for m in range(LOW, HIGH + 1) if m % 12 in WHITE_PCS]
KW = W / len(WHITES)
WIDX = {m: i for i, m in enumerate(WHITES)}


def key_x(m):
    return WIDX[m] * KW + KW / 2 if m in WIDX else WIDX[m - 1] * KW + KW


def mix(a, b, k):
    return tuple(int(a[i] * (1 - k) + b[i] * k) for i in range(3))


def ik(sh, tgt, side, l1=270.0, l2=270.0):
    dx, dy = tgt[0] - sh[0], tgt[1] - sh[1]
    d = max(1e-3, min(math.hypot(dx, dy), l1 + l2 - 0.5))
    a = math.atan2(dy, dx)
    b = math.acos(max(-1, min(1, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d))))
    best = None
    for s in (-1, 1):
        ex, ey = sh[0] + l1 * math.cos(a + s * b), sh[1] + l1 * math.sin(a + s * b)
        score = side * (ex - sh[0]) + 0.5 * (ey - sh[1])
        if best is None or score > best[0]:
            best = (score, (ex, ey))
    return best[1], (sh[0] + d * math.cos(a), sh[1] + d * math.sin(a))


def draw_note(d, x, y, s, col):
    d.ellipse((x - 12 * s, y - 8 * s, x + 12 * s, y + 8 * s), fill=col)
    d.line((x + 11 * s, y, x + 11 * s, y - 42 * s), fill=col, width=max(2, int(4 * s)))
    d.line((x + 11 * s, y - 42 * s, x + 26 * s, y - 28 * s), fill=col, width=max(2, int(4 * s)))


def render(events, audio, out, total, bpm, seed, episode, title):
    rng = random.Random(seed * 7 + 1)
    hue = rng.random()

    def hsv(h, s, v):
        r, g, b = colorsys.hsv_to_rgb(h % 1, s, v)
        return int(r * 255), int(g * 255), int(b * 255)

    top, bot = hsv(hue, 0.55, 0.30), hsv(hue + 0.07, 0.70, 0.10)
    accent = hsv(hue + 0.5, 0.75, 1.0)
    stick = (246, 246, 250)
    dark = (24, 24, 34)

    ys = np.linspace(0, 1, H)[:, None, None]
    arr = np.array(top)[None, None, :] * (1 - ys) + np.array(bot)[None, None, :] * ys
    arr = np.repeat(arr, W, axis=1)
    for _ in range(150):
        x, y, s, v = rng.randrange(W), rng.randrange(0, KY - 150), rng.choice([2, 2, 3, 4]), rng.uniform(.3, .9)
        arr[y:y + s, x:x + s] = arr[y:y + s, x:x + s] * (1 - v) + 255 * v
    bg_arr = arr.astype(np.uint8)
    bg = Image.fromarray(bg_arr)

    f_title, f_sub = load_font(86), load_font(40)
    beat = 60.0 / bpm
    bar_len = beat * 4
    bars = int(round((total - 1.5) / bar_len))

    # прыжки: (старт, длительность, высота, руки вверх)
    jumps = []
    for b in range(bars):
        t0 = b * bar_len
        if (b % 4 == 0 and b > 0) or b == bars - 1:
            jumps.append((t0, 0.55, 260, True))
        else:
            if rng.random() < 0.35:
                jumps.append((t0, 0.32, 70, False))
            if rng.random() < 0.35:
                jumps.append((t0 + 2 * beat, 0.32, 70, False))

    nframes = int(total * FPS)
    dt = 1.0 / FPS
    hands = {"L": {"x": 300.0, "p": 0.0}, "R": {"x": 700.0, "p": 0.0}}
    by_hand = {h: [e for e in events if e["hand"] == h] for h in "LR"}
    cx = 540.0
    particles, spawn_i = [], 0

    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-i", audio, "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out],
        stdin=subprocess.PIPE)

    for f in range(nframes):
        t = f * dt
        # --- состояние рук ---
        for h in "LR":
            lst = by_hand[h]
            tgt_x = hands[h]["x"]
            for e in lst:
                if e["t"] <= t + 0.10:
                    tgt_x = key_x(e["m"])
                else:
                    break
            pressed = any(e["t"] <= t < e["t"] + max(e["dur"] * 0.9, 0.14) for e in lst)
            hands[h]["x"] += (tgt_x - hands[h]["x"]) * (1 - math.exp(-dt * 22))
            hands[h]["p"] += ((1.0 if pressed else 0.0) - hands[h]["p"]) * min(1, dt * 25)

        # --- прыжок ---
        off, up = 0.0, 0.0
        for (j0, jd, jh, jup) in jumps:
            if j0 <= t < j0 + jd:
                u = (t - j0) / jd
                v = 4 * u * (1 - u)
                if jh * v > off:
                    off = jh * v
                    up = v ** 0.5 if jup else 0.0
        air = min(1.0, off / 260.0)

        target_cx = max(300, min(780, (hands["L"]["x"] + hands["R"]["x"]) / 2))
        cx += (target_cx - cx) * (1 - math.exp(-dt * 6))
        bob = 9 * abs(math.sin(math.pi * t / beat))
        ny = 1045 - off - bob
        head = (cx, ny - 92)
        shL, shR = (cx - 42, ny + 14), (cx + 42, ny + 14)
        hip = (cx, ny + 215)

        # --- новые частицы ---
        while spawn_i < len(events) and events[spawn_i]["t"] <= t:
            e = events[spawn_i]
            for _ in range(2):
                particles.append([key_x(e["m"]), KY - 10, rng.uniform(-50, 50), rng.uniform(-420, -260),
                                  t, rng.uniform(1.0, 1.5), rng.uniform(0.8, 1.3)])
            spawn_i += 1

        img = bg.copy()
        d = ImageDraw.Draw(img)

        # --- ореол ---
        pulse = math.exp(-((t % beat) / beat) * 5)
        rad = 430 + 45 * pulse
        d.ellipse((cx - rad, 1000 - rad, cx + rad, 1000 + rad), fill=mix(top, accent, 0.10 + 0.07 * pulse))

        # --- ноги, торс, голова (за пианино) ---
        lw = 20
        for sgn in (-1, 1):
            foot = (cx + sgn * 55, hip[1] + 175 - 95 * air)
            knee = ((hip[0] + foot[0]) / 2 + sgn * (10 + 45 * air), (hip[1] + foot[1]) / 2 - 10 * air)
            d.line([hip, knee, foot], fill=stick, width=lw, joint="curve")
            d.ellipse((foot[0] - 10, foot[1] - 10, foot[0] + 10, foot[1] + 10), fill=stick)
        d.line([(cx, ny + 14), hip], fill=stick, width=lw)
        d.line([shL, shR], fill=stick, width=lw)
        for p in (shL, shR, hip):
            d.ellipse((p[0] - lw / 2, p[1] - lw / 2, p[0] + lw / 2, p[1] + lw / 2), fill=stick)
        d.line([(cx, ny + 14), (cx, head[1] + 70)], fill=stick, width=lw)
        d.ellipse((head[0] - 78, head[1] - 78, head[0] + 78, head[1] + 78), fill=stick)
        blink = (t % 4.0) < 0.12
        for sgn in (-1, 1):
            ex, ey = head[0] + sgn * 28, head[1] - 8
            if blink:
                d.line((ex - 9, ey, ex + 9, ey), fill=dark, width=5)
            else:
                d.ellipse((ex - 9, ey - 9, ex + 9, ey + 9), fill=dark)
        if air > 0.3:
            d.ellipse((head[0] - 16, head[1] + 18, head[0] + 16, head[1] + 48), fill=dark)
        else:
            d.arc((head[0] - 30, head[1] - 2, head[0] + 30, head[1] + 44), 20, 160, fill=dark, width=6)

        # --- пианино: крышка, клавиши ---
        d.rectangle((0, FALL_TOP, W, KY), fill=(16, 16, 24))
        d.rectangle((0, FALL_TOP, W, FALL_TOP + 6), fill=mix((16, 16, 24), accent, 0.5))
        d.text((W / 2, FALL_TOP + 52), "S T I C K M A N   P I A N O", font=f_sub, fill=mix((16, 16, 24), accent, 0.55), anchor="mm")

        active = set()
        for e in events:
            if e["t"] > t:
                break
            if t < e["t"] + max(e["dur"] * 0.9, 0.14):
                active.add(e["m"])
        for m in WHITES:
            x0 = WIDX[m] * KW
            col = mix((250, 250, 252), accent, 0.55) if m in active else (250, 250, 252)
            d.rounded_rectangle((x0 + 1.5, KY, x0 + KW - 1.5, KY + KEY_H), radius=10, fill=col,
                                corners=(False, False, True, True))
        bw = KW * 0.62
        for m in range(LOW, HIGH + 1):
            if m % 12 in WHITE_PCS:
                continue
            x = key_x(m)
            col = mix((25, 25, 35), accent, 0.75) if m in active else (25, 25, 35)
            d.rounded_rectangle((x - bw / 2, KY, x + bw / 2, KY + BLACK_H), radius=7, fill=col,
                                corners=(False, False, True, True))
        d.rectangle((0, KY + KEY_H, W, H), fill=(14, 14, 22))

        # --- руки (перед пианино) ---
        for side, sh, h in ((-1, shL, "L"), (1, shR, "R")):
            key_t = (hands[h]["x"], KY + 18 - 45 * (1 - hands[h]["p"]))
            up_t = (sh[0] + side * 130, sh[1] - 330)
            tgt = (key_t[0] + (up_t[0] - key_t[0]) * up, key_t[1] + (up_t[1] - key_t[1]) * up)
            elbow, hand = ik(sh, tgt, side)
            d.line([sh, elbow, hand], fill=stick, width=lw, joint="curve")
            d.ellipse((elbow[0] - 10, elbow[1] - 10, elbow[0] + 10, elbow[1] + 10), fill=stick)
            d.ellipse((hand[0] - 17, hand[1] - 17, hand[0] + 17, hand[1] + 17), fill=stick)

        # --- частицы-ноты ---
        alive = []
        for p in particles:
            age = t - p[4]
            if age >= p[5]:
                continue
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] *= 0.992
            xi, yi = int(min(max(p[0], 0), W - 1)), int(min(max(p[1], 0), H - 1))
            draw_note(d, p[0], p[1], p[6], mix(tuple(bg_arr[yi, xi]), accent, 1 - age / p[5]))
            alive.append(p)
        particles = alive

        # --- заголовок и прогресс ---
        d.text((W / 2 + 3, 183), title, font=f_title, fill=(0, 0, 0), anchor="mm")
        d.text((W / 2, 180), title, font=f_title, fill=(255, 255, 255), anchor="mm")
        d.text((W / 2, 262), f"EPISODE #{episode}", font=f_sub, fill=accent, anchor="mm")
        d.rounded_rectangle((90, 1790, W - 90, 1802), radius=6, fill=(40, 40, 56))
        d.rounded_rectangle((90, 1790, 90 + (W - 180) * t / total, 1802), radius=6, fill=accent)
        d.text((W / 2, 1850), "follow for more", font=f_sub, fill=(150, 150, 175), anchor="mm")

        proc.stdin.write(img.tobytes())

    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg завершился с ошибкой")


# --------------------------------------------------------------------------
TITLES = ["Stickman plays piano", "Piano stickman jam", "Jumping stickman pianist",
          "This stickman can really play", "Stickman piano vibes"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--bpm", type=int, default=0)
    ap.add_argument("--episode", type=int, default=1)
    ap.add_argument("--out", default="out/video.mp4")
    a = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    rng = random.Random(a.seed)
    bpm = a.bpm or rng.randrange(96, 125, 4)
    step = 60.0 / bpm / 2
    bars = max(4, round((a.duration - 1.5) / (8 * step) / 4) * 4)
    events, step, mode = compose(rng, bpm, bars)
    total = bars * 8 * step + 1.5

    wav = os.path.splitext(a.out)[0] + ".wav"
    print(f"seed={a.seed} bpm={bpm} mode={mode} bars={bars} notes={len(events)} length={total:.1f}s", flush=True)
    write_wav(wav, synth(events, total, a.seed))
    title = "PIANO STICKMAN"
    render(events, wav, a.out, total, bpm, a.seed, a.episode, title)
    os.remove(wav)

    hook = TITLES[a.seed % len(TITLES)]
    meta = {
        "title": f"{hook} #{a.episode}",
        "description": "A stickman plays a piano melody and jumps to the beat. "
                       "Every video is generated by code: music, animation, everything.",
        "tags": ["piano", "stickman", "shorts", "animation", "music", "satisfying", "relaxing"],
        "hashtags": "#piano #stickman #shorts #animation #music #satisfying",
        "seed": a.seed, "bpm": bpm, "mode": mode, "duration": round(total, 1),
    }
    with open(os.path.splitext(a.out)[0] + ".json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    print("готово:", a.out, flush=True)


if __name__ == "__main__":
    main()
