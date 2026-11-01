"""Step 2c: per-track EQ/dynamics with pedalboard: HPF -> split-band de-esser -> compressor -> limiter."""
import argparse
from pathlib import Path
import numpy as np
from common import load_cfg, log_step, pin_threads, read_wav, speakers, write_wav


def deess(x, sr, c):
    from pedalboard import Pedalboard, HighpassFilter
    band = Pedalboard([HighpassFilter(c["freq_hz"]), HighpassFilter(c["freq_hz"])])(x.astype(np.float32)[None], sr)[0].astype(np.float64)
    hop = int(0.005 * sr); n = len(band) // hop
    env = np.sqrt(np.mean(band[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(env)
    over = np.maximum(db - c["threshold_db"], 0)
    gdb = -over * (1 - 1 / c["ratio"])
    g = np.repeat(10 ** (gdb / 20), hop)
    g = np.concatenate([g, np.full(len(band) - len(g), g[-1] if len(g) else 1.0)])
    k = np.ones(hop * 2) / (hop * 2)
    g = np.convolve(g, k, mode="same")
    return x - band + band * g


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); a = ap.parse_args()
    ep = Path(a.ep); cfg = load_cfg(ep); pin_threads(cfg["env"]["threads"]); c = cfg["clean"]
    from pedalboard import Pedalboard, HighpassFilter, Compressor, Limiter
    for s in speakers(ep):
        x, sr = read_wav(ep / "work/dfn" / f"{s}.wav")
        x = Pedalboard([HighpassFilter(c["highpass_hz"])])(x.astype(np.float32)[None], sr)[0].astype(np.float64)
        x = deess(x, sr, c["deess"])
        cc, lc = c["compressor"], c["limiter"]
        y = Pedalboard([Compressor(threshold_db=cc["threshold_db"], ratio=cc["ratio"], attack_ms=cc["attack_ms"], release_ms=cc["release_ms"]),
                        Limiter(threshold_db=lc["threshold_db"], release_ms=lc["release_ms"])])(x.astype(np.float32)[None], sr)[0]
        write_wav(ep / "work/clean" / f"{s}.wav", y.astype(np.float64), sr)
    log_step(ep, "clean_dynamics", {})
    print("dynamics ok")


if __name__ == "__main__":
    main()
