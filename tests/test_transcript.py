import zencastr_transcript as Z

C = {"max_utt_s": 30, "snap_s": 0.6, "end_pad_s": 0.1}


def test_ts_and_rows(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("Timestamp\tSpeaker\tTranscript\n00:01.24\tA\tこんにちは\n1:02:03.50\tB\tはい\n01:00.00\tA\t\n", encoding="utf-8")
    assert Z.read_rows(p) == [(1.24, "A", "こんにちは"), (3723.5, "B", "はい")]


def test_segments_snap_and_clip():
    isl = [[1.0, 2.0], [2.3, 3.0], [10.0, 11.0]]
    seg = Z.segments([(1.3, "あ"), (10.2, "い"), (20.0, "う")], isl, C, 60.0)
    assert seg[0]["start"] == 1.0 and seg[0]["end"] == 3.1          # snapped, clipped to last island before next utt
    assert seg[1]["start"] == 10.0 and seg[1]["end"] == 11.1
    assert seg[2]["flags"] == ["no_vad_speech"] and seg[2]["end"] < 21


def test_coverage_gaps():
    segs = [{"start": 1.0, "end": 3.0}]
    assert Z.coverage(segs, [[1.0, 2.0], [5.0, 7.0], [8.0, 8.5]], 1.5) == [[5.0, 7.0]]
