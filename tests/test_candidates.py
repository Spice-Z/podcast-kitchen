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
    assert lp and all(c["default_action"] in ("review", "keep") for c in lp)


def test_overlap_yield_targets_only_yielder_never_auto_mutes(cfg):
    v = vad({"host": [[40.0, 41.0], [42.0, 42.8]], "guest_a": [[40.2, 48.0]]}, dur=120)
    w = {"host": [seg(40.0, 41.0, "それで僕が"), seg(42.0, 42.8, "どうぞどうぞ")], "guest_a": [seg(40.2, 48.0, "いやこれは長く続く話なんですけど")]}
    oy = [c for c in C.build(v, w, cfg) if c["type"] == "overlap_yield"]
    assert len(oy) == 1 and oy[0]["track"] == "host" and oy[0]["default_action"] in ("review", "keep")
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
    assert [c["default_action"] for c in C.build(v, w, cfg) if c["type"] == "overlap_yield"] in (["review"], ["keep"])


def test_overlap_without_marker_or_mid_turn_not_muted(cfg):
    # finished phrase at the end of the speaker's own turn (no pre-silence) -> no candidate
    v = vad({"guest_b": [[30.0, 39.4], [40.0, 41.0]], "guest_a": [[40.2, 48.0]]}, dur=120)
    w = {"guest_b": [seg(30.0, 39.4, "こう言うと"), seg(40.0, 41.0, "それっぽくやってくる")], "guest_a": [seg(40.2, 48.0, "それ用のエージェントを作って任せる")]}
    assert not [c for c in C.build(v, w, cfg) if c["type"] == "overlap_yield"]
    # turn start but no yield marker -> review, never mute
    v = vad({"guest_b": [[40.0, 41.0]], "guest_a": [[40.2, 48.0]]}, dur=120)
    w = {"guest_b": [seg(40.0, 41.0, "そうだと思う本当に")], "guest_a": [seg(40.2, 48.0, "結構それができるスキルって大事")]}
    assert [c["default_action"] for c in C.build(v, w, cfg) if c["type"] == "overlap_yield"] in (["review"], ["keep"])



def W(t, sur):
    out = []
    for k, x in enumerate(sur):
        out.append({"surface": x, "kana": x, "pos": "名詞", "start": t + 0.3 * k, "end": t + 0.3 * k + 0.25, "score": 0.9})
    return out


def test_false_start_immediate_restart_cut_parallel_structure_review(cfg):
    a = ["ずっと", "使って", "ずっと", "使って", "て"]
    b = ["毎月", "というか", "毎週", "というか", "変化"]
    v = vad({"host": [[60.0, 61.6], [80.0, 81.6]]}, dur=200)
    w = {"host": [seg(60.0, 61.6, "".join(a), W(60.0, a)), seg(80.0, 81.6, "".join(b), W(80.0, b))]}
    fs = {round(c["start"]): c["default_action"] for c in C.build(v, w, cfg) if c["type"] == "false_start"}
    assert fs.get(60) == "cut"
    assert fs.get(80) in (None, "review")


def test_auto_decide_only_keeps():
    cs = [{"type": "false_start", "default_action": "review", "reason": "repeated phrase (parallel structure?)", "confidence": 0.3},
          {"type": "false_start", "default_action": "review", "reason": "immediate restart", "confidence": 0.5},
          {"type": "filler", "default_action": "cut", "reason": "filler", "confidence": 0.9}]
    out = C.auto_decide(cs, {"enabled": True})
    assert [c["default_action"] for c in out] == ["keep", "review", "cut"]
