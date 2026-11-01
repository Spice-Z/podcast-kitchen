import json
import numpy as np
import pytest
import jingle as J

SR = 8000
P = {**J.DEF, "min_start_s": 10.0, "exclude_end_s": 10.0, "chapter_before_s": 5.0, "chapter_after_s": 2.0, "avoid_margin_s": 0.5}


def isl(*spans):
    return [(a, b, s) for a, b, s in spans]


def test_chapter_boundary_preferred_and_central_one_wins():
    islands = isl((0, 19.0, "a"), (20.0, 49.0, "b"), (50.0, 79.0, "a"), (80.0, 100.0, "b"))
    segs = [(0, 19.0, "話しました。"), (20.0, 49.0, "それはこういうことです"), (50.0, 79.0, "ですよね"), (80.0, 100.0, "終わり")]
    gs = J.gaps(islands, segs, [], 10, 90, 0.35, 0.5)
    assert [g[:2] for g in gs] == [(19.0, 20.0), (49.0, 50.0), (79.0, 80.0)]
    g, why = J.choose(gs, [20.5, 50.5, 80.5], 100.0, P)
    assert g[:2] == (49.0, 50.0) and "chapter" in why          # boundary nearest the midpoint (50 s)


def test_rejects_mid_sentence_question_reply_laugh_and_edges():
    islands = isl((0, 15.0, "a"), (15.5, 30.0, "a"), (31.0, 45.0, "b"), (46.0, 60.0, "a"), (61.0, 75.0, "b"),
                  (76.0, 90.0, "a"), (91.0, 95.0, "b"), (96.0, 120.0, "a"))
    segs = [(0, 31.5, "ずっと続く文の途中で"),                    # 15-15.5 covered by a running segment -> mid-sentence
            (31.0, 45.0, "どう思いますか?"),                       # question -> answer belongs with it
            (46.0, 60.0, "そうですね。"), (61.0, 75.0, "そうそう、まさにそれです"),   # next line is a reply
            (76.0, 90.0, "以上です。"), (91.0, 95.0, "次の話題に行きます"), (96.0, 120.0, "はい")]
    avoid = [(90.2, 90.8)]                                          # laugh right at the 90-91 gap
    gs = J.gaps(islands, segs, avoid, 10, 110, 0.35, 0.5)
    starts = [g[0] for g in gs]
    assert 15.0 not in starts and 30.0 not in starts and 45.0 not in starts and 60.0 not in starts and 90.0 not in starts
    assert 75.0 in starts                                           # "…まさにそれです" -> new speaker, clean end
    assert J.gaps(islands, segs, [], 100, 110, 0.35, 0.5) == []     # last stretch excluded


def test_fallback_longest_pause_with_speaker_change():
    gs = [(32.0, 32.6, False), (40.0, 40.9, True), (60.0, 61.1, False)]
    g, why = J.choose(gs, [], 100.0, P)
    assert g == (40.0, 40.9, True) and "speaker change" in why      # 0.9 + 0.3 bonus > 1.1
    g, _ = J.choose(gs + [(50.0, 51.5, False)], [], 100.0, P)
    assert g[0] == 50.0                                              # a clearly longer pause still wins
    assert J.choose([], [], 100.0, P)[0] is None


def test_splice_shifts_chapters_and_joins():
    tm = {"spans": [[0.0, 30.0, 0.0], [35.0, 80.0, 30.0]], "joins": [{"out_s": 30.0, "ids": ["x"]}], "edited_duration_s": 75.0}
    tm2, d = J.splice(tm, 50.0, 51.0, 3.0)                          # replace a 1 s pause by 3 s
    assert d == pytest.approx(2.0) and tm2["edited_duration_s"] == pytest.approx(77.0)
    assert J.map_time(tm2, 10.0) == pytest.approx(10.0)             # before: unchanged
    assert J.map_time(tm2, 50.0) == pytest.approx(45.0)             # raw 55 -> edited 50 = gap start
    assert J.map_time(tm2, 60.0) == pytest.approx(57.0)             # after: chapter shifted by +2
    assert J.map_time(tm2, 79.0) == pytest.approx(76.0)
    assert tm2["joins"][0]["out_s"] == pytest.approx(30.0)
    tm3, _ = J.splice(tm, 20.0, 21.0, 3.0)
    assert tm3["joins"][0]["out_s"] == pytest.approx(32.0)


