# tests/test_reporter.py

_SAMPLE = [
    {
        "status": "PASS", "filename": "a.mp4", "shot": "001", "uv_area": "T",
        "duration": "2.4", "actual_res": "2318x1632", "checked_on": "2026-05-06 12:00:00",
        "rel_path": "folder/a.mp4", "airtable_synced": False,
    },
    {
        "status": "FAIL", "filename": "b.mp4", "shot": "002", "uv_area": "WallA",
        "duration": "1.1", "actual_res": "640x480", "checked_on": "2026-05-06 12:01:00",
        "rel_path": "folder/b.mp4", "airtable_synced": False,
    },
]


def test_to_csv_empty():
    from core.reporter import to_csv
    assert to_csv([]) == ""


def test_to_csv_has_header():
    from core.reporter import to_csv
    csv_str = to_csv(_SAMPLE)
    first_line = csv_str.splitlines()[0]
    assert "status" in first_line
    assert "filename" in first_line


def test_to_csv_row_count():
    from core.reporter import to_csv
    lines = [l for l in to_csv(_SAMPLE).splitlines() if l.strip()]
    assert len(lines) == 3  # header + 2 rows


def test_to_csv_contains_values():
    from core.reporter import to_csv
    out = to_csv(_SAMPLE)
    assert "a.mp4" in out
    assert "b.mp4" in out


def test_to_html_empty():
    from core.reporter import to_html
    html = to_html([])
    assert "<html" in html
    assert "0" in html


def test_to_html_contains_pass_colour():
    from core.reporter import to_html
    html = to_html(_SAMPLE)
    assert "#22c55e" in html


def test_to_html_contains_fail_colour():
    from core.reporter import to_html
    html = to_html(_SAMPLE)
    assert "#ef4444" in html


def test_to_html_summary_counts():
    from core.reporter import to_html
    html = to_html(_SAMPLE, project="Test Report")
    assert "Test Report" in html
    # 1 passed, 1 failed
    assert "1" in html
