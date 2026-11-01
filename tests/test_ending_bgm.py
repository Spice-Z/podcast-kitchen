import numpy as np
import pytest
import ending_bgm as B

SR = 8000
P = {**B.DEF, "lead_in_s": 3.0, "fade_in_s": 2.0, "bed_db": -20.0, "ramp_s": 1.0, "tail_db": -4.0, "tail_s": 5.0, "fade_out_s": 3.0}


def test_find_phrase_last_occurrence_in_window_uses_token_start():
    segs = [(10.0, "ということで始めます", [(10.0, "という"), (10.4, "ことで")]),
            (90.0, "はいということで今日は", [(90.0, "はい"), (90.5, "という"), (90.9, "ことで")]),
            (95.0, "ありがとうございました", [])]
    t, ph, text = B.find_phrase(segs, ["ということで"], 100.0, 30.0)
    assert t == pytest.approx(90.5) and ph == "ということで"
    assert B.find_phrase(segs, ["ということで"], 200.0, 30.0) is None       # outside the window -> skip
    assert B.find_phrase(segs, ["それでは"], 100.0, 30.0) is None


def test_last_speech_end_ignores_short_islands():
    assert B.last_speech_end([(1, 5), (6, 9.5), (9.8, 9.9)], 12.0, 0.2) == 9.5


def tone(sec, f=220, amp=0.3):
    t = np.arange(int(sec * SR)) / SR
    return amp * np.sin(2 * np.pi * f * t)


def db(x):
    return 10 * np.log10(np.mean(x ** 2) + 1e-20)


def test_mix_bgm_envelope_levels_and_extension():
    voice = np.concatenate([tone(20, 300), np.zeros(int(0.5 * SR))])       # speech ends at 20 s, file 20.5 s
    bgm = tone(60, 500, 0.5)
    vdb = B.active_rms_db(voice[:20 * SR], SR)
    y, info = B.mix_bgm(voice, bgm, SR, 12.0, 20.0, P, vdb)
    assert info["fade_in_start_s"] == pytest.approx(9.0)
    assert info["end_s"] == pytest.approx(28.0, abs=0.01) and info["extended_s"] == pytest.approx(7.5, abs=0.01)
    added = y.copy(); added[:len(voice)] -= voice
    seg = lambda a, b: added[int(a * SR):int(b * SR)]
    assert np.max(np.abs(seg(0, 8.99))) == 0                                  # nothing before the lead-in
    assert db(seg(12, 19)) - vdb == pytest.approx(-20, abs=0.5)               # ducked bed under the voices
    assert db(seg(21.5, 24.5)) - vdb == pytest.approx(-4, abs=0.5)            # BGM-only level after the last speech
    assert db(seg(9.0, 9.5)) < db(seg(10.5, 11.0))                            # fade-in
    assert np.max(np.abs(y[-int(0.05 * SR):])) < 0.02                         # faded out at the end


def make_ep(tmp_path, text="ということで以上です", **bgm_cfg):
    import json, sys, yaml, soundfile as sf
    from conftest import ROOT, seg
    ep = tmp_path / "ep"; (ep / "work").mkdir(parents=True)
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    sf.write(str(tmp_path / "bgm.wav"), np.stack([tone(40, 500, 0.5)] * 2, 1), SR)
    cfg["ending_bgm"].update({"file": str(tmp_path / "bgm.wav"), **bgm_cfg})
    (ep / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True))
    (ep / "manifest.json").write_text(json.dumps({"speakers": ["a"]}))
    v = np.concatenate([tone(20, 300), np.zeros(SR // 2)])
    sf.write(str(ep / "work/mix.wav"), np.stack([v, v], 1), SR, subtype="FLOAT")
    (ep / "work/timemap.json").write_text(json.dumps({"spans": [[0, 20.5, 0]], "edited_duration_s": 20.5}))
    (ep / "work/words.json").write_text(json.dumps({"a": [seg(14.0, 16.0, text)]}, ensure_ascii=False))
    (ep / "work/vad.json").write_text(json.dumps({"speakers": {"a": [[0.5, 20.0]]}}))
    return ep, len(v)


def run(ep, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "argv", ["ending_bgm.py", "--ep", str(ep)])
    B.main()


def frames(p):
    import soundfile as sf
    return sf.info(str(p)).frames


def test_main_applies_extends_and_is_idempotent(tmp_path, monkeypatch):
    import json
    ep, n = make_ep(tmp_path)
    run(ep, monkeypatch)
    log = json.loads((ep / "logs/ending_bgm.json").read_text())
    assert log["applied"] and log["phrase_s"] == pytest.approx(14.0) and log["fade_in_start_s"] == pytest.approx(11.0)
    n1 = frames(ep / "work/mix.wav"); assert n1 > n
    run(ep, monkeypatch)                                   # re-run: rebuilt from mix_voice.wav, not stacked
    assert frames(ep / "work/mix.wav") == n1 and frames(ep / "work/mix_voice.wav") == n
    assert json.loads((ep / "work/timemap.json").read_text())["edited_duration_s"] == pytest.approx(n1 / SR)


@pytest.mark.parametrize("kw,reason", [({"enabled": False}, "disabled"), ({"file": "/nonexistent/x.mp3"}, "not found"),
                                       ({"phrases": ["それでは"]}, "no closing phrase")])
def test_main_skips_cleanly(tmp_path, monkeypatch, capsys, kw, reason):
    import json
    ep, n = make_ep(tmp_path, **kw)
    run(ep, monkeypatch)
    log = json.loads((ep / "logs/ending_bgm.json").read_text())
    assert not log["applied"] and reason in log["reason"] and "WARNING" in capsys.readouterr().err
    assert frames(ep / "work/mix.wav") == n                 # voice mix passed through unchanged
