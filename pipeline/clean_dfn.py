"""Step 2b (venv_dfn_asr): DeepFilterNet3 denoise, attenuation capped by clean.dfn_atten_lim_db.
Processed in fixed 30 s chunks with 1 s linear crossfades (bounded memory, deterministic)."""
import argparse, hashlib
from pathlib import Path
import numpy as np
from common import dump, load_cfg, log_step, pin_threads, read_wav, speakers, write_wav

CH, OV = 30.0, 1.0


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); a = ap.parse_args()
    ep = Path(a.ep); cfg = load_cfg(ep); pin_threads(cfg["env"]["threads"])
    import torch
    from df.enhance import init_df, enhance
    model, st, _ = init_df(model_base_dir=cfg["models"]["dfn"]["name"], log_level="ERROR")
    sr_df = st.sr()
    mdir = Path.home() / ".cache/DeepFilterNet" / cfg["models"]["dfn"]["name"] / "checkpoints"
    mhash = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:16] for p in sorted(mdir.glob("*"))}
    for s in speakers(ep):
        x, sr = read_wav(ep / "work/sync" / f"{s}.wav")
        assert sr == sr_df, (sr, sr_df)
        n, c, o = len(x), int(CH * sr), int(OV * sr)
        y = np.zeros(n); w = np.zeros(n)
        start = 0
        while start < n:
            end = min(n, start + c + o)
            seg = torch.from_numpy(x[start:end].astype(np.float32))[None]
            e = enhance(model, st, seg, atten_lim_db=cfg["clean"]["dfn_atten_lim_db"])[0].numpy().astype(np.float64)
            win = np.ones(end - start)
            if start > 0: win[:o] = np.linspace(0, 1, o)
            if end < n: win[-o:] = np.linspace(1, 0, o)
            y[start:end] += e * win; w[start:end] += win
            start += c
        write_wav(ep / "work/dfn" / f"{s}.wav", y / np.maximum(w, 1e-9), sr)
    dump(ep / "logs/env_dfn.json", {"model": cfg["models"]["dfn"], "checkpoints_sha256": mhash, "torch": torch.__version__})
    log_step(ep, "clean_dfn", {})
    print("dfn ok")


if __name__ == "__main__":
    main()
