"""
Devin Superset Automation - Main Orchestrator
Event-driven system: GitHub webhook → Devin session → PR + observability
"""

import os
import time
import logging
import requests
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

DEVIN_API_BASE = "https://api.devin.ai/v1"
GITHUB_API_BASE = "https://api.github.com"

DEVIN_TOKEN = os.environ["DEVIN_API_KEY"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = os.environ.get("GITHUB_REPO", "DoomoBebop/superset-interview")


@dataclass
class TaskResult:
    issue_number: int
    issue_title: str
    session_id: Optional[str] = None
    status: str = "pending"          # pending | running | success | failed
    pr_url: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    logs: list = field(default_factory=list)


# ── Observability store (in-memory, written to JSON) ──────────────────────────

_results: dict[int, TaskResult] = {}

def _save_results():
    path = os.environ.get("METRICS_PATH", "/tmp/devin_metrics.json")
    with open(path, "w") as f:
        json.dump(
            {k: asdict(v) for k, v in _results.items()},
            f, indent=2
        )
    log.info(f"Metrics saved to {path}")


# ── GitHub helpers ─────────────────────────────────────────────────────────────

def _gh_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.github+json",
    }

def get_open_issues(label: Optional[str] = None) -> list[dict]:
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/issues"
    params = {"state": "open", "per_page": 50}
    if label:
        params["labels"] = label
    resp = requests.get(url, headers=_gh_headers(), params=params)
    resp.raise_for_status()
    return resp.json()

def comment_on_issue(issue_number: int, body: str):
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/issues/{issue_number}/comments"
    requests.post(url, headers=_gh_headers(), json={"body": body})

def close_issue(issue_number: int):
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/issues/{issue_number}"
    requests.patch(url, headers=_gh_headers(), json={"state": "closed"})


# ── Devin API helpers ──────────────────────────────────────────────────────────

def _devin_headers():
    return {
        "Authorization": f"Bearer {DEVIN_TOKEN}",
        "Content-Type": "application/json",
    }

def create_devin_session(issue: dict) -> str:
    """Spin up a Devin session with a precise prompt for the issue."""
    number = issue["number"]
    title = issue["title"]
    body = issue.get("body", "")

    prompt = f"""You are working on the GitHub repository {GITHUB_REPO}.

Issue #{number}: {title}

{body}

Your tasks:
1. Clone the repository (already available in your environment)
2. Implement the remediation described in the issue
3. Write or update tests if applicable
4. Create a pull request with:
   - Title: "fix: {title} (closes #{number})"
   - A clear description of what was changed and why
   - Reference to the issue: "Closes #{number}"

Be pragmatic. Focus on correctness. Do not change unrelated code."""

    payload = {
        "prompt": prompt,
        "idempotent_id": f"superset-issue-{number}-{int(time.time())}",
    }

    resp = requests.post(
        f"{DEVIN_API_BASE}/sessions",
        headers=_devin_headers(),
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    session_id = resp.json()["session_id"]
    log.info(f"[Issue #{number}] Devin session created: {session_id}")
    return session_id

def poll_session(session_id: str, timeout_minutes: int = 30) -> dict:
    """Poll Devin session until terminal state."""
    deadline = time.time() + timeout_minutes * 60
    while time.time() < deadline:
        resp = requests.get(
            f"{DEVIN_API_BASE}/session/{session_id}",
            headers=_devin_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status", "")
        log.info(f"  Session {session_id}: status={status}")

        if status in ("finished", "failed", "stopped", "blocked"):
            return data

        time.sleep(20)

    return {"status": "timeout", "session_id": session_id}

def extract_pr_url(session_data: dict) -> Optional[str]:
    """Try to find a PR URL in session output."""
    output = session_data.get("output", "") or ""
    import re
    matches = re.findall(r"https://github\.com/[^\s]+/pull/\d+", output)
    return matches[0] if matches else None


# ── Core workflow ──────────────────────────────────────────────────────────────

def remediate_issue(issue: dict) -> TaskResult:
    number = issue["number"]
    title = issue["title"]
    result = TaskResult(issue_number=number, issue_title=title)
    result.started_at = datetime.utcnow().isoformat()
    _results[number] = result

    log.info(f"▶ Processing issue #{number}: {title}")
    comment_on_issue(number, "🤖 **Devin automation triggered.** Starting remediation session...")

    try:
        session_id = create_devin_session(issue)
        result.session_id = session_id
        result.status = "running"
        result.logs.append(f"Session created: {session_id}")
        _save_results()

        session_data = poll_session(session_id)
        result.finished_at = datetime.utcnow().isoformat()

        final_status = session_data.get("status", "unknown")
        pr_url = extract_pr_url(session_data)
        result.pr_url = pr_url

        if final_status == "finished":
            result.status = "success"
            msg = f"✅ **Devin completed remediation.**\n\n"
            if pr_url:
                msg += f"Pull request opened: {pr_url}\n"
            msg += f"Session: `{session_id}`"
            comment_on_issue(number, msg)
            if pr_url:
                close_issue(number)
        else:
            result.status = "failed"
            result.error = f"Session ended with status: {final_status}"
            comment_on_issue(number, f"❌ Devin session ended with status `{final_status}`. Session: `{session_id}`")

    except Exception as e:
        result.status = "failed"
        result.error = str(e)
        result.finished_at = datetime.utcnow().isoformat()
        log.error(f"[Issue #{number}] Error: {e}")
        comment_on_issue(number, f"❌ Automation error: `{e}`")

    _results[number] = result
    _save_results()
    log.info(f"✔ Issue #{number} → {result.status} | PR: {result.pr_url}")
    return result


def run_all(label: Optional[str] = None):
    """Fetch all open issues and remediate them sequentially."""
    issues = get_open_issues(label)
    log.info(f"Found {len(issues)} open issues (label={label})")

    for issue in issues:
        remediate_issue(issue)
        time.sleep(5)  # small buffer between sessions

    # Final summary
    print_summary()

def print_summary():
    log.info("\n" + "="*60)
    log.info("REMEDIATION SUMMARY")
    log.info("="*60)
    total = len(_results)
    success = sum(1 for r in _results.values() if r.status == "success")
    failed = sum(1 for r in _results.values() if r.status == "failed")

    for r in _results.values():
        icon = "✅" if r.status == "success" else "❌"
        pr = r.pr_url or "no PR"
        log.info(f"  {icon} #{r.issue_number} {r.issue_title[:50]} | {pr}")

    log.info(f"\nTotal: {total} | Success: {success} | Failed: {failed}")
    log.info("="*60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default=None, help="Filter issues by label")
    parser.add_argument("--issue", type=int, default=None, help="Process a single issue number")
    args = parser.parse_args()

    if args.issue:
        issues = get_open_issues()
        target = next((i for i in issues if i["number"] == args.issue), None)
        if target:
            remediate_issue(target)
        else:
            log.error(f"Issue #{args.issue} not found or not open")
    else:
        run_all(label=args.label)
