"""Step 5a: ending BGM (render stage, after mix, before loudness).
Finds the last closing phrase (ending_bgm.phrases, e.g. 「ということで」) in the edited transcript within
ending_bgm.search_window_s of the end, fades the BGM in lead_in_s before it (over fade_in_s), keeps it as a bed
bed_db below the voices' active level, and after the last speech end on the edited timeline (all speakers) ramps it
to tail_db (relative to the same voice level) over ramp_s, plays BGM alone for tail_s, then fades out over
fade_out_s linearly in dB (exponential in amplitude) down to fade_out_floor_db (re voice), cuts to 0 and appends
end_silence_s of digital silence. The episode is extended as needed. Rewrites work/mix.wav (the voice-only mix is kept as
work/mix_voice.wav so re-running never stacks BGM). Skips with a warning when disabled, the file is missing or no
phrase is found. Log: logs/ending_bgm.json; timemap.json gets "ending_bgm" and the new edited_duration_s."""
import argparse, os, subprocess, sys
from pathlib import Path
import numpy as np
from common import dump, load, load_cfg, log_step, r, read_wav, speakers

DEF = {"enabled": True, "file": "../../assets/ending_bgm.mp3", "phrases": ["ということで"], "search_window_s": 120.0,
       "lead_in_s": 3.0, "fade_in_s": 2.0, "bed_db": -20.0, "ramp_s": 1.5, "tail_db": -4.0, "tail_s": 5.0,
       "fade_out_s": 7.0, "fade_out_floor_db": -60.0, "end_silence_s": 1.5, "bgm_offset_s": 0.0, "voice_ref_window_s": 60.0, "min_island_s": 0.2}


def map_time(tm, t):
    for a, b, o in tm["spans"]:
        if t < a:
            return o
        if t <= b:
            return o + (t - a)
    a, b, o = tm["spans"][-1]
    return o + (b - a)


def find_phrase(segs, phrases, dur, window):
    """segs: [(edited_start, text, [(edited_tok_start or None, surface), ...])]. -> (time, phrase, text) of the last
    occurrence starting within `window` s of the end, else None. The start is the token where the phrase begins
    (last known token start at or before it; the segment start if tokens carry no timing)."""
    best = None
    for st, text, toks in segs:
        for ph in phrases:
            i = text.rfind(ph)
            if i < 0:
                continue
            t, n = st, 0
            for ts, sf in toks:
                if ts is not None and n <= i:
                    t = ts
                n += len(sf)
                if n > i:
                    break
            if t >= dur - window and (best is None or t > best[0]):
                best = (t, ph, text)
    return best


def last_speech_end(intervals, dur, min_len=0.2):
    ends = [b for a, b in intervals if b - a >= min_len and a < dur]
    return min(dur, max(ends)) if ends else None


def active_rms_db(x, sr):
    fr = int(0.05 * sr); m = len(x) // fr
    if m == 0:
        return -120.0
    e = np.mean(x[: m * fr].reshape(m, fr) ** 2, axis=1); db = 10 * np.log10(e + 1e-20)
    act = e[db > np.max(db) - 30]
    return float(10 * np.log10(np.mean(act) + 1e-20))


def envelope(n, sr, t_in, t_end, p):
    """-> (amplitude gain per sample relative to the voice-matched BGM, total length). Silence before t_in, linear
    fade-in to bed_db, bed until t_end, ramp to tail_db over ramp_s, hold until t_end + tail_s, fade-out linear in dB
    from tail_db to fade_out_floor_db over fade_out_s, then 0 (incl. end_silence_s of digital silence)."""
    t_ph_end = t_end + p["tail_s"]; t_stop = t_ph_end + p["fade_out_s"]
    n_total = max(n, int(np.ceil((t_stop + p["end_silence_s"]) * sr)))
    t = np.arange(n_total) / sr
    bed, tail = p["bed_db"], p["tail_db"]
    lin = lambda a, b, ga, gb: ga + (gb - ga) * np.clip((t - a) / max(b - a, 1e-9), 0, 1)
    fi = (t >= t_in) & (t < t_in + p["fade_in_s"])     # fade in from silence (in amplitude)
    g_amp = np.zeros(n_total)
    g_amp[fi] = 10 ** (bed / 20) * (t[fi] - t_in) / p["fade_in_s"]
    on = (t >= t_in + p["fade_in_s"]) & (t < t_end)
    g_amp[on] = 10 ** (bed / 20)
    up = (t >= t_end) & (t < t_ph_end)
    g_amp[up] = 10 ** (lin(t_end, t_end + p["ramp_s"], bed, tail)[up] / 20)
    fo = (t >= t_ph_end) & (t < t_stop)
    g_amp[fo] = 10 ** ((tail + (p["fade_out_floor_db"] - tail) * (t[fo] - t_ph_end) / p["fade_out_s"]) / 20)
    return g_amp, n_total


