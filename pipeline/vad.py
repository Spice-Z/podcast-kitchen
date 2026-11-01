"""Step 3a: the only VAD (Silero, pinned version/thresholds) on each leveled track.
Writes work/vad.json: per-speaker speech islands and their union (the basis of every silence rule)."""
import argparse
from pathlib import Path
import numpy as np
from scipy.signal import resample_poly
from common import dump, load_cfg, log_step, pin_threads, read_wav, speakers, r


def union(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); a = ap.parse_args()
    ep = Path(a.ep); cfg = load_cfg(ep); pin_threads(cfg["env"]["threads"]); c = cfg["vad"]
    import torch
    from silero_vad import load_silero_vad, get_speech_timestamps
    model = load_silero_vad()
    res = {"speakers": {}, "duration_s": None}
    for s in speakers(ep):
        x, sr = read_wav(ep / "work/level" / f"{s}.wav")
        y = resample_poly(x, c["sample_rate"], sr).astype(np.float32)
        res["duration_s"] = r(len(x) / sr, 6)
        ts = get_speech_timestamps(torch.from_numpy(y), model, sampling_rate=c["sample_rate"], threshold=c["threshold"],
                                   min_speech_duration_ms=c["min_speech_ms"], min_silence_duration_ms=c["min_silence_ms"],
                                   speech_pad_ms=c["speech_pad_ms"])
        res["speakers"][s] = [[r(t["start"] / c["sample_rate"]), r(t["end"] / c["sample_rate"])] for t in ts]
    res["union"] = union([iv for v in res["speakers"].values() for iv in v])
    dump(ep / "work/vad.json", res)
    log_step(ep, "vad", {k: len(v) for k, v in res["speakers"].items()})
    print("vad", {k: len(v) for k, v in res["speakers"].items()})


if __name__ == "__main__":
    main()
