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


def test_sniff_in_pad_after_vad_end_is_muted_unless_word_final():
    # sniff in the post-pad after a VAD end with no word ending there -> muted; at a word end the first
    # word_end_keep_s is protected (20261026 raw 39.42: the 「ね」 tail, wrongly muted in v4)
    x = quiet(45); x[int(37.7 * SR):int(39.42 * SR)] = tone(1.72); x[int(39.45 * SR):int(39.65 * SR)] = highband_noise(0.2)
    vad = {"speakers": {"a": [[37.7, 39.42]]}}
    rd = lambda a, b: x[int(a * SR):int(b * SR)]
    w_mid = {"a": [{"start": 37.7, "end": 40.5, "text": "続けてるわけですね", "status": "ok"}]}
    reg, tr = G.speech_regions("a", vad, w_mid, [], [], rd, SR, G_CFG, G.track_floor(x, SR))
    assert not overl_any(reg, 39.47, 39.63) and any(a <= 37.7 and b >= 39.4 for a, b in reg)
    w_end = {"a": [{"start": 37.7, "end": 39.52, "text": "続けてるわけですね", "status": "ok"}]}
    reg, tr = G.speech_regions("a", vad, w_end, [], [], rd, SR, G_CFG, G.track_floor(x, SR))
    assert any(a <= 39.42 and b >= 39.6 for a, b in reg)


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


def lowband_noise(sec, seed=7):
    n = noise(sec, seed); k = np.ones(24) / 24
    return np.convolve(n, k, mode="same") * 4                 # ~< 700 Hz, unperiodic (breathy/creaky decay)


def highband_noise(sec, seed=8):
    n = noise(sec, seed)
    return np.diff(np.diff(n, prepend=0), prepend=0) * 0.5    # energy mostly above 2 kHz (sniff)


def test_classify_needs_low_voicing_and_high_band():
    assert G.classify(highband_noise(0.2), SR, G_CFG)["transient"]
    assert not G.classify(lowband_noise(0.2), SR, G_CFG)["transient"]   # unvoiced but low-band -> speech decay


def test_breathy_word_end_decay_kept_synthetic():
    # 20261026 raw host 39.2-39.45: 「ね」 fades out low-band with low periodicity, VAD end 39.42, word end 39.52
    x = quiet(45); x[int(37.7 * SR):int(39.2 * SR)] = tone(1.5)
    d = lowband_noise(0.25) * np.linspace(0.5, 0.01, int(0.25 * SR)); x[int(39.2 * SR):int(39.45 * SR)] = d
    vad = {"speakers": {"a": [[37.7, 39.42]]}}
    words = {"a": [{"start": 37.7, "end": 39.52, "text": "続けてるわけですね", "status": "ok"}]}
    rd = lambda a, b: x[int(a * SR):int(b * SR)]
    reg, tr = G.speech_regions("a", vad, words, [], [], rd, SR, G_CFG, G.track_floor(x, SR))
    assert any(a <= 37.7 and b >= 39.42 for a, b in reg)


def test_mostly_unvoiced_island_with_hallucinated_word_muted_synthetic():
    # 20261026 raw host 40.61-41.31: ASR word 「ありがとうございました。」 over a sniff island (0.7 s > transient_max_s)
    x = quiet(45); x[int(40.6 * SR):int(40.8 * SR)] = lowband_noise(0.2); x[int(41.0 * SR):int(41.3 * SR)] = highband_noise(0.3)
    vad = {"speakers": {"a": [[40.61, 41.31]]}}
    words = {"a": [{"start": 40.61, "end": 41.41, "text": "ありがとうございました。", "status": "ok"}]}
    rd = lambda a, b: x[int(a * SR):int(b * SR)]
    reg, tr = G.speech_regions("a", vad, words, [], [], rd, SR, G_CFG, G.track_floor(x, SR))
    assert not overl_any(reg, 40.6, 41.3)


