import pytest
import label_store as L

CANDS = [{"key": "k1", "type": "long_pause", "track": "all", "start": 1, "end": 2, "default_action": "cut", "reason": "", "excerpt": "", "confidence": .9},
         {"key": "k2", "type": "overlap_yield", "track": "host", "start": 3, "end": 4, "default_action": "mute", "reason": "", "excerpt": "", "confidence": .6},
         {"key": "k3", "type": "false_start", "track": "all", "start": 5, "end": 6, "default_action": "review", "reason": "", "excerpt": "", "confidence": .5}]


def test_seed_approves_only_auto_types(cfg):
    labels = {}
    assert L.seed(CANDS, labels, cfg) == 3
    assert labels["k1"]["approved"] and not labels["k2"]["approved"] and not labels["k3"]["approved"]


def test_seed_keeps_existing_labels(cfg):
    labels = {"k1": {"action": "keep", "labeler": "human", "approved": True, "note": ""}}
    L.seed(CANDS, labels, cfg)
    assert labels["k1"]["action"] == "keep" and labels["k1"]["labeler"] == "human"


def test_build_fails_on_unlabeled():
    with pytest.raises(SystemExit):
        L.build(CANDS, {"k1": {"action": "cut", "labeler": "rule", "approved": True}})


def test_build_schema_and_review_never_approved(cfg):
    labels = {}; L.seed(CANDS, labels, cfg); labels["k3"]["approved"] = True
    ed = L.build(CANDS, labels)
    assert set(ed[0]) == {"id", "key", "type", "track", "start", "end", "action", "approved", "labeler", "reason", "excerpt", "confidence", "note"}
    assert ed[2]["approved"] is False
