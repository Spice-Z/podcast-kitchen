import json
from datetime import datetime
import show_notes as SN


def test_next_publish_is_next_monday_7am_jst():
    t = SN.next_publish(datetime(2026, 11, 1, 12, 0, tzinfo=SN.PT))      # Sun PT = Mon 05:00 JST
    assert t.strftime("%Y-%m-%d %H:%M %a") == "2026-11-02 07:00 Mon"
    t = SN.next_publish(datetime(2026, 11, 2, 7, 0, tzinfo=SN.JST))      # exactly at the slot -> next week
    assert t.strftime("%Y-%m-%d") == "2026-11-09"
    exp = datetime(2026, 11, 9, 7, 0, tzinfo=SN.JST).astimezone(SN.PT)   # whatever local tzdata says
    assert t.astimezone(SN.PT) == exp and str(SN.PT) == "America/Vancouver"


def test_package_copies_show_notes_into_out(tmp_path):
    (tmp_path / "out").mkdir(); (tmp_path / "manifest.json").write_text(json.dumps({"slug": "ep1"}))
    (tmp_path / "out/ep1.mp3").write_bytes(b""); (tmp_path / "out/chapters.json").write_text("{}")
    (tmp_path / "show_notes.md").write_text("# notes")
    pk = SN.package(tmp_path, "タイトル")
    assert (tmp_path / "out/show_notes.md").read_text() == "# notes" and pk["missing"] == ["ad_insertion_point (no applied jingle)"]
    assert pk["artwork"] == "show default" and pk["title"] == "タイトル" and "JST" in pk["publish_at_jst"]
    assert "Vancouver time (PT)" in pk["publish_at_pt"] and "PST" not in pk["publish_at_pt"] and "PDT" not in pk["publish_at_pt"]


def test_ad_insertion_point_is_pre_jingle_silence_start(tmp_path):
    (tmp_path / "logs").mkdir(); (tmp_path / "out").mkdir(); (tmp_path / "manifest.json").write_text(json.dumps({"slug": "ep1"}))
    pk = SN.package(tmp_path)
    assert pk["ad_insertion_point"] is None and any("ad_insertion_point" in m for m in pk["missing"])
    (tmp_path / "logs/jingle.json").write_text(json.dumps({"applied": True, "jingle_start_s": 1455.805, "quiet_s": 1455.405}))
    ad = SN.ad_point(tmp_path)
    assert ad == {"seconds": 1455.41, "mmss": "24:15.41"}
