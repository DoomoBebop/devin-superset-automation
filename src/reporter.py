"""
Observability reporter — reads metrics JSON and generates an HTML dashboard.
Run: python reporter.py --metrics /tmp/devin_metrics.json --out report.html
"""

import json
import argparse
from datetime import datetime
from pathlib import Path


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Devin Automation — Superset Remediation Report</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #0d1117; color: #e6edf3; }}
  h1 {{ color: #58a6ff; }}
  .summary {{ display: flex; gap: 1rem; margin: 1.5rem 0; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 1rem 1.5rem; min-width: 120px; }}
  .card .num {{ font-size: 2rem; font-weight: bold; }}
  .card .label {{ color: #8b949e; font-size: 0.85rem; }}
  .success .num {{ color: #3fb950; }}
  .failed .num {{ color: #f85149; }}
  .running .num {{ color: #d29922; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 1.5rem; }}
  th {{ text-align: left; padding: 0.6rem 1rem; background: #161b22; color: #8b949e; font-size: 0.8rem; text-transform: uppercase; }}
  td {{ padding: 0.75rem 1rem; border-top: 1px solid #21262d; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.78rem; font-weight: 600; }}
  .badge-success {{ background: #1a4a2e; color: #3fb950; }}
  .badge-failed {{ background: #4a1a1a; color: #f85149; }}
  .badge-running {{ background: #3d2f00; color: #d29922; }}
  .badge-pending {{ background: #1c2128; color: #8b949e; }}
  a {{ color: #58a6ff; }}
  .ts {{ color: #8b949e; font-size: 0.8rem; }}
  .footer {{ margin-top: 3rem; color: #484f58; font-size: 0.8rem; }}
</style>
</head>
<body>
<h1>🤖 Devin Automation — Superset Remediation</h1>
<p class="ts">Generated: {generated_at} | Repo: {repo}</p>

<div class="summary">
  <div class="card"><div class="num">{total}</div><div class="label">Total Issues</div></div>
  <div class="card success"><div class="num">{success}</div><div class="label">Success</div></div>
  <div class="card failed"><div class="num">{failed}</div><div class="label">Failed</div></div>
  <div class="card running"><div class="num">{running}</div><div class="label">Running</div></div>
</div>

<table>
  <thead>
    <tr>
      <th>#</th>
      <th>Issue</th>
      <th>Status</th>
      <th>Session ID</th>
      <th>Pull Request</th>
      <th>Started</th>
      <th>Finished</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>

<div class="footer">Devin Superset Automation — Nathan Raffy</div>
</body>
</html>"""

ROW_TEMPLATE = """<tr>
  <td>#{issue_number}</td>
  <td>{issue_title}</td>
  <td><span class="badge badge-{status}">{status}</span></td>
  <td><code>{session_id}</code></td>
  <td>{pr_link}</td>
  <td class="ts">{started_at}</td>
  <td class="ts">{finished_at}</td>
</tr>"""


def generate_report(metrics_path: str, out_path: str, repo: str):
    data = {}
    if Path(metrics_path).exists():
        with open(metrics_path) as f:
            data = json.load(f)

    tasks = list(data.values())
    total = len(tasks)
    success = sum(1 for t in tasks if t["status"] == "success")
    failed = sum(1 for t in tasks if t["status"] == "failed")
    running = sum(1 for t in tasks if t["status"] == "running")

    rows = []
    for t in tasks:
        pr_url = t.get("pr_url")
        pr_link = f'<a href="{pr_url}" target="_blank">View PR</a>' if pr_url else "—"
        session_id = t.get("session_id") or "—"
        rows.append(ROW_TEMPLATE.format(
            issue_number=t["issue_number"],
            issue_title=t["issue_title"],
            status=t["status"],
            session_id=session_id[:16] + "..." if len(session_id) > 16 else session_id,
            pr_link=pr_link,
            started_at=t.get("started_at") or "—",
            finished_at=t.get("finished_at") or "—",
        ))

    html = HTML_TEMPLATE.format(
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        repo=repo,
        total=total,
        success=success,
        failed=failed,
        running=running,
        rows="\n".join(rows) if rows else "<tr><td colspan='7'>No tasks yet.</td></tr>",
    )

    with open(out_path, "w") as f:
        f.write(html)
    print(f"Report saved: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", default="/tmp/devin_metrics.json")
    parser.add_argument("--out", default="report.html")
    parser.add_argument("--repo", default="DoomoBebop/superset-interview")
    args = parser.parse_args()
    generate_report(args.metrics, args.out, args.repo)
