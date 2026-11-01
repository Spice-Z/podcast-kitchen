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


def RW(s, k, pos, t):
    return {"surface": s, "kana": k, "pos": pos, "start": t, "end": t + 0.1, "score": 0.9}


def _restart_fixture(restart_at=154.882, restart_words=None):
    host_abort = seg(151.426, 153.154, "なんか最近言われてるのは", [RW("なん", "ナン", "代名詞", 151.437), RW("か", "カ", "助詞", 151.557),
                     RW("最近", "サイキン", "名詞", 151.637), RW("言わ", "イワ", "動詞", 151.979), RW("の", "ノ", "助詞", 152.421), RW("は", "ワ", "助詞", 152.541)])
    rw = restart_words or [RW("最近", "サイキン", "名詞", restart_at + 0.01), RW("ちょろっ", "チョロッ", "副詞", restart_at + 0.4),
                           RW("聴い", "キイ", "動詞", restart_at + 0.8), RW("の", "ノ", "助詞", restart_at + 1.0)]
    host_restart = seg(restart_at, restart_at + 1.6, "最近ちょろっと聴いたのは", rw)
    ga = seg(151.618, 153.922, "学生時代の過ごし方", [RW("学生", "ガクセー", "名詞", 151.609), RW("時代", "ジダイ", "名詞", 152.154)])
    v = {"duration_s": 300.0, "speakers": {"host": [[151.426, 153.054], [restart_at, restart_at + 1.5]], "guest_a": [[151.618, 153.822]]}}
    v["union"] = sorted([list(x) for s in v["speakers"].values() for x in s])
    return v, {"host": [host_abort, host_restart], "guest_a": [ga]}


def test_overlap_restart_20261026_mutes_host_abort_only(cfg):
    v, w = _restart_fixture()
    cs = C.build(v, w, cfg)
    orr = [c for c in cs if c["type"] == "overlap_restart"]
    assert len(orr) == 1 and orr[0]["track"] == "host" and orr[0]["default_action"] == "mute"
    assert (orr[0]["start"], orr[0]["end"]) == (151.426, 153.154)
    assert not [c for c in cs if c["track"] == "guest_a" and c["default_action"] in ("cut", "mute", "duck")]
    assert not [c for c in cs if c["type"] == "overlap_yield" and c["track"] == "host"]  # not auto-kept
    assert not [c for c in cs if c["type"] == "overlap_restart" and c["track"] == "all"]
    assert "overlap_restart" in cfg["labels"]["auto_approve_types"]


def test_overlap_restart_needs_shared_content_word_and_window(cfg):
    v, w = _restart_fixture(restart_words=[RW("英語", "エーゴ", "名詞", 154.9), RW("の", "ノ", "助詞", 155.2)])
    assert not [c for c in C.build(v, w, cfg) if c["type"] == "overlap_restart"]
    v, w = _restart_fixture(restart_at=153.154 + cfg["candidates"]["overlap_restart"]["restart_window_s"] + 0.3)
    assert not [c for c in C.build(v, w, cfg) if c["type"] == "overlap_restart"]


def _T(cs, typ):
    return [c for c in cs if c["type"] == typ]


def _mutual_fixture(marker="どうぞ", restart_at=1612.26, third=False):
    host = [seg(1609.06, 1609.98, "私なんか"), seg(1611.20, 1611.84, marker)]
    ga = [seg(1609.12, 1610.30, "まあでもなんか"), seg(1610.47, 1610.80, "うん"), seg(restart_at, restart_at + 4.0, "01のハードルだいぶ下がった")]
    sp = {"host": [[1609.06, 1609.98], [1611.20, 1611.84]], "guest_a": [[1609.12, 1610.30], [1610.47, 1610.80], [restart_at, restart_at + 4.0]], "guest_b": []}
    gb = []
    if third:
        sp["guest_b"] = [[1610.9, 1611.1]]; gb = [seg(1610.9, 1611.1, "へえ")]
    return vad(sp, 3000.0), {"host": host, "guest_a": ga, "guest_b": gb}


def test_mutual_yield_cuts_collision_to_gap_before_restart(cfg):
    v, w = _mutual_fixture()
    cs = C.build(v, w, cfg)
    my = _T(cs, "mutual_yield")
    gap = cfg["candidates"]["mutual_yield"]["gap_s"]
    assert len(my) == 1 and my[0]["track"] == "all" and my[0]["default_action"] == "cut"
    assert my[0]["start"] == 1609.06 and abs(my[0]["end"] - (1612.26 - gap)) < 1e-6
    assert 0.3 <= gap <= 0.5
    assert not _T(cs, "overlap_yield")  # not left to keep_overlap_yield
    assert "mutual_yield" in cfg["labels"]["auto_approve_types"]


