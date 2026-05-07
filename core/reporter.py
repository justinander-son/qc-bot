from __future__ import annotations

import csv
import io


def to_csv(results: list[dict]) -> str:
    """Convert a list of result dicts to a CSV string."""
    if not results:
        return ""
    fieldnames = [
        "status", "filename", "shot", "uv_area", "duration",
        "actual_res", "checked_on", "rel_path", "airtable_synced",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(results)
    return buf.getvalue()


def to_html(results: list[dict], project: str = "QC Report") -> str:
    """Generate a standalone HTML report from a list of result dicts.

    Returns a complete HTML document as a string.
    Dark theme matching the dashboard.
    """
    total = len(results)
    passed = sum(1 for r in results if r.get("status", "").upper() in ("PASS", "OVERRIDDEN"))
    failed = sum(1 for r in results if r.get("status", "").upper() == "FAIL")
    errors = sum(1 for r in results if r.get("status", "").upper() == "ERROR")
    pass_rate = (passed / total * 100) if total > 0 else 0.0

    _STATUS_COLORS = {
        "PASS": "#22c55e",
        "FAIL": "#ef4444",
        "ERROR": "#f97316",
        "OVERRIDDEN": "#eab308",
        "SKIPPED": "#6b7280",
    }

    rows_html = []
    for r in results:
        status = r.get("status", "").upper()
        color = _STATUS_COLORS.get(status, "#ffffff")
        rows_html.append(
            f"<tr>"
            f"<td style='color:{color};font-weight:700;'>{status}</td>"
            f"<td>{r.get('filename', '')}</td>"
            f"<td>{r.get('shot', '')}</td>"
            f"<td>{r.get('uv_area', '')}</td>"
            f"<td>{r.get('actual_res', '')}</td>"
            f"<td>{r.get('duration', '')}</td>"
            f"<td>{r.get('checked_on', '')}</td>"
            f"<td style='word-break:break-all;font-size:0.8em;'>{r.get('rel_path', '')}</td>"
            f"</tr>"
        )

    rows_joined = "\n".join(rows_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{project}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap');
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{
    background: #000;
    color: #fff;
    font-family: 'Inter', sans-serif;
    margin: 0;
    padding: 2rem;
  }}
  h1 {{
    text-transform: uppercase;
    letter-spacing: 0.3rem;
    font-size: 1.6rem;
    margin-bottom: 0.25rem;
  }}
  .subtitle {{
    color: #888;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.15rem;
    margin-bottom: 2rem;
  }}
  .stats {{
    display: flex;
    gap: 2rem;
    margin-bottom: 2rem;
  }}
  .stat {{
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }}
  .stat-value {{
    font-size: 2rem;
    font-weight: 700;
  }}
  .stat-label {{
    color: #888;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.15rem;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
  }}
  thead th {{
    text-align: left;
    text-transform: uppercase;
    letter-spacing: 0.1rem;
    font-size: 0.7rem;
    color: #888;
    border-bottom: 1px solid #222;
    padding: 0.5rem 0.75rem;
  }}
  tbody tr {{
    border-bottom: 1px solid #111;
  }}
  tbody tr:hover {{
    background: #111;
  }}
  tbody td {{
    padding: 0.5rem 0.75rem;
    vertical-align: top;
  }}
  .pass-rate {{ color: #22c55e; }}
</style>
</head>
<body>
<h1>{project}</h1>
<div class="subtitle">Generated report</div>
<div class="stats">
  <div class="stat">
    <span class="stat-value">{total}</span>
    <span class="stat-label">Total Files</span>
  </div>
  <div class="stat">
    <span class="stat-value" style="color:#22c55e;">{passed}</span>
    <span class="stat-label">Passed</span>
  </div>
  <div class="stat">
    <span class="stat-value" style="color:#ef4444;">{failed}</span>
    <span class="stat-label">Failed</span>
  </div>
  <div class="stat">
    <span class="stat-value" style="color:#f97316;">{errors}</span>
    <span class="stat-label">Errors</span>
  </div>
  <div class="stat">
    <span class="stat-value pass-rate">{pass_rate:.0f}%</span>
    <span class="stat-label">Pass Rate</span>
  </div>
</div>
<table>
  <thead>
    <tr>
      <th>Status</th>
      <th>Filename</th>
      <th>Shot</th>
      <th>UV</th>
      <th>Resolution</th>
      <th>Duration</th>
      <th>Checked On</th>
      <th>Path</th>
    </tr>
  </thead>
  <tbody>
{rows_joined}
  </tbody>
</table>
</body>
</html>
"""