def test_fricative_inside_speech_kept_but_isolated_sniff_window_muted():
    x = quiet(10)
    x[int(1 * SR):int(2 * SR)] = tone(1.0); x[int(2 * SR):int(2.1 * SR)] = highband_noise(0.1); x[int(2.1 * SR):int(3 * SR)] = tone(0.9)
    x[int(4 * SR):int(5 * SR)] = tone(1.0); x[int(5.1 * SR):int(5.4 * SR)] = highband_noise(0.3); x[int(5.5 * SR):int(6.5 * SR)] = tone(1.0)
    vad = {"speakers": {"a": [[1.0, 3.0], [4.0, 6.5]]}}
    words = {"a": [{"start": 1.0, "end": 3.0, "text": "あさ", "status": "ok"}, {"start": 4.0, "end": 6.5, "text": "あい", "status": "ok"}]}
    rd = lambda a, b: x[int(a * SR):int(b * SR)]
    reg, tr = G.speech_regions("a", vad, words, [], [], rd, SR, G_CFG, G.track_floor(x, SR))
    assert any(a <= 1.0 and b >= 3.0 for a, b in reg)                       # "s" between vowels kept
    assert not overl_any(reg, 5.2, 5.3)                                       # isolated sniff inside the island muted


EP = "/workspace/podcast/episodes/20261026"


def _real():
    import json, os, pytest
    sf = pytest.importorskip("soundfile")
    p = f"{EP}/work/level/host.wav"
    if not os.path.exists(p):
        pytest.skip("20261026 episode data not available")
    sr = sf.info(p).samplerate
    x = sf.read(p, start=15 * sr, stop=45 * sr, dtype="float64")[0]
    if x.ndim > 1: x = x.mean(1)
    rd = lambda a, b: x[max(0, int((a - 15) * sr)):max(0, int((b - 15) * sr))]
    vad = {"speakers": {"host": [v for v in json.load(open(f"{EP}/work/vad.json"))["speakers"]["host"] if 15 < v[0] and v[1] < 45]}}
    words = {"host": [w for w in json.load(open(f"{EP}/work/words.json"))["host"] if 15 < w["start"] and w["end"] < 45]}
    return G.speech_regions("host", vad, words, [], [], rd, sr, G_CFG, -106.6)


def test_real_20261026_host_ne_decay_kept_and_sniffs_muted():
    reg, tr = _real()
    assert any(a <= 39.2 and b >= 39.45 for a, b in reg)        # 「ね」 decay kept
    assert not overl_any(reg, 26.53, 26.81)                     # sniff (edited ~0:15) muted
    assert not overl_any(reg, 40.6, 41.3)                       # sniff after 「続けてるわけですね」 muted


def _real_cfg(spk, t0, t1, floor):
    import json, os, pytest, yaml
    sf = pytest.importorskip("soundfile")
    p = f"{EP}/work/level/{spk}.wav"
    if not os.path.exists(p):
        pytest.skip("20261026 episode data not available")
    cfg = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "..", "config.yaml")))["gate"]
    sr = sf.info(p).samplerate
    x = sf.read(p, start=int(t0 * sr), stop=int(t1 * sr), dtype="float64")[0]
    if x.ndim > 1: x = x.mean(1)
    rd = lambda a, b: x[max(0, int((a - t0) * sr)):max(0, int((b - t0) * sr))]
    vad = {"speakers": {spk: [v for v in json.load(open(f"{EP}/work/vad.json"))["speakers"][spk] if t0 < v[0] and v[1] < t1]}}
    words = {spk: [w for w in json.load(open(f"{EP}/work/words.json"))[spk] if t0 < w["start"] and w["end"] < t1]}
    return G.speech_regions(spk, vad, words, [], [], rd, sr, cfg, floor)


def test_real_20261026_host_throat_clear_burst_muted():
    reg, tr = _real_cfg("host", 330, 350, -106.6)
    assert not overl_any(reg, 342.40, 342.69)
    assert any(t.get("kind") == "burst" and t["start"] <= 342.5 <= t["end"] for t in tr)


def test_real_20261026_host_ne_decay_kept_with_burst_rule():
    reg, tr = _real_cfg("host", 15, 45, -106.6)
    assert any(a <= 39.2 and b >= 39.45 for a, b in reg)


def test_real_20261026_guest_a_hum_kept_by_burst_rule():
    reg, tr = _real_cfg("guest_a", 330, 350, -86.1)
    assert any(a <= 341.63 and b >= 342.27 for a, b in reg)
