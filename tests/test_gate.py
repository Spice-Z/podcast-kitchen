import numpy as np
import gate as G

G_CFG = {"transient_max_s": 0.6, "voicing_max": 0.35, "flatness_min": 0.3, "pad_before_ms": 150, "pad_after_ms": 250,
         "merge_gap_ms": 300, "fade_ms": 15, "attenuation_db": "-inf", "transient_rise_db": 15, "noise_floor_min_db": -80}
SR = 16000


def tone(sec, f=150):
    t = np.arange(int(sec * SR)) / SR
    return 0.3 * np.sin(2 * np.pi * f * t) * (1 + 0.5 * np.sin(2 * np.pi * 3 * t))


def noise(sec, seed=0):
    return 0.3 * np.random.default_rng(seed).standard_normal(int(sec * SR))


def test_classify_voiced_vs_sniff():
    assert not G.classify(tone(0.3), SR, G_CFG)["transient"]
    assert G.classify(noise(0.3), SR, G_CFG)["transient"]


def test_regions_pad_merge_and_transient_gated():
    x = np.zeros(10 * SR); x[int(5 * SR):int(5.3 * SR)] = noise(0.3)   # sniff at 5.0-5.3, no text
    x[int(7 * SR):int(7.3 * SR)] = tone(0.3)                             # voiced untranscribed island (laugh-like)
    vad = {"speakers": {"a": [[1.0, 2.0], [2.2, 3.0], [5.0, 5.3], [7.0, 7.3]]}}
    words = {"a": [{"start": 1.0, "end": 3.0, "text": "こんにちは", "status": "ok"}]}
    rd = lambda a, b: x[int(a * SR):int(b * SR)]
    reg, tr = G.speech_regions("a", vad, words, [], [], rd, SR, G_CFG)
    assert [round(v, 2) for v in reg[0]] == [0.85, 3.25]       # padded 150/250 ms, gap < 300 ms merged
    assert len(tr) == 1 and tr[0]["start"] == 5.0             # sniff classified and gated
    assert any(a <= 7.0 and b >= 7.3 for a, b in reg)          # voiced island kept as speech


def test_laugh_and_backchannel_never_gated():
    x = noise(10)
    vad = {"speakers": {"a": [[4.0, 4.4], [6.0, 6.3]]}}
    rd = lambda a, b: x[int(a * SR):int(b * SR)]
    reg, tr = G.speech_regions("a", vad, {"a": []}, [{"type": "backchannel", "track": "a", "start": 4.0, "end": 4.4}],
                               [(6.0, 6.3, "a")], rd, SR, G_CFG)
    assert not tr and len(reg) == 2


def test_gain_grid_mute_and_fades():
    gg = G.gain_grid([[1.0, 2.0]], 3.0, G_CFG)
    assert gg[500] == 0 and gg[1500] == 1 and 0 < gg[1000] < 1 and gg[2500] == 0
    g40 = G.gain_grid([[1.0, 2.0]], 3.0, {**G_CFG, "attenuation_db": -40})
    assert abs(g40[500] - 0.01) < 1e-9


def test_bursts_counted_outside_speech_only():
    x = 1e-4 * np.random.default_rng(1).standard_normal(10 * SR)
    x[int(5 * SR):int(5.2 * SR)] += noise(0.2)
    assert G.bursts(x, SR, [], G_CFG) == 1
    assert G.bursts(x, SR, [[4.9, 5.3]], G_CFG) == 0
