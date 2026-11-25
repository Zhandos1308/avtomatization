#!/usr/bin/env python3
"""Создаёт MIDI-файлы мелодий из public domain (композиторы умерли более 70 лет назад
или это народные песни) в папке songs/. Это собственные аранжировки (мелодия + простой бас).

Запуск:  python tools/make_public_domain_midis.py
Формат нот: "E4:.5" = нота E4 длиной 0.5 доли; "R:1" = пауза; без суффикса = 1 доля.
Мелодия идёт на канал 0 (правая рука), бас на канал 1 (левая рука)."""
import os
import re

import mido

NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def parse(s, ch):
    t, out = 0.0, []
    for tok in s.replace("|", " ").split():
        name, _, dur = tok.partition(":")
        d = float(dur) if dur else 1.0
        if name != "R":
            m = re.fullmatch(r"([A-G])([#b]?)(-?\d)", name)
            pc = NAMES[m.group(1)] + (1 if m.group(2) == "#" else -1 if m.group(2) == "b" else 0)
            out.append((t, d, 12 * (int(m.group(3)) + 1) + pc, ch))
        t += d
    return out, t


def save(path, bpm, mel, bass, repeat=1):
    mid = mido.MidiFile(ticks_per_beat=480)
    tracks = []
    for ch, s in ((0, mel), (1, bass)):
        notes, total = parse(s, ch)
        tracks.append((notes, total))
    length = max(t for _, t in tracks)
    for i, (notes, total) in enumerate(tracks):
        tr = mido.MidiTrack()
        mid.tracks.append(tr)
        if i == 0:
            tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm)))
        ev = []
        for r in range(repeat):
            for t, d, m, ch in notes:
                ev.append(((t + r * length) * 480, "on", m, ch))
                ev.append(((t + r * length + d * 0.95) * 480, "off", m, ch))
        ev.sort(key=lambda e: (e[0], e[1] == "on"))
        last = 0
        for tk, kind, m, ch in ev:
            tk = int(round(tk))
            tr.append(mido.Message("note_on" if kind == "on" else "note_off", note=m, channel=ch,
                                   velocity=90 if kind == "on" else 0, time=tk - last))
            last = tk
        tr.append(mido.MetaMessage("end_of_track", time=max(0, int(round(length * repeat * 480)) - last)))
    mid.save(path)


# ----------------------------------------------------------------------------- Ode to Joy (Beethoven)
ODE_A = ("E4 E4 F4 G4 | G4 F4 E4 D4 | C4 C4 D4 E4 | E4:1.5 D4:.5 D4:2 | "
         "E4 E4 F4 G4 | G4 F4 E4 D4 | C4 C4 D4 E4 | D4:1.5 C4:.5 C4:2")
ODE_B = "D4 D4 E4 C4 | D4 E4:.5 F4:.5 E4 C4 | D4 E4:.5 F4:.5 E4 D4 | C4 D4 G3:2"
ODE_BASS_A = "C3:4 G2:4 C3:4 G2:4 C3:4 G2:4 C3:4 G2:4"
ODE_BASS_B = "G2:4 C3:4 G2:4 G2:4"

# ----------------------------------------------------------------------------- Für Elise (Beethoven)
ELISE_M = ("E5:.25 D#5:.25 | E5:.25 D#5:.25 E5:.25 B4:.25 D5:.25 C5:.25 | A4:.5 R:.25 C4:.25 E4:.25 A4:.25 | "
           "B4:.5 R:.25 E4:.25 G#4:.25 B4:.25 | C5:.5 R:.25 E4:.25 E5:.25 D#5:.25 | "
           "E5:.25 D#5:.25 E5:.25 B4:.25 D5:.25 C5:.25 | A4:.5 R:.25 C4:.25 E4:.25 A4:.25 | "
           "B4:.5 R:.25 E4:.25 C5:.25 B4:.25 | A4:.75 R:.75")
ELISE_B = ("R:.5 | R:1.5 | R:.5 A2:.25 E3:.25 A3:.25 R:.25 | R:.5 E2:.25 E3:.25 G#3:.25 R:.25 | "
           "R:.5 A2:.25 E3:.25 A3:.25 R:.25 | R:1.5 | R:.5 A2:.25 E3:.25 A3:.25 R:.25 | "
           "R:.5 E2:.25 E3:.25 G#3:.25 R:.25 | A2:.75 R:.75")