def mix_bgm(voice, bgm, sr, t_phrase, t_end, p, voice_db):
    """voice: mono mix; bgm: mono BGM; levels: bed/tail are dB relative to voice_db (active voice RMS)."""
    t_in = max(0.0, t_phrase - p["lead_in_s"])
    t_end = max(t_end, t_in + p["fade_in_s"])
    g, n_total = envelope(len(voice), sr, t_in, t_end, p)
    b = bgm[int(p["bgm_offset_s"] * sr):]
    norm = 10 ** ((voice_db - active_rms_db(b[: int(30 * sr)], sr)) / 20)  # BGM active level -> voice level
    i0 = int(t_in * sr); seg = np.zeros(n_total); k = min(len(b), n_total - i0)
    seg[i0:i0 + k] = b[:k] * norm
    out = np.zeros(n_total); out[:len(voice)] = voice
    out += seg * g
    return out, {"fade_in_start_s": r(t_in), "last_speech_end_s": r(t_end), "tail_end_s": r(t_end + p["tail_s"]),
                 "fade_out_end_s": r(t_end + p["tail_s"] + p["fade_out_s"]), "end_s": r(n_total / sr), "extended_s": r((n_total - len(voice)) / sr), "bgm_short": bool(k < n_total - i0)}


def decode(path, sr):
    p = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f64le", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.float64).copy()


def main():
    import soundfile as sf
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); a = ap.parse_args()
    ep = Path(a.ep); cfg = load_cfg(ep); p = {**DEF, **(cfg.get("ending_bgm") or {})}
    mix_p, voice_p, mark = ep / "work/mix.wav", ep / "work/mix_voice.wav", ep / "work/.ending_bgm"
    # mix.wav written by this step before (mark = its mtime) -> the voice mix is mix_voice.wav; else render just wrote it
    ours = mark.exists() and mix_p.exists() and mark.read_text().strip() == str(mix_p.stat().st_mtime_ns)
    if not ours:
        if not mix_p.exists():
            raise SystemExit("ending_bgm: work/mix.wav missing; run render first")
        os.replace(mix_p, voice_p)
    info_v = sf.info(str(voice_p)); sr, n, ch = info_v.samplerate, info_v.frames, info_v.channels; dur = n / sr

    def write(tail=None, t0=0):
        """copy the voice mix head blockwise, then the processed mono tail from sample t0 (or the rest unchanged)."""
        blk = sr * 60
        with sf.SoundFile(str(voice_p)) as src, sf.SoundFile(str(mix_p), "w", sr, ch, subtype="FLOAT") as dst:
            stop = t0 if tail is not None else n
            for s0 in range(0, stop, blk):
                dst.write(src.read(min(blk, stop - s0), dtype="float64", always_2d=True))
            if tail is not None:
                dst.write(np.repeat(tail[:, None], ch, 1))
        mark.write_text(str(mix_p.stat().st_mtime_ns))

    def skip(msg):
        print(f"WARNING ending_bgm: {msg}; skipped", file=sys.stderr)
        write(); dump(ep / "logs/ending_bgm.json", {"applied": False, "reason": msg}); log_step(ep, "ending_bgm", {"applied": False, "reason": msg})

    if not p["enabled"]:
        return skip("disabled")
    f = Path(p["file"]); f = f if f.is_absolute() else (ep / f).resolve()
    if not f.exists():
        return skip(f"BGM file not found: {p['file']}")
    tm = load(ep / "work/timemap.json"); words = load(ep / "work/words.json"); vad = load(ep / "work/vad.json")
    segs = []
    for s in speakers(ep):
        for w in words.get(s, []):
            if w.get("status") == "rejected":
                continue
            toks = [(map_time(tm, t["start"]) if t.get("start") is not None else None, t.get("surface", "")) for t in w.get("words", [])]
            segs.append((map_time(tm, w["start"]), w.get("text", ""), toks))
    hit = find_phrase(segs, p["phrases"], dur, p["search_window_s"])
    if hit is None:
        return skip(f"no closing phrase {p['phrases']} in the last {p['search_window_s']} s")
    iv = [(map_time(tm, a_), map_time(tm, b_)) for s in speakers(ep) for a_, b_ in vad["speakers"][s]]
    t_end = max(last_speech_end(iv, dur, p["min_island_s"]) or dur, hit[0])
    t0s = max(0.0, min(hit[0] - p["lead_in_s"], t_end - p["voice_ref_window_s"]) - 1.0); i0 = int(t0s * sr)
    with sf.SoundFile(str(voice_p)) as src:
        src.seek(i0); tail = src.read(dtype="float64", always_2d=True)[:, 0]
    ref = tail[max(0, int((t_end - p["voice_ref_window_s"] - t0s) * sr)):int((t_end - t0s) * sr)]
    vdb = active_rms_db(ref, sr)
    y, info = mix_bgm(tail, decode(f, sr), sr, hit[0] - t0s, t_end - t0s, p, vdb)
    for k in ("fade_in_start_s", "last_speech_end_s", "tail_end_s", "fade_out_end_s", "end_s"):
        info[k] = r(info[k] + t0s)
    write(y, i0)
    info.update({"applied": True, "phrase": hit[1], "phrase_s": r(hit[0]), "phrase_text": hit[2], "voice_active_db": r(vdb, 1),
                 "params": {k: p[k] for k in DEF if k != "file"}})
    dump(ep / "logs/ending_bgm.json", info)
    tm["ending_bgm"] = info; tm["edited_duration_s"] = r(info["end_s"], 6); dump(ep / "work/timemap.json", tm)
    if info["bgm_short"]:
        print("WARNING ending_bgm: BGM shorter than the needed span", file=sys.stderr)
    log_step(ep, "ending_bgm", {k: info[k] for k in ("phrase_s", "last_speech_end_s", "end_s", "extended_s")})
    print("ending_bgm", {k: v for k, v in info.items() if k != "params"})


if __name__ == "__main__":
    main()
