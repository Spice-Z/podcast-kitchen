"""Step 2d: leveler. Position: after clean_dynamics, before VAD/ASR/edits (all later steps see leveled tracks).
1) slow RMS leveler: window_s RMS every hop_s, gain toward the track's gated median, clamped to
   +/-max_gain_db, frames under gate_dbfs hold the previous gain, smoothed over smoothing_s;
2) static gain to level.target_lufs (pyloudnorm integrated, measurement only)."""
import argparse
from pathlib import Path
import numpy as np
from common import dump, load_cfg, log_step, read_wav, speakers, write_wav, r


def leveler_gain(x, sr, c):
    hop = int(c["hop_s"] * sr); win = int(c["window_s"] * sr)
    n = max(1, len(x) // hop)
    cs = np.concatenate([[0], np.cumsum(x ** 2)])
    centers = np.arange(n) * hop + hop // 2
    lo = np.clip(centers - win // 2, 0, len(x)); hi = np.clip(centers + win // 2, 0, len(x))
    rms_db = 10 * np.log10((cs[hi] - cs[lo]) / np.maximum(hi - lo, 1) + 1e-12)
    voiced = rms_db > c["gate_dbfs"]
    ref = float(np.median(rms_db[voiced])) if voiced.any() else 0.0
    g = np.zeros(n); prev = 0.0
    for i in range(n):
        if voiced[i]:
            prev = float(np.clip(ref - rms_db[i], -c["max_gain_db"], c["max_gain_db"]))
        g[i] = prev
    k = max(1, int(c["smoothing_s"] / c["hop_s"]))
    g = np.convolve(np.pad(g, (k, k), mode="edge"), np.ones(k) / k, mode="same")[k:-k]
    gs = np.interp(np.arange(len(x)), centers, g)
    return gs, ref


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); a = ap.parse_args()
    ep = Path(a.ep); cfg = load_cfg(ep); c = cfg["level"]
    import pyloudnorm as pyln
    log = {}
    for s in speakers(ep):
        x, sr = read_wav(ep / "work/clean" / f"{s}.wav")
        meter = pyln.Meter(sr)
        l0 = meter.integrated_loudness(x)
        gdb, ref = leveler_gain(x, sr, c)
        y = x * 10 ** (gdb / 20)
        y = y * 10 ** ((c["target_lufs"] - meter.integrated_loudness(y)) / 20)
        write_wav(ep / "work/level" / f"{s}.wav", y, sr)
        log[s] = {"input_lufs": r(l0, 2), "leveler_ref_dbfs": r(ref, 2),
                  "leveler_gain_db_min": r(gdb.min(), 2), "leveler_gain_db_max": r(gdb.max(), 2),
                  "output_lufs": r(meter.integrated_loudness(y), 2)}
    dump(ep / "logs/level.json", log)
    log_step(ep, "level", {})
    print("level", log)


if __name__ == "__main__":
    main()
