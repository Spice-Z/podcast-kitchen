"""Step 3c: word timing. Text -> fugashi(unidic-lite) tokens (POS) -> pyopenjtalk kana reading ->
uroman romanisation -> torchaudio MMS_FA forced alignment per ASR segment.
Segments the aligner rejects or scores below align.min_segment_score get status 'rejected'/'low'
(they feed acoustic candidates and review). Writes work/words.json."""
import argparse
from pathlib import Path
import numpy as np
from scipy.signal import resample_poly
from common import dump, load, load_cfg, log_step, pin_threads, read_wav, speakers, r

_tagger = None


def tokenize(text):
    """[(surface, pos1, kana)]: words+POS from pinned fugashi/unidic-lite, readings from pinned
    pyopenjtalk run on the whole sentence (context-dependent kanji readings), mapped by char offsets."""
    global _tagger
    import re, fugashi, pyopenjtalk
    if _tagger is None:
        _tagger = fugashi.Tagger()
    njd, pos = [], 0
    for u in pyopenjtalk.run_frontend(text):
        st = u["string"]; i = text.find(st, pos)
        if i < 0:
            continue
        njd.append((i, i + len(st), re.sub(r"[^ァ-ヴー]", "", u["pron"]))); pos = i + len(st)
    out, pos, used = [], 0, set()
    for w in _tagger(text):
        i = text.find(w.surface, pos); pos = i + len(w.surface) if i >= 0 else pos
        if w.feature.pos1 in ("補助記号", "空白"):
            continue
        if w.surface.isascii():
            kana = w.surface
        else:
            kana = ""
            for k, (a0, a1, pr) in enumerate(njd):
                if a0 < pos and a1 > i and k not in used:
                    used.add(k); kana += pr
        out.append((w.surface, w.feature.pos1, kana))
    return out


def romanize(u, kana):
    import re
    return re.sub(r"[^a-z]", "", u.romanize_string(kana).lower())


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); a = ap.parse_args()
    ep = Path(a.ep); cfg = load_cfg(ep); pin_threads(cfg["env"]["threads"]); c = cfg["align"]
    import torch, uroman
    from torchaudio.pipelines import MMS_FA as B
    model, tok, aligner = B.get_model(), B.get_tokenizer(), B.get_aligner()
    u = uroman.Uroman()
    asr = load(ep / "work/asr.json")
    res, stats = {}, {}
    for s in speakers(ep):
        x, sr = read_wav(ep / "work/level" / f"{s}.wav")
        y = resample_poly(x, c["sample_rate"], sr).astype(np.float32)
        out = []
        for i, g in enumerate(asr[s]):
            toks = tokenize(g["text"])
            rom = [romanize(u, k) for _, _, k in toks]
            t0 = max(0.0, g["start"] - c["pad_s"]); t1 = min(len(y) / c["sample_rate"], g["end"] + c["pad_s"])
            seg = {"i": i, "start": g["start"], "end": g["end"], "text": g["text"], "words": [], "status": "ok", "score": 0.0}
            idx = [j for j, rr in enumerate(rom) if rr]
            words = [{"surface": su, "pos": p, "kana": k, "start": None, "end": None, "score": None} for su, p, k in toks]
            try:
                if not idx:
                    raise ValueError("nothing alignable")
                wav = torch.from_numpy(y[int(t0 * c["sample_rate"]):int(t1 * c["sample_rate"])])[None]
                with torch.inference_mode():
                    em, _ = model(wav)
                spans = aligner(em[0], tok([rom[j] for j in idx]))
                ratio = wav.shape[1] / em.shape[1] / c["sample_rate"]
                for j, sp in zip(idx, spans):
                    words[j].update(start=r(t0 + sp[0].start * ratio), end=r(t0 + sp[-1].end * ratio),
                                    score=r(float(np.mean([t.score for t in sp]))))
                sc = float(np.mean([words[j]["score"] for j in idx]))
                seg["score"] = r(sc)
                if sc < c["min_segment_score"]:
                    seg["status"] = "low"
            except Exception as e:  # aligner rejection (too many tokens for frames, empty, ...)
                seg["status"] = "rejected"; seg["error"] = type(e).__name__
            seg["words"] = words
            out.append(seg)
        res[s] = out
        stats[s] = {k: sum(1 for g in out if g["status"] == k) for k in ("ok", "low", "rejected")}
    dump(ep / "work/words.json", res)
    log_step(ep, "align_kana", stats)
    print("align", stats)


if __name__ == "__main__":
    main()