def tone(sec, f=300, amp=0.3):
    t = np.arange(int(round(sec * SR))) / SR
    return amp * np.sin(2 * np.pi * f * t)


def make_ep(tmp_path, **kw):
    import yaml, soundfile as sf
    from conftest import ROOT, seg
    ep = tmp_path / "ep"; (ep / "work").mkdir(parents=True)
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    sf.write(str(tmp_path / "j.wav"), tone(1.0, 700, 0.5), SR)
    cfg["jingle"].update({"file": str(tmp_path / "j.wav"), "min_start_s": 10, "exclude_end_s": 10, **kw})
    cfg["ending_bgm"]["enabled"] = False
    (ep / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True))
    (ep / "manifest.json").write_text(json.dumps({"speakers": ["a", "b"]}))
    v = np.concatenate([tone(30), np.zeros(SR), tone(30, 200)])          # speech 0-30 (a), pause 30-31, 31-61 (b)
    sf.write(str(ep / "work/mix.wav"), np.stack([v, v], 1), SR, subtype="FLOAT")
    (ep / "work/timemap.json").write_text(json.dumps({"spans": [[0, 61.0, 0]], "joins": [], "edited_duration_s": 61.0}))
    (ep / "work/words.json").write_text(json.dumps({"a": [seg(0.5, 30.0, "前半の話でした。")], "b": [seg(31.0, 60.5, "次の話題です")]},
                                                   ensure_ascii=False))
    (ep / "work/vad.json").write_text(json.dumps({"speakers": {"a": [[0.0, 30.0]], "b": [[31.0, 61.0]]}}))
    (ep / "chapters_raw.json").write_text(json.dumps([{"raw_s": 0, "title": "x"}, {"raw_s": 31.0, "title": "y"}]))
    return ep, v


def run(ep, monkeypatch, *extra):
    import sys
    monkeypatch.setattr(sys, "argv", ["jingle.py", "--ep", str(ep), *extra]); J.main()


