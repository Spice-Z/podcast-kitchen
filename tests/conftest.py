import sys
from pathlib import Path
import pytest, yaml
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))


@pytest.fixture
def cfg():
    return yaml.safe_load(open(ROOT / "config.yaml"))


def seg(t0, t1, text, words=None, status="ok", score=0.9):
    words = words or [{"surface": text, "kana": text, "pos": "名詞", "start": t0, "end": t1, "score": score}]
    return {"start": t0, "end": t1, "text": text, "status": status, "score": score, "words": words, "i": 0}