def test_mutual_yield_guards(cfg):
    v, w = _mutual_fixture(marker="なるほど")      # no どうぞ/お先に
    assert not _T(C.build(v, w, cfg), "mutual_yield")
    v, w = _mutual_fixture(restart_at=1611.84 + cfg["candidates"]["mutual_yield"]["restart_window_s"] + 0.5)
    assert not _T(C.build(v, w, cfg), "mutual_yield")  # nobody restarts
    v, w = _mutual_fixture(third=True)
    assert [c["default_action"] for c in _T(C.build(v, w, cfg), "mutual_yield")] == ["review"]
    cfg["candidates"]["mutual_yield"]["enabled"] = False
    v, w = _mutual_fixture()
    assert not _T(C.build(v, w, cfg), "mutual_yield")


def _interject_fixture(text="ハードルね", words=None):
    words = words or [RW("ハードル", "ハードル", "名詞", 1624.6), RW("ね", "ネ", "助詞", 1625.5)]
    host = [seg(1624.51, 1625.73, text, words),
            seg(1627.91, 1630.5, "01のハードルがなくなった", [RW("01", "ゼロイチ", "名詞", 1627.91), RW("ハードル", "ハードル", "名詞", 1628.4)])]
    gb = [seg(1622.43, 1625.92, "やっぱりそこのハードルが下がって")]
    sp = {"host": [[1624.51, 1625.73], [1627.91, 1630.5]], "guest_b": [[1622.43, 1625.92]]}
    return vad(sp, 3000.0), {"host": host, "guest_b": gb}


def test_overlap_restart_interjection_mutes_own_track(cfg):
    v, w = _interject_fixture()
    o = _T(C.build(v, w, cfg), "overlap_restart")
    assert len(o) == 1 and o[0]["track"] == "host" and o[0]["default_action"] == "mute" and "ongoing line" in o[0]["reason"]


def test_overlap_restart_interjection_skips_finished_reactions(cfg):
    for t in ("2022年か", "前半?後半?", "すごいね。", "ハードルね!"):
        v, w = _interject_fixture(text=t, words=[RW(t, "ハードル", "名詞", 1624.6)])
        assert not _T(C.build(v, w, cfg), "overlap_restart"), t
    cfg["candidates"]["overlap_restart"]["interject_lead_s"] = 5.0   # guest_b only 2.08s ahead
    v, w = _interject_fixture()
    assert not _T(C.build(v, w, cfg), "overlap_restart")


def _abandon_fixture(text="でもなんかその", x_again=None, y_end=2196.0, words=None):
    words = words or [RW("でも", "デモ", "接続詞", 2188.4), RW("その", "ソノ", "連体詞", 2189.0)]
    host = [seg(2188.39, 2189.28, text, words)]
    sp_h = [[2188.39, 2189.28]]
    if x_again:
        host.append(seg(x_again, x_again + 1.0, "AIを使う才能")); sp_h.append([x_again, x_again + 1.0])
    gb = [seg(2183.4, y_end, "自分も子供生まれたから分かるけど")]
    return vad({"host": sp_h, "guest_b": [[2183.4, y_end]]}, 3000.0), {"host": host, "guest_b": gb}


def test_overlap_abandon_mutes_only_abandoner(cfg):
    v, w = _abandon_fixture()
    cs = C.build(v, w, cfg)
    a = _T(cs, "overlap_abandon")
    assert len(a) == 1 and a[0]["track"] == "host" and a[0]["default_action"] == "mute"
    assert not [c for c in cs if c["track"] in ("guest_b", "all") and c["default_action"] in ("cut", "mute")]
    assert "overlap_abandon" in cfg["labels"]["auto_approve_types"]


def test_overlap_abandon_guards(cfg):
    for t in ("2022年か", "すごいね。", "そうなんだ", "うん", "(笑)"):
        v, w = _abandon_fixture(text=t, words=[RW(t, t, "名詞", 2188.4)])
        assert not _T(C.build(v, w, cfg), "overlap_abandon"), t
    v, w = _abandon_fixture(x_again=2191.0)          # X speaks again within 3 s
    assert not [c for c in _T(C.build(v, w, cfg), "overlap_abandon") if c["start"] == 2188.39]
    v, w = _abandon_fixture(y_end=2189.8)            # Y stops < 1 s after X
    assert not _T(C.build(v, w, cfg), "overlap_abandon")