def test_main_exact_silences_extension_and_idempotent(tmp_path, monkeypatch):
    import soundfile as sf
    ep, v = make_ep(tmp_path)
    run(ep, monkeypatch)
    y, sr = sf.read(str(ep / "work/mix.wav")); y = y[:, 0]
    log = json.loads((ep / "logs/jingle.json").read_text())
    assert log["applied"] and log["gap_start_s"] == pytest.approx(30.0) and "chapter" in log["reason"]
    i0 = 30 * SR; pre, post, jl = int(0.4 * SR), int(0.2 * SR), SR
    assert np.all(y[i0:i0 + pre] == 0) and abs(y[i0 + pre - 1 + 1]) >= 0     # exactly 0.4 s of digital silence
    assert np.max(np.abs(y[i0 + pre:i0 + pre + jl])) > 0.05                    # jingle
    assert np.all(y[i0 + pre + jl:i0 + pre + jl + post] == 0)                  # exactly 0.2 s of silence
    assert abs(y[i0 + pre + jl + post + 2 * int(0.01 * SR)]) > 0 or np.max(np.abs(y[i0 + pre + jl + post:i0 + pre + jl + post + SR])) > 0.1
    assert np.max(np.abs(y[i0 - SR // 2:i0 - int(0.01 * SR)])) > 0.1           # speech before kept
    assert len(y) == len(v) - SR + pre + jl + post                             # the 1 s pause replaced by 1.6 s
    tm = json.loads((ep / "work/timemap.json").read_text())
    assert J.map_time(tm, 31.0) == pytest.approx(31.6) and tm["edited_duration_s"] == pytest.approx(61.6)
    run(ep, monkeypatch)                                                       # re-run: still exactly one jingle
    y2, _ = sf.read(str(ep / "work/mix.wav"))
    assert len(y2) == len(y) and json.loads((ep / "work/timemap.json").read_text())["edited_duration_s"] == pytest.approx(61.6)


def test_dry_run_and_skips(tmp_path, monkeypatch, capsys):
    import soundfile as sf
    ep, v = make_ep(tmp_path)
    run(ep, monkeypatch, "--dry-run")
    assert "dry run" in capsys.readouterr().out and sf.info(str(ep / "work/mix.wav")).frames == len(v)
    ep2, v2 = make_ep(tmp_path / "x", file="/nonexistent.mp3")
    run(ep2, monkeypatch)
    assert "WARNING" in capsys.readouterr().err and sf.info(str(ep2 / "work/mix.wav")).frames == len(v2)


def test_middle_range_preferred_over_better_ranked_edge_chapter():
    p = {**P, "prefer_range_frac": [0.3, 0.7], "widen_step_frac": 0.1}
    gs = [(20.0, 21.0, True), (55.0, 55.5, False), (85.0, 86.0, True)]
    g, why = J.choose(gs, [21.5, 86.5], 100.0, p)              # chapters only at 21/86, outside 30-70
    assert g[0] == 55.0 and "tier 0" in why and why.startswith("no usable chapter")


def test_widens_stepwise_and_keeps_quality_within_tier():
    p = {**P, "prefer_range_frac": [0.4, 0.6], "widen_step_frac": 0.1}
    gs = [(25.0, 27.0, True), (33.0, 33.5, False), (68.0, 68.4, True)]
    g, why = J.choose(gs, [68.5], 100.0, p)                    # tier 1 = 30-70: chapter at 68 beats the 33 pause
    assert g[0] == 68.0 and "chapter" in why and "tier 1" in why
    g, why = J.choose([(12.0, 13.0, True)], [], 100.0, p)      # only reachable at tier 3 (10-90)
    assert g[0] == 12.0 and "tier 3" in why
    assert [t[0] for t in J.tiers(100.0, p)] == [0, 1, 2, 3, 4]


def test_waits_out_laughter_and_aizuchi_tail():
    islands = isl((0, 20.0, "a"), (20.3, 20.9, "b"), (21.2, 22.0, "c"), (23.0, 40.0, "a"))   # b aizuchi, c laugh
    segs = [(0, 20.0, "前の話でした。"), (23.0, 40.0, "次の話題に行きます")]
    gs = J.gaps(islands, segs, [], 10, 35, 0.35, 0.5, 0.3, reactions=[(21.2, 22.0)], max_tail_s=4.0)
    assert gs == [(22.0, 23.0, False, 2.0)]                    # inserted after the laugh, nothing cut


def test_tail_into_new_speech_or_too_long_is_rejected():
    islands = isl((0, 20.0, "a"), (20.3, 20.8, "b"), (20.9, 30.0, "b"))                        # b starts talking for real
    segs = [(0, 20.0, "前の話でした。"), (20.9, 30.0, "それで次の話なんですが")]
    assert J.gaps(islands, segs, [], 10, 35, 0.35, 0.5) == []
    islands = isl((0, 20.0, "a"), (20.2, 25.5, "c"), (26.0, 40.0, "a"))                         # 5.5 s laugh
    segs = [(0, 20.0, "前の話でした。"), (26.0, 40.0, "次の話題に行きます")]
    assert J.gaps(islands, segs, [], 10, 35, 0.35, 0.5, 0.3, reactions=[(20.2, 25.5)], max_tail_s=4.0) == []
    assert J.gaps(islands, segs, [], 10, 35, 0.35, 0.5, 0.3, reactions=[(20.2, 25.5)], max_tail_s=6.0)[0][:2] == (25.5, 26.0)


# ---- track-shift ----
PS = {**P, "chapter_before_s": 5.0, "chapter_after_s": 2.0}


def shift_scene(tail_end=21.0, tail_kind="react", other_start=None):
    # a talks until 18 (sentence end), b laughs 19.5-tail_end, a's new topic starts at 20.0 (chapter at 20)
    islands = [(5.0, 18.0, "a"), (19.5, tail_end, "b"), (20.0, 30.0, "a")]
    segs = [(5.0, 18.0, "話しました。", "a"), (20.0, 30.0, "ちなみに次の話題ですが", "a")]
    if tail_kind == "speech":
        segs.append((19.5, tail_end, "いやほんとにそれは大事な話で", "b"))
    if other_start is not None:
        islands.append((other_start, other_start + 3, "b")); segs.append((other_start, other_start + 3, "えっと私も話したいのは", "b"))
    react = [(19.5, tail_end)] if tail_kind == "react" else []
    return sorted(islands), segs, react


def test_shift_candidate_found_and_fields():
    isl_, segs, rx = shift_scene()
    out = J.shift_candidates(isl_, segs, rx, [20.0], PS, 10, 90)
    assert len(out) == 1
    T, _, sc, tail, info = out[0]
    assert T == 21.0 and info == {"speaker": "a", "split_s": 19.95, "quiet_s": 21.0} and tail == pytest.approx(1.05)


def test_shift_rejects_overlap_with_substantive_speech_and_cap():
    isl_, segs, rx = shift_scene(tail_end=22.0, tail_kind="speech")      # b's real line runs 2 s past a's onset
    assert J.shift_candidates(isl_, segs, rx, [20.0], PS, 10, 90) == []
    isl_, segs, rx = shift_scene(other_start=20.5)                       # b starts real speech after the split
    assert J.shift_candidates(isl_, segs, rx, [20.0], PS, 10, 90) == []
    isl_, segs, rx = shift_scene(tail_end=23.5)                          # laugh tail > max_shift_s (3.0)
    assert J.shift_candidates(isl_, segs, rx, [20.0], PS, 10, 90) == []
    assert J.shift_candidates(isl_, segs, rx, [20.0], {**PS, "max_shift_s": 4.0}, 10, 90) != []


def test_chapter_track_shift_beats_plain_pause():
    gs = [(45.0, 46.5, True), (50.2, 50.2, True, 1.0, {"speaker": "a", "split_s": 49.0, "quiet_s": 50.2})]
    g, why = J.choose(gs, [49.5], 100.0, P)
    assert g[0] == 50.2 and "chapter" in why


def test_write_track_shift_keeps_every_sample_and_exact_silences(tmp_path):
    import soundfile as sf
    ep = tmp_path / "ep"; (ep / "work/render").mkdir(parents=True)
    n = SR * 40; rng = np.random.default_rng(0)
    a = np.zeros(n); b = np.zeros(n)
    a[: 18 * SR] = rng.uniform(-.3, .3, 18 * SR); a[20 * SR:] = rng.uniform(-.3, .3, n - 20 * SR)
    b[int(19.5 * SR): int(20.9 * SR)] = rng.uniform(-.3, .3, int(1.4 * SR))   # quiet by T = 21.0
    sf.write(str(ep / "work/render/a.wav"), a, SR, subtype="FLOAT"); sf.write(str(ep / "work/render/b.wav"), b, SR, subtype="FLOAT")
    a, b = sf.read(str(ep / "work/render/a.wav")), sf.read(str(ep / "work/render/b.wav"))[0]; a = a[0]
    p = {**J.DEF, "edge_fade_ms": 0}
    pre, post = int(0.4 * SR), int(0.2 * SR); jin = np.full(SR, 0.5)
    ins = np.concatenate([np.zeros(pre), jin, np.zeros(post)])
    ts = {"speaker": "a", "split_s": 19.95, "quiet_s": 21.0}
    J.write_track_shift(ep, ep / "work/mix.wav", SR, 1, ts, 21.0, ins, p)
    y, _ = sf.read(str(ep / "work/mix.wav"))
    sp, T, L = int(19.95 * SR), 21 * SR, len(ins); D = T - sp + L
    assert len(y) == n + D
    exp = np.zeros(n + D)
    exp[:sp] += a[:sp]; exp[sp + D:] += a[sp:]
    exp[:T] += b[:T]; exp[T + D:] += b[T:]
    exp[T:T + L] += ins
    assert np.allclose(y, exp, atol=1e-6)                                 # nothing lost, nothing reordered
    assert np.all(y[T:T + pre] == 0) and np.all(y[T + pre + SR:T + L] == 0)  # exact 0.4 / 0.2 s silences
    assert np.allclose(y[T + L:T + L + SR], a[sp:sp + SR])                # a resumes from its split point right after
    tm = {"spans": [[0.0, 40.0, 0.0]], "joins": [], "edited_duration_s": 40.0}
    tm2, d = J.splice(tm, 19.95, 19.95, D / SR)
    assert J.map_time(tm2, 25.0) == pytest.approx(25.0 + D / SR)          # chapters after the split shift by D
