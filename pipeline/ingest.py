"""Step 1: copy raw tracks into the episode folder, probe, decode gapless to 48 kHz/24-bit mono WAV.

usage: ingest.py --ep EP --track NAME=PATH [--track ...] [--transcript PATH]
Sources are copied, never moved. MP3 encoder delay/padding (LAME tag) is read and logged;
ffmpeg's mp3 decoder trims it (gapless) and we verify the decoded length against the tag.
"""
import argparse, re, shutil, struct, subprocess
from pathlib import Path
from common import REPO, dump, load_cfg, log_step, run, sha256, r


def lame_tag(path):
    """Return dict(delay, padding, frames) from a Xing/Info+LAME header, or None."""
    b = Path(path).read_bytes()[:16384]
    i = 0
    if b[:3] == b"ID3":
        sz = b[6:10]
        i = 10 + ((sz[0] << 21) | (sz[1] << 14) | (sz[2] << 7) | sz[3])
        b = Path(path).read_bytes()[: i + 16384]
    for tag in (b"Xing", b"Info"):
        x = b.find(tag, i, i + 200)
        if x < 0:
            continue
        flags = struct.unpack(">I", b[x + 4:x + 8])[0]
        o = x + 8
        frames = None
        if flags & 1:
            frames = struct.unpack(">I", b[o:o + 4])[0]; o += 4
        if flags & 2: o += 4
        if flags & 4: o += 100
        if flags & 8: o += 4
        if b[o:o + 4] != b"LAME" and b[o:o + 4] != b"Lavc" and b[o:o + 4] != b"Lavf":
            return {"frames": frames, "delay": None, "padding": None, "encoder": None}
        enc = b[o:o + 9].decode("latin1")
        d = b[o + 21:o + 24]
        return {"frames": frames, "delay": (d[0] << 4) | (d[1] >> 4),
                "padding": ((d[1] & 0xF) << 8) | d[2], "encoder": enc}
    return None


def probe(path):
    import json
    p = run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    return json.loads(p.stdout)


def tool_versions(cfg):
    v = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.split()[2]
    lame = subprocess.run(["dpkg-query", "-W", "-f=${Version}", "libmp3lame0"], capture_output=True, text=True).stdout
    soxr = subprocess.run(["dpkg-query", "-W", "-f=${Version}", "libsoxr0"], capture_output=True, text=True).stdout
    if not v.startswith(cfg["env"]["ffmpeg_version"]):
        raise SystemExit(f"ffmpeg {v} != pinned {cfg['env']['ffmpeg_version']}")
    if not lame.startswith(cfg["env"]["lame_version"]):
        raise SystemExit(f"libmp3lame {lame} != pinned {cfg['env']['lame_version']}")
    return {"ffmpeg": v, "libmp3lame": lame, "libsoxr": soxr}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ep", required=True)
    ap.add_argument("--track", action="append", required=True, help="speaker=path (speaker: lowercase ascii)")
    ap.add_argument("--transcript", action="append", default=[], help="Zencastr export: CSV/TSV (timed, primary) and/or TXT")
    ap.add_argument("--speaker", action="append", default=[], help="'Transcript Name=track' (stored only in the episode manifest)")
    ap.add_argument("--keep-config", action="store_true", help="keep an existing per-episode config.yaml override")
    a = ap.parse_args()
    ep = Path(a.ep)
    for d in ("raw", "work", "out", "logs"):
        (ep / d).mkdir(parents=True, exist_ok=True)
    if not a.keep_config or not (ep / "config.yaml").exists():  # episode copy = exact config used for this run
        shutil.copy2(REPO / "config.yaml", ep / "config.yaml")
    cfg = load_cfg(ep)
    ic = cfg["ingest"]
    versions = tool_versions(cfg)
    tracks = {}
    for t in a.track:
        spk, src = t.split("=", 1)
        if not re.fullmatch(r"[a-z0-9_]+", spk):
            raise SystemExit(f"bad speaker name {spk}")
        src = Path(src)
        dst = ep / "raw" / f"track_{spk}{src.suffix.lower()}"
        if not dst.exists() or sha256(dst) != sha256(src):
            shutil.copy2(src, dst)  # copy, never move
        pr = probe(dst)
        st = next(s for s in pr["streams"] if s["codec_type"] == "audio")
        tag = lame_tag(dst) if src.suffix.lower() == ".mp3" else None
        out = ep / "work" / "ingest" / f"{spk}.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(dst), "-map_metadata", "-1",
             "-af", f"aresample=resampler={ic['resampler']}:osr={ic['sample_rate']}",
             "-ac", str(ic["channels"]), "-c:a", ic["codec"], "-fflags", "+bitexact", "-flags:a", "+bitexact", str(out)])
        dec = probe(out)
        n_out = int(dec["streams"][0]["duration_ts"])
        start = float(st.get("start_time", 0) or 0)
        info = {"src_sha256": sha256(dst), "codec": st["codec_name"], "sample_rate": int(st["sample_rate"]),
                "channels": st["channels"], "start_time_s": start, "probe_duration_s": float(pr["format"]["duration"]),
                "decoded_samples": n_out, "decoded_s": r(n_out / ic["sample_rate"], 6), "lame": tag, "wav": str(out.relative_to(ep))}
        if tag and tag.get("frames") and tag.get("delay") is not None:
            sr = int(st["sample_rate"])
            expect = tag["frames"] * 1152 - tag["delay"] - tag["padding"]  # ffmpeg trims delay+529 at start, padding at end
            got = n_out * sr / ic["sample_rate"]
            info["gapless"] = {"expected_src_samples": expect, "decoded_src_samples": r(got, 1),
                               "diff_ms": r((got - expect) / sr * 1000, 2)}
            # start_time of a LAME-tagged mp3 reflects delay compensation, not a recording offset
            info["start_offset_s"] = r(start - (tag["delay"] + 529) / sr, 6)
        else:
            info["start_offset_s"] = start
            if src.suffix.lower() == ".mp3":
                info["gapless"] = "no LAME/Xing tag: encoder delay (~1105 samples) not removable; sync.py measures residual offset"
        if abs(info["start_offset_s"]) > ic["max_start_offset_s"]:
            raise SystemExit(f"{spk}: stream start offset {info['start_offset_s']} s exceeds limit")
        tracks[spk] = info
    longest = max(v["decoded_s"] for v in tracks.values())
    for spk, v in tracks.items():
        v["length_diff_s"] = r(longest - v["decoded_s"], 6)
        if v["length_diff_s"] > ic["max_length_diff_s"]:
            raise SystemExit(f"{spk}: {v['length_diff_s']} s shorter than longest track -> check offsets")
    has_tr = False
    for t in a.transcript:
        src = Path(t)
        shutil.copy2(src, ep / "raw" / ("transcript.csv" if src.suffix.lower() in (".csv", ".tsv") else f"transcript{src.suffix}"))
        has_tr = True
    dump(ep / "logs" / "probe.json", tracks)
    dump(ep / "manifest.json", {"slug": ep.name, "speakers": sorted(tracks), "transcript": has_tr,
                                "speaker_map": dict(x.rsplit("=", 1) for x in a.speaker),
                                "tools": versions, "config_sha256": sha256(ep / "config.yaml")})
    log_step(ep, "ingest", {"tracks": len(tracks)})
    print("ingest ok", {k: (v["decoded_s"], v["start_offset_s"]) for k, v in tracks.items()})


if __name__ == "__main__":
    main()
