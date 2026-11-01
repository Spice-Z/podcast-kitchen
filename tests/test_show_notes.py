import json
from datetime import datetime
import show_notes as SN


def test_next_publish_is_next_monday_7am_jst():
    t = SN.next_publish(datetime(2026, 11, 1, 12, 0, tzinfo=SN.PT))      # Sun PT = Mon 05:00 JST
    assert t.strftime("%Y-%m-%d %H:%M %a") == "2026-11-02 07:00 Mon"
    t = SN.next_publish(datetime(2026, 11, 2, 7, 0, tzinfo=SN.JST))      # exactly at the slot -> next week
    assert t.strftime("%Y-%m-%d") == "2026-11-09"
    assert t.astimezone(SN.PT).strftime("%Y-%m-%d %H:%M") == "2026-11-08 14:00"


def test_package_copies_show_notes_into_out(tmp_path):
    (tmp_path / "out").mkdir(); (tmp_path / "manifest.json").write_text(json.dumps({"slug": "ep1"}))
    (tmp_path / "out/ep1.mp3").write_bytes(b""); (tmp_path / "out/chapters.json").write_text("{}")
    (tmp_path / "show_notes.md").write_text("# notes")
    pk = SN.package(tmp_path, "タイトル")
    assert (tmp_path / "out/show_notes.md").read_text() == "# notes" and pk["missing"] == []
    assert pk["artwork"] == "show default" and pk["title"] == "タイトル" and "JST" in pk["publish_at_jst"]
