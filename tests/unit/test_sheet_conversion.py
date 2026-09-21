"""T058 — spreadsheets become text the evaluator can quote."""

from __future__ import annotations

from bie.attachments import sheet_to_text


def test_every_sheet_is_a_section_with_its_header(tmp_attachments):
    text = sheet_to_text(tmp_attachments["xlsx"].read_bytes())
    assert "# preorders" in text
    assert "# costs" in text
    assert "month\tsignups\tpaid" in text
    assert "Feb\t180\t14" in text


def test_empty_cells_do_not_break_the_row(tmp_attachments):
    text = sheet_to_text(tmp_attachments["xlsx"].read_bytes())
    assert "item\tusd" in text