# ----------------------------------------------------------------------------- Turkish March (Mozart), вступление
TURK_M = ("B4:.25 A4:.25 G#4:.25 A4:.25 C5:1 | D5:.25 C5:.25 B4:.25 C5:.25 E5:1 | "
          "F5:.25 E5:.25 D#5:.25 E5:.25 B5:.25 A5:.25 G#5:.25 A5:.25 | "
          "B5:.25 A5:.25 G#5:.25 A5:.25 C6:1 | A5:.5 C6:.5 B5:.5 A5:.5 | G#5:.5 B5:.5 A5:2")
TURK_B = ("A2:.5 E3:.5 A2:.5 E3:.5 | A2:.5 E3:.5 A2:.5 E3:.5 | E2:.5 B2:.5 E2:.5 B2:.5 | "
          "A2:.5 E3:.5 A2:.5 E3:.5 | A2:.5 E3:.5 A2:.5 E3:.5 | E2:.5 B2:.5 A2:2")

# ----------------------------------------------------------------------------- Canon in D (Pachelbel)
CANON_BASS = "D3:2 A2:2 B2:2 F#2:2 G2:2 D2:2 G2:2 A2:2"
CANON_M1 = "F#5:2 E5:2 D5:2 C#5:2 B4:2 A4:2 B4:2 C#5:2"
CANON_M2 = "F#5 A5 E5 G5 D5 F#5 C#5 E5 B4 D5 A4 C#5 B4 D5 C#5 E5"

# ----------------------------------------------------------------------------- Jingle Bells (Pierpont, 1857)
JB_M = ("E4 E4 E4:2 | E4 E4 E4:2 | E4 G4 C4:1.5 D4:.5 | E4:4 | F4 F4 F4:1.5 F4:.5 | F4 E4 E4 E4:.5 E4:.5 | "
        "E4 D4 D4 E4 | D4:2 G4:2 | "
        "E4 E4 E4:2 | E4 E4 E4:2 | E4 G4 C4:1.5 D4:.5 | E4:4 | F4 F4 F4:1.5 F4:.5 | F4 E4 E4 E4:.5 E4:.5 | "
        "G4 G4 F4 D4 | C4:4")
JB_B = ("C3:4 C3:4 C3:4 C3:4 F3:4 F3:4 C3:4 G2:4 | C3:4 C3:4 C3:4 C3:4 F3:4 F3:4 G2:4 C3:4")

# ----------------------------------------------------------------------------- Greensleeves (народная, XVI в.)
GS_M = ("A4:1 | C5:2 D5:1 | E5:1.5 F5:.5 E5:1 | D5:2 B4:1 | G4:1.5 A4:.5 B4:1 | C5:2 A4:1 | "
        "A4:1.5 G#4:.5 A4:1 | B4:2 G#4:1 | E4:3")
GS_B = "R:1 | A2:3 | C3:3 | G2:3 | G2:3 | A2:3 | E2:3 | E2:3 | A2:3"


def main():
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "songs")
    os.makedirs(out, exist_ok=True)
    save(f"{out}/ode_to_joy.mid", 120, f"{ODE_A} {ODE_B} {ODE_A}", f"{ODE_BASS_A} {ODE_BASS_B} {ODE_BASS_A}")
    save(f"{out}/fur_elise.mid", 100, ELISE_M, ELISE_B, repeat=3)
    save(f"{out}/turkish_march.mid", 132, TURK_M, TURK_B, repeat=4)
    save(f"{out}/canon_in_d.mid", 80, f"{CANON_M1} {CANON_M2} {CANON_M1}", f"{CANON_BASS} {CANON_BASS} {CANON_BASS}")
    save(f"{out}/jingle_bells.mid", 150, JB_M, JB_B)
    save(f"{out}/greensleeves.mid", 110, GS_M, GS_B, repeat=2)
    print("готово:", sorted(os.listdir(out)))


if __name__ == "__main__":
    main()
