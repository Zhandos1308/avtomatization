"""Импорт MIDI для режима hop. Используйте только файлы, на которые у вас есть права
(свои, лицензированные, royalty-free, public domain). Положите их в папку songs/.

Каналы: канал 10 (индекс 9) = ударные (кик/снейр/хэт), остальное = ноты.
Если в файле несколько каналов, канал с более высокими нотами = правая рука, иначе
руки делятся по медиане высоты.

Короткий файл автоматически разворачивается в длинный трек: проход 1 как есть,
дальше тональность поднимается (0, 0, +2, +2, +4, +4 полутонов), чтобы был «подъём»."""
import math

import mido

from generate import clampm

GM_DRUMS = {35: "kick", 36: "kick", 38: "snare", 39: "snare", 40: "snare",
            42: "hat", 44: "hat", 46: "hat", 49: "hat", 51: "hat", 59: "hat"}
SHIFTS = [0, 0, 2, 2, 4, 4, 5, 5]


def load_midi(path, start=0.0, duration=90.0, loop=True):
    """Возвращает (events, drums, step8, bpm, total, pass_len)."""
    mf = mido.MidiFile(path)
    t, first_tempo = 0.0, None
    on, notes, drums = {}, [], []
    for msg in mf:                                  # время в секундах, дорожки склеены
        t += msg.time
        if msg.type == "set_tempo" and first_tempo is None:
            first_tempo = msg.tempo
        if msg.type == "note_on" and msg.velocity > 0:
            if msg.channel == 9:
                kind = GM_DRUMS.get(msg.note)
                if kind:
                    drums.append({"t": t, "kind": kind, "vel": 0.4 + 0.6 * msg.velocity / 127})
            else:
                on[(msg.channel, msg.note)] = (t, msg.velocity)
        elif msg.type in ("note_off", "note_on") and msg.channel != 9:
            k = (msg.channel, msg.note)
            if k in on:
                t0, v = on.pop(k)
                notes.append((t0, t - t0, msg.note, v, msg.channel))
    file_len = t

    pass_len = file_len - start
    notes = [n for n in notes if n[0] >= start]
    if len(notes) < 8:
        raise ValueError(f"В MIDI слишком мало нот: {path}")
    pitches = sorted(n[2] for n in notes)
    split = pitches[len(pitches) // 2]
    by_ch = {}
    for n in notes:
        by_ch.setdefault(n[4], []).append(n[2])
    means = {c: sum(v) / len(v) for c, v in by_ch.items()}
    cut = sorted(means.values())[len(means) // 2] if len(means) >= 2 else None

    events, last = [], {"L": -9.0, "R": -9.0}
    for t0, d, m, v, ch in sorted(notes, key=lambda n: (n[0], -n[2])):
        if cut is not None:
            hand = "R" if means[ch] >= cut else "L"
        else:
            hand = "L" if m <= split else "R"
        if t0 - last[hand] < 0.11:
            continue
        last[hand] = t0
        events.append({"t": t0 - start, "dur": min(max(d, 0.12), 2.0), "m": m,
                       "hand": hand, "vel": 0.45 + 0.5 * v / 127, "bright": True})
    if not any(e["hand"] == "L" for e in events) or not any(e["hand"] == "R" for e in events):
        raise ValueError("Не получилось разделить ноты на две руки (нужны и низкие, и высокие)")
    dr = [dict(d, t=d["t"] - start) for d in drums if d["t"] >= start]

    passes = max(1, math.ceil(duration / pass_len - 0.05)) if loop else 1
    full, full_dr = [], []
    for p in range(passes):
        sh = SHIFTS[p % len(SHIFTS)]
        for e in events:
            full.append(dict(e, t=e["t"] + p * pass_len, m=clampm(e["m"] + sh)))
        for d in dr:
            full_dr.append(dict(d, t=d["t"] + p * pass_len))
    full.sort(key=lambda e: e["t"])
    bpm = 60e6 / (first_tempo or 500000)
    step8 = 60.0 / bpm / 2
    total = passes * pass_len + 1.5
    return full, full_dr, step8, bpm, total, pass_len
