"""Hash artifacts for determinism checks. WAVs are hashed by decoded samples + rate, because
libsndfile's PEAK chunk carries a write timestamp. Output names drop the episode slug."""
import hashlib, sys
from pathlib import Path
import soundfile as sf

root = Path(sys.argv[1]); slug = root.name


def rel(p):
    r = p.relative_to(root)
    return str(r.parent / ("<ep>" + r.name[len(slug):] if r.parts[0] == "out" and r.name.startswith(slug) else r.name))


for p in sorted(x for d in ("out", "work") for x in (root / d).rglob("*") if x.is_file()) + [root / "labels.json"]:
    if p.suffix == ".wav":
        a, sr = sf.read(p, dtype="float64", always_2d=True); h = hashlib.sha256(a.tobytes() + str(sr).encode()).hexdigest()
    else:
        h = hashlib.sha256(p.read_bytes()).hexdigest()
    print(h, rel(p))
