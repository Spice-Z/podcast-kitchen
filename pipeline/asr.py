"""Step 3b (venv_dfn_asr): per-speaker ASR with kotoba-whisper-v2.0 (faster-whisper, float32, pinned revision).
Audio is fed per chunk built from Silero VAD islands (vad.json), so Whisper's own VAD is off.
temperature is a single value -> no fallback; segments that would have triggered one are flagged."""
import argparse, platform
from pathlib import Path
import numpy as np
from scipy.signal import resample_poly
from common import dump, load, load_cfg, log_step, pin_threads, read_wav, speakers, r


def chunks(islands, gap, max_len):
    out = []
    for s, e in islands:
        if out and s - out[-1][1] <= gap and e - out[-1][0] <= max_len:
            out[-1][1] = e
        else:
            out.append([s, e])
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); a = ap.parse_args()
    ep = Path(a.ep); cfg = load_cfg(ep); c = cfg["asr"]; th = cfg["env"]["threads"]; pin_threads(th)
    import faster_whisper, ctranslate2
    from faster_whisper import WhisperModel, download_model
    m = cfg["models"]["asr"]
    path = download_model(m["repo"], revision=m["revision"], local_files_only=True)
    model = WhisperModel(path, device=c["device"], compute_type=c["compute_type"], cpu_threads=th, num_workers=1)
    vad = load(ep / "work/vad.json")
    res, flags = {}, []
    for s in speakers(ep):
        x, sr = read_wav(ep / "work/level" / f"{s}.wav")
        y = resample_poly(x, 16000, sr).astype(np.float32)
        segs = []
        for cs, ce in chunks(vad["speakers"][s], c["merge_gap_s"], c["max_chunk_s"]):
            a0, a1 = int(cs * 16000), int(ce * 16000)
            out, _ = model.transcribe(y[a0:a1], language=c["language"], beam_size=c["beam_size"], temperature=c["temperature"],
                                      condition_on_previous_text=c["condition_on_previous_text"], word_timestamps=False,
                                      vad_filter=False, without_timestamps=False)
            for g in out:
                t = g.text.strip()
                if not t:
                    continue
                f = []
                if g.avg_logprob < c["log_prob_threshold"]: f.append("low_logprob")
                if g.compression_ratio > c["compression_ratio_threshold"]: f.append("high_compression")
                seg = {"start": r(cs + g.start), "end": r(min(ce, cs + g.end)), "text": t, "chunk": [r(cs), r(ce)],
                       "avg_logprob": r(g.avg_logprob), "no_speech_prob": r(g.no_speech_prob), "flags": f}
                segs.append(seg)
                if f: flags.append({"speaker": s, **seg})
        res[s] = segs
    dump(ep / "work/asr.json", res)
    dump(ep / "logs/asr_fallbacks.json", flags)
    dump(ep / "logs/env_asr.json", {"model": m, "faster_whisper": faster_whisper.__version__, "ctranslate2": ctranslate2.__version__,
                                     "python": platform.python_version(), "threads": th, "params": c})
    log_step(ep, "asr", {k: len(v) for k, v in res.items()})
    print("asr", {k: len(v) for k, v in res.items()}, "flagged", len(flags))


if __name__ == "__main__":
    main()
