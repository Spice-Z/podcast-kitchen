from conftest import seg
import candidates as C


def vad(sp, dur=60.0):
    u = sorted(iv for v in sp.values() for iv in v)
    m = []
    for s, e in u:
        if m and s <= m[-1][1]:
            m[-1][1] = max(m[-1][1], e)
        else:
            m.append([s, e])
    return {"speakers": sp, "union": m, "duration_s": dur}


def test_long_pause_within_turn_compressed_to_target(cfg):
    v = vad({"host": [[1, 5], [7, 12]], "guest_a": [[20, 25]]})
    w = {"host": [seg(1, 5, "それで"), seg(7, 12, "次の話")], "guest_a": [seg(20, 25, "なるほどですね")]}
    lp = [c for c in C.build(v, w, cfg) if c["type"] == "long_pause"]
    tgt = cfg["candidates"]["long_pause"]["target_s"]
    within = [c for c in lp if c["start"] < 7]
    assert len(within) == 1 and within[0]["default_action"] == "cut" and within[0]["track"] == "all"
    assert abs((7 - 5) - (within[0]["end"] - within[0]["start"]) - tgt) < 1e-6


def test_long_pause_below_threshold_ignored(cfg):
    thr = cfg["candidates"]["long_pause"]["within_turn_min_s"]
    v = vad({"host": [[1, 5], [5 + thr - 0.05, 10]]})
    assert not [c for c in C.build(v, {"host": [seg(1, 5, "あ"), seg(6, 10, "い")]}, cfg) if c["type"] == "long_pause"]


def test_long_pause_before_laugh_goes_to_review(cfg):
    v = vad({"host": [[1, 5]], "guest_a": [[8, 12]]})
    w = {"host": [seg(1, 5, "オチです")], "guest_a": [seg(8, 12, "(笑)")]}
    lp = [c for c in C.build(v, w, cfg) if c["type"] == "long_pause"]
    assert lp and all(c["default_action"] == "review" for c in lp)


def test_overlap_yield_mutes_only_yielder(cfg):
    v = vad({"host": [[40.0, 41.0]], "guest_a": [[40.2, 48.0]]}, dur=120)
    w = {"host": [seg(40.0, 41.0, "それで僕が")], "guest_a": [seg(40.2, 48.0, "いやこれは長く続く話なんですけど")]}
    oy = [c for c in C.build(v, w, cfg) if c["type"] == "overlap_yield"]
    assert len(oy) == 1 and oy[0]["track"] == "host" and oy[0]["default_action"] == "mute"
    assert all(c["track"] != "guest_a" for c in oy)


def test_backchannel_is_ducked_not_cut(cfg):
    v = vad({"host": [[0, 20]], "guest_a": [[5.0, 5.4]]})
    w = {"host": [seg(0, 20, "長い説明が続いています")], "guest_a": [seg(5.0, 5.4, "うん")]}
    bc = [c for c in C.build(v, w, cfg) if c["type"] == "backchannel"]
    assert bc and all(c["track"] == "guest_a" and c["default_action"] in ("keep", "duck", "review") for c in bc)
    assert not any(c["default_action"] == "cut" for c in bc)


def test_keys_are_stable(cfg):
    v = vad({"host": [[1, 5], [7, 12]]})
    w = {"host": [seg(1, 5, "それで"), seg(7, 12, "次の話")]}
    assert [c["key"] for c in C.build(v, w, cfg)] == [c["key"] for c in C.build(v, w, cfg)]


def test_head_tail_protected_goes_to_review(cfg):
    v = vad({"host": [[10.0, 11.0]], "guest_a": [[10.2, 18.0]]}, dur=120)
    w = {"host": [seg(10.0, 11.0, "それで僕が")], "guest_a": [seg(10.2, 18.0, "いやこれは長く続く話なんですけど")]}
    assert [c["default_action"] for c in C.build(v, w, cfg) if c["type"] == "overlap_yield"] == ["review"]
