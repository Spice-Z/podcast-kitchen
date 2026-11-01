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


def quiet(sec, seed=3):
    return 1e-4 * np.random.default_rng(seed).standard_normal(int(sec * SR))


def test_smeared_word_does_not_protect_sniff():
    # regression 20261026 raw host 26.53-26.81: word aligned 20.23-26.91 but VAD speech ends at 23.68
    x = quiet(30); x[int(20.2 * SR):int(23.7 * SR)] = tone(3.5); x[int(26.5 * SR):int(26.85 * SR)] = noise(0.35)
    vad = {"speakers": {"a": [[20.23, 23.68], [26.53, 26.81]]}}
    words = {"a": [{"start": 20.23, "end": 26.91, "text": "5年目に突入したというアイディトリオです", "status": "ok"}]}
    rd = lambda a, b: x[int(a * SR):int(b * SR)]
    reg, tr = G.speech_regions("a", vad, words, [], [], rd, SR, G_CFG, G.track_floor(x, SR))
    assert not any(overl_any(reg, 26.4, 26.9))
    assert max(b for a, b in reg) < 24.0                         # smear beyond VAD dropped; pad anchored to VAD end


def overl_any(reg, a, b):
    return [1 for p, q in reg if G.overl(a, b, p, q) > 0]


def test_sniff_in_pad_after_word_end_is_muted():
    # regression 20261026 raw host 39.4-39.8: unvoiced tail after VAD/word end inside the post-pad
    x = quiet(45); x[int(37.7 * SR):int(39.42 * SR)] = tone(1.72); x[int(39.45 * SR):int(39.75 * SR)] = noise(0.3)
    vad = {"speakers": {"a": [[37.7, 39.42]]}}
    words = {"a": [{"start": 37.7, "end": 39.52, "text": "続けてるわけですね", "status": "ok"}]}
    rd = lambda a, b: x[int(a * SR):int(b * SR)]
    reg, tr = G.speech_regions("a", vad, words, [], [], rd, SR, G_CFG, G.track_floor(x, SR))
    assert not overl_any(reg, 39.47, 39.73)
    assert any(a <= 37.7 and b >= 39.4 for a, b in reg)


def test_sniff_glued_to_vad_island_tail_is_muted_but_short_consonant_kept():
    x = quiet(20); x[int(5 * SR):int(6.2 * SR)] = tone(1.2); x[int(6.2 * SR):int(6.5 * SR)] = noise(0.3)
    x[int(10 * SR):int(11.2 * SR)] = tone(1.2); x[int(11.2 * SR):int(11.3 * SR)] = noise(0.1)   # final "-su"
    vad = {"speakers": {"a": [[5.0, 6.5], [10.0, 11.3]]}}
    words = {"a": [{"start": 5.0, "end": 6.2, "text": "ね", "status": "ok"}, {"start": 10.0, "end": 11.3, "text": "です", "status": "ok"}]}
    rd = lambda a, b: x[int(a * SR):int(b * SR)]
    reg, tr = G.speech_regions("a", vad, words, [], [], rd, SR, G_CFG, G.track_floor(x, SR))
    assert not overl_any(reg, 6.3, 6.5) and any(a <= 6.0 and b >= 6.2 for a, b in reg)
    assert any(a <= 10.0 and b >= 11.3 for a, b in reg)


def test_laugh_inside_region_not_muted_by_subwindow():
    x = quiet(10); x[int(2 * SR):int(3 * SR)] = tone(1.0); x[int(3.1 * SR):int(3.4 * SR)] = noise(0.3)
    vad = {"speakers": {"a": [[2.0, 3.0]]}}
    rd = lambda a, b: x[int(a * SR):int(b * SR)]
    reg, tr = G.speech_regions("a", vad, {"a": [{"start": 2.0, "end": 3.0, "text": "あ", "status": "ok"}]}, [],
                               [(3.1, 3.4, "a")], rd, SR, G_CFG, G.track_floor(x, SR))
    assert any(a <= 3.1 and b >= 3.4 for a, b in reg)


def test_roomtone_window_is_burst_free():
    from render import roomtone
    x = quiet(20, 5) * 0.5
    x[int(2 * SR):int(2.1 * SR)] += noise(0.1)              # sniff inside the otherwise quietest region
    x[int(5 * SR):] += quiet(15, 6) * 2                     # slightly louder but clean region
    _, t0 = roomtone(x, SR, [], 2.0)
    assert not (t0 <= 2.1 and t0 + 2.0 >= 2.0)
