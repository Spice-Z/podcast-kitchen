"""Step 2a: measure offset/drift of each track against the longest track and correct if confident.

Method: 10 ms log-energy envelopes (bleed of the other voices is what correlates), onset-emphasised
(first difference), normalised cross-correlation within +/- max_lag at the start and end windows.
Correction only when both peaks clear min_peak_confidence. Drift is reported in ppm.
"""
import argparse, shutil
from pathlib import Path
import numpy as np
from scipy.signal import resample_poly, correlate
from common import dump, load_cfg, log_step, read_wav, speakers, write_wav, r


def envelope(x, sr, rate):
    hop = sr // rate
    n = len(x) // hop
    e = np.log10(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-10)
    d = np.diff(e, prepend=e[0])
    return d


def ncc(ref, sig, max_lag):
    a = (ref - ref.mean()) / (ref.std() + 1e-12)
    b = (sig - sig.mean()) / (sig.std() + 1e-12)
    c = correlate(a, b, mode="full", method="fft") / len(a)
    mid = len(b) - 1
    c = c[mid - max_lag: mid + max_lag + 1]
    k = int(np.argmax(c))
    return k - max_lag, float(c[k])


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); a = ap.parse_args()
    ep = Path(a.ep); cfg = load_cfg(ep); sc = cfg["sync"]
    spk = speakers(ep)
    wav = {s: read_wav(ep / "work/ingest" / f"{s}.wav") for s in spk}
    sr = wav[spk[0]][1]
    ref = max(spk, key=lambda s: (len(wav[s][0]), -spk.index(s)))
    rate = sc["env_rate_hz"]; W = int(sc["window_s"] * rate); L = int(sc["max_lag_s"] * rate)
    env = {s: envelope(wav[s][0], sr, rate) for s in spk}
    out = {"reference": ref, "tracks": {}}
    (ep / "work/sync").mkdir(parents=True, exist_ok=True)
    for s in spk:
        x = wav[s][0]
        dst = ep / "work/sync" / f"{s}.wav"
        if s == ref:
            shutil.copyfile(ep / "work/ingest" / f"{s}.wav", dst)
            out["tracks"][s] = {"reference": True}
            continue
        e, er = env[s], env[ref]
        n = min(len(e), len(er))
        lag0, c0 = ncc(er[:W], e[:W], L)
        lag1, c1 = ncc(er[n - W:n], e[n - W:n], L)
        off0, off1 = lag0 / rate, lag1 / rate          # + = track is late vs reference
        span = (n - W) / rate
        drift_ppm = (off1 - off0) / span * 1e6 if span > 0 else 0.0
        conf = min(c0, c1)
        info = {"offset_start_s": r(off0), "offset_end_s": r(off1), "conf_start": r(c0), "conf_end": r(c1),
                "drift_ppm": r(drift_ppm, 1), "action": "none", "applied_offset_s": 0.0}
        y = x
        if conf < sc["min_peak_confidence"]:
            info["action"] = "none (low confidence; tracks assumed aligned)"
        else:
            if abs(drift_ppm) > sc["max_drift_ppm"]:
                # stretch track so that end offset matches start offset
                num = int(round(len(y) * (1 - drift_ppm * 1e-6))); g = np.gcd(num, len(y))
                y = resample_poly(y, num // g, len(y) // g)
                info["action"] = f"resampled {r(-drift_ppm,1)} ppm"
            if abs(off0) * 1000 > sc["min_offset_ms"]:
                k = int(round(off0 * sr))
                y = y[k:] if k > 0 else np.concatenate([np.zeros(-k), y])
                info["action"] += f"; shifted {-k} samples"
                info["applied_offset_s"] = r(-k / sr)  # add to a source-relative time (e.g. transcript) of this track
        L_ref = len(wav[ref][0])
        y = y[:L_ref] if len(y) >= L_ref else np.concatenate([y, np.zeros(L_ref - len(y))])
        write_wav(dst, y, sr)
        out["tracks"][s] = info
    dump(ep / "logs/sync.json", out)
    log_step(ep, "sync", {"reference": ref})
    print("sync", out)


if __name__ == "__main__":
    main()
