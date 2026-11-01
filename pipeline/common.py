"""Shared helpers. Works in both venvs (numpy, soundfile, pyyaml only)."""
import hashlib, json, os, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_cfg(ep: Path) -> dict:
    import yaml
    p = Path(ep) / "config.yaml"
    if not p.exists():
        p = REPO / "config.yaml"
    return yaml.safe_load(p.read_text())


def pin_threads(n: int):
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[k] = str(n)
    try:
        import torch
        torch.set_num_threads(n)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True, warn_only=True)
        torch.manual_seed(0)
    except Exception:
        pass


def dump(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    tmp.replace(path)


def load(path):
    return json.loads(Path(path).read_text())


def sha256(path, n=None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:n] if n else h.hexdigest()


def key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def r(x, n=3):
    return round(float(x), n)


def run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode:
        sys.stderr.write(p.stderr[-3000:])
        raise SystemExit(f"command failed: {' '.join(map(str, cmd[:6]))} ...")
    return p


def speakers(ep):
    return load(Path(ep) / "manifest.json")["speakers"]


def read_wav(path):
    import soundfile as sf
    x, sr = sf.read(str(path), dtype="float64", always_2d=False)
    return x, sr


def write_wav(path, x, sr, subtype="FLOAT"):
    import soundfile as sf
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), x, sr, subtype=subtype)


def log_step(ep, step, info):
    p = Path(ep) / "logs" / "steps.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps({"step": step, **info}, ensure_ascii=False, sort_keys=True) + "\n")
