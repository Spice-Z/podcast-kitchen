"""Step 3b (primary): Zencastr transcript -> per-track segments (work/asr.json, same schema as asr.py).
Input raw/transcript.csv: TSV with header Timestamp (mm:ss.cc or h:mm:ss.cc), Speaker, Transcript; one row per utterance
with its start time. Speakers map to tracks via manifest.json speaker_map (ingest --speaker "Name=track"; kept out of
the repo). Times are shifted by transcript.offset_s plus the sync offset of the mapped track when sync applied one.
Each utterance is bounded by the next utterance of the same speaker (and max_utt_s), start snapped to and end clipped
to the speaker's VAD islands; align_kana.py then aligns the text on that track. Speaker VAD islands with no utterance
are written to logs/transcript_coverage.json (input for the optional kotoba ASR fallback)."""
import argparse, csv, re
from pathlib import Path
from common import dump, load, load_cfg, log_step, speakers, r


def ts(s):
    p = [float(x) for x in s.strip().split(":")]
    return sum(v * 60 ** i for i, v in enumerate(reversed(p)))


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    if rows and not re.match(r"^\d", rows[0][0]):
        rows = rows[1:]
    return [(ts(a), b.strip(), c.strip()) for a, b, c, *_ in rows if c.strip()]


def segments(rows, islands, c, dur):
    """rows: [(t, text)] of ONE speaker, sorted. islands: that speaker's VAD islands."""
    out = []
    for k, (t, text) in enumerate(rows):
        nxt = rows[k + 1][0] if k + 1 < len(rows) else dur
        lim = min(nxt, t + c["max_utt_s"], dur)
        snap = [s for s, e in islands if abs(s - t) <= c["snap_s"]]
        st = min(snap, key=lambda s: abs(s - t)) if snap else t
        st = min(st, lim - 0.05)
        inside = [(s, e) for s, e in islands if s < lim - (c["snap_s"] if lim == nxt else 0) and e > st]  # next utt's onset excluded
        if inside:
            en = min(lim, inside[-1][1] + c["end_pad_s"])
        else:  # no detected speech: short window sized by text length
            en = min(lim, st + 0.5 + 0.12 * len(text))
        out.append({"start": r(st), "end": r(max(en, st + 0.1)), "text": text, "source": "zencastr", "ts": r(t),
                    "vad_speech": bool(inside), "flags": [] if inside else ["no_vad_speech"]})
    return out


def coverage(segs, islands, min_s):
    gaps = []
    for s, e in islands:
        if e - s >= min_s and not any(g["start"] < e and g["end"] > s for g in segs):
            gaps.append([r(s), r(e)])
    return gaps


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); a = ap.parse_args()
    ep = Path(a.ep); cfg = load_cfg(ep); c = cfg["transcript"]
    man = load(ep / "manifest.json"); smap = man.get("speaker_map") or {}
    if not smap:
        raise SystemExit("manifest has no speaker_map; ingest with --speaker 'Transcript Name=track'")
    rows = read_rows(ep / "raw/transcript.csv")
    unknown = sorted({n for _, n, _ in rows} - set(smap))
    if unknown:
        raise SystemExit(f"transcript speakers without a track: {len(unknown)}; add --speaker mappings")
    sync = load(ep / "logs/sync.json")["tracks"]; vad = load(ep / "work/vad.json"); dur = vad["duration_s"]
    res, gaps = {}, {}
    for s in speakers(ep):
        st = sync.get(s, {}); off = c["offset_s"] + (st.get("applied_offset_s", 0.0) or 0.0)
        mine = sorted((t + off, x) for t, n, x in rows if smap[n] == s)
        res[s] = segments(mine, vad["speakers"][s], c, dur)
        gaps[s] = coverage(res[s], vad["speakers"][s], c["uncovered_min_s"])
    dump(ep / "work/asr.json", res)
    dump(ep / "logs/transcript_coverage.json", gaps)
    st = {s: {"utterances": len(v), "no_vad_speech": sum(1 for g in v if g["flags"]), "uncovered_islands": len(gaps[s])} for s, v in res.items()}
    log_step(ep, "zencastr_transcript", st)
    print("transcript", st)


if __name__ == "__main__":
    main()
