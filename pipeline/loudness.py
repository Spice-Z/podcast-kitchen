"""Step 5b: the one loudness tool: ffmpeg loudnorm, two-pass, linear only.
pass 1 measure -> if the linear gain would push true peak above (max_true_peak - limiter_headroom),
pre-limit with alimiter at the needed ceiling and re-measure -> pass 2 linear=true. Fails if ffmpeg
reports normalization_type != linear. Deliverable: out/<slug>.mp3 only (LAME CBR, 44.1k stereo). The normalized
WAV is a temp file in work/ deleted after encoding, as are prelimited.wav and (with output.delete_render_wavs) mix.wav, mix_voice.wav + work/render/*.wav and logs/loudness.json."""
import argparse, json, re
from pathlib import Path
from common import dump, load, load_cfg, log_step, run, r

BX = ["-fflags", "+bitexact", "-flags:a", "+bitexact", "-map_metadata", "-1"]


def measure(src, L):
    p = run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(src), "-af",
             f"loudnorm=I={L['target_lufs']}:TP={L['max_true_peak_dbtp']}:LRA={L['lra']}:print_format=json", "-f", "null", "-"])
    return json.loads(re.findall(r"\{[^{}]*\}", p.stderr)[-1])


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ep", required=True); a = ap.parse_args()
    ep = Path(a.ep); cfg = load_cfg(ep); L = cfg["loudness"]; slug = load(ep / "manifest.json")["slug"]
    src = ep / "work/mix.wav"
    m1 = measure(src, L)
    gain = L["target_lufs"] - float(m1["input_i"])
    ceiling = L["max_true_peak_dbtp"] - L["limiter_headroom_db"]
    log = {"pass1": m1, "gain_db": r(gain, 2), "prelimit": None}
    if float(m1["input_tp"]) + gain > ceiling:
        lim_db = ceiling - gain
        pre = ep / "work/prelimited.wav"
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-af",
             f"alimiter=limit={10 ** (lim_db / 20):.6f}:level=false:attack=5:release=50:asc=false",
             "-c:a", "pcm_f32le", *BX, str(pre)])
        src = pre; log["prelimit"] = {"limit_dbfs": r(lim_db, 2)}
        m1 = measure(src, L); log["pass1_after_limit"] = m1
    ln = (f"loudnorm=I={L['target_lufs']}:TP={L['max_true_peak_dbtp']}:LRA={L['lra']}:linear=true:"
          f"measured_I={m1['input_i']}:measured_TP={m1['input_tp']}:measured_LRA={m1['input_lra']}:"
          f"measured_thresh={m1['input_thresh']}:offset={m1['target_offset']}:print_format=json")
    M = L["master"]; master = ep / "work" / "normalized.tmp.wav"
    p = run(["ffmpeg", "-nostdin", "-hide_banner", "-y", "-i", str(src), "-af",
             f"{ln},aresample=resampler=soxr:osr={M['sample_rate']}",
             "-c:a", M["codec"], *BX, str(master)])
    m2 = json.loads(re.findall(r"\{[^{}]*\}", p.stderr)[-1]); log["pass2"] = m2
    if m2.get("normalization_type") != "linear":
        raise SystemExit(f"loudnorm fell back to {m2.get('normalization_type')}; refusing non-linear output")
    P = L["mp3"]; mp3 = ep / "out" / f"{slug}.mp3"
    run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(master), "-af", f"aresample=resampler=soxr:osr={P['sample_rate']}",
         "-ac", str(P["channels"]), "-c:a", P["codec"], "-b:a", P["bitrate"], *BX, "-write_xing", "1", "-id3v2_version", "0", str(mp3)])
    master.unlink(missing_ok=True); (ep / "work/prelimited.wav").unlink(missing_ok=True)
    (ep / "out" / f"{slug}_master.wav").unlink(missing_ok=True)
    if cfg.get("output", {}).get("delete_render_wavs", True):
        (ep / "work/mix.wav").unlink(missing_ok=True); (ep / "work/mix_voice.wav").unlink(missing_ok=True); (ep / "work/mix_prejingle.wav").unlink(missing_ok=True)
        (ep / "work/.ending_bgm").unlink(missing_ok=True)
        for w in (ep / "work/render").glob("*.wav"): w.unlink()
    dump(ep / "logs/loudness.json", log)
    log_step(ep, "loudness", {"type": m2["normalization_type"]})
    print("loudness ok", m2["output_i"], m2["output_tp"], m2["normalization_type"])


if __name__ == "__main__":
    main()
