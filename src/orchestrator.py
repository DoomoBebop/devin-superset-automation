"""
Devin Superset Automation - Orchestrator (Devin API v3)
Event-driven: GitHub issue → Devin session → PR + observability
"""

import os, time, logging, json, urllib.request, urllib.error
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict
import re

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DEVIN_TOKEN  = os.environ["DEVIN_API_KEY"]
DEVIN_ORG_ID = os.environ["DEVIN_ORG_ID"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "DoomoBebop/superset-interview")

DEVIN_BASE  = f"https://api.devin.ai/v3/organizations/{DEVIN_ORG_ID}"
GITHUB_BASE = "https://api.github.com"


@dataclass
class TaskResult:
    issue_number: int
    issue_title: str
    session_id:   Optional[str] = None
    session_url:  Optional[str] = None
    status:       str = "pending"   # pending | running | success | failed
    pr_url:       Optional[str] = None
    started_at:   Optional[str] = None
    finished_at:  Optional[str] = None
    error:        Optional[str] = None
    logs:         list = field(default_factory=list)


_results: dict[int, TaskResult] = {}

def _save():
    path = os.environ.get("METRICS_PATH", "/tmp/devin_metrics.json")
    with open(path, "w") as f:
        json.dump({k: asdict(v) for k, v in _results.items()}, f, indent=2)


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _gh(method, path, body=None):
    url = f"{GITHUB_BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.github+json",
    })
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())

def _devin(method, path, body=None):
    url = f"{DEVIN_BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {DEVIN_TOKEN}",
        "Content-Type": "application/json",
    })
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


# ── GitHub helpers ─────────────────────────────────────────────────────────────

def get_open_issues(label=None):
    params = "state=open&per_page=50"
    if label:
        params += f"&labels={label}"
    return _gh("GET", f"/repos/{GITHUB_REPO}/issues?{params}")

def comment(issue_number, body):
    try:
        _gh("POST", f"/repos/{GITHUB_REPO}/issues/{issue_number}/comments", {"body": body})
    except Exception as e:
        log.warning(f"Comment failed: {e}")

def close_issue(issue_number):
    try:
        _gh("PATCH", f"/repos/{GITHUB_REPO}/issues/{issue_number}", {"state": "closed"})
    except Exception as e:
        log.warning(f"Close issue failed: {e}")


# ── Devin helpers ──────────────────────────────────────────────────────────────

def create_session(issue: dict) -> dict:
    n, title, body = issue["number"], issue["title"], issue.get("body", "")
    prompt = f"""You are working on the GitHub repository https://github.com/{GITHUB_REPO}.

Issue #{n}: {title}

{body}

Your task:
1. Implement the remediation described above
2. Create a pull request titled: "fix: {title} (closes #{n})"
3. The PR description must reference: "Closes #{n}"

Focus on correctness. Do not change unrelated code."""

    resp = _devin("POST", "/sessions", {
        "prompt": prompt,
        "idempotent_id": f"superset-issue-{n}-{int(time.time())}",
    })
    return resp   # contains session_id, url, status, etc.

def get_session(session_id: str) -> dict:
    return _devin("GET", f"/sessions/{session_id}")

def poll_session(session_id: str, timeout_min=45) -> dict:
    deadline = time.time() + timeout_min * 60
    while time.time() < deadline:
        data = get_session(session_id)
        status = data.get("status", "")
        log.info(f"  [{session_id[:16]}] status={status}")
        if status in ("finished", "failed", "stopped", "blocked", "suspended"):
            return data
        time.sleep(20)
    return {"status": "timeout", "session_id": session_id}

def extract_pr(session_data: dict) -> Optional[str]:
    text = json.dumps(session_data)
    m = re.search(r"https://github\.com/[^\s\"]+/pull/\d+", text)
    return m.group(0) if m else None


# ── Core workflow ──────────────────────────────────────────────────────────────

def remediate_issue(issue: dict) -> TaskResult:
    n, title = issue["number"], issue["title"]
    result = TaskResult(issue_number=n, issue_title=title,
                        started_at=datetime.utcnow().isoformat())
    _results[n] = result

    log.info(f"▶ Issue #{n}: {title}")
    comment(n, "🤖 **Devin automation triggered.** Starting remediation session...")

    try:
        sess = create_session(issue)
        session_id  = sess["session_id"]
        session_url = sess.get("url", "")
        result.session_id  = session_id
        result.session_url = session_url
        result.status      = "running"
        result.logs.append(f"Session: {session_id}")
        _save()

        log.info(f"  Session: {session_url}")
        comment(n, f"🔄 Devin session started: {session_url}")

        data = poll_session(session_id)
        result.finished_at = datetime.utcnow().isoformat()

        pr_url = extract_pr(data)
        result.pr_url = pr_url

        if data.get("status") == "finished":
            result.status = "success"
            msg = f"✅ **Devin completed remediation.**\n\nSession: {session_url}\n"
            if pr_url:
                msg += f"Pull request: {pr_url}"
                close_issue(n)
            comment(n, msg)
        else:
            result.status = "failed"
            result.error  = f"Session ended: {data.get('status')}"
            comment(n, f"❌ Session ended with status `{data.get('status')}`. See: {session_url}")

    except Exception as e:
        result.status      = "failed"
        result.error       = str(e)
        result.finished_at = datetime.utcnow().isoformat()
        log.error(f"[#{n}] {e}")
        comment(n, f"❌ Automation error: `{e}`")

    _results[n] = result
    _save()
    log.info(f"✔ #{n} → {result.status} | PR: {result.pr_url}")
    return result


def run_all(label=None):
    issues = get_open_issues(label)
    log.info(f"Found {len(issues)} open issues")
    for issue in issues:
        remediate_issue(issue)
        time.sleep(5)
    _print_summary()

def _print_summary():
    total   = len(_results)
    success = sum(1 for r in _results.values() if r.status == "success")
    failed  = sum(1 for r in _results.values() if r.status == "failed")
    log.info(f"\n{'='*60}\nSUMMARY: {total} total | {success} success | {failed} failed")
    for r in _results.values():
        icon = "✅" if r.status == "success" else "❌"
        log.info(f"  {icon} #{r.issue_number} {r.issue_title[:50]} | {r.pr_url or 'no PR'}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--label", default=None)
    p.add_argument("--issue", type=int, default=None)
    args = p.parse_args()

    if args.issue:
        issues = get_open_issues()
        target = next((i for i in issues if i["number"] == args.issue), None)
        if target:
            remediate_issue(target)
        else:
            log.error(f"Issue #{args.issue} not found")
    else:
        run_all(label=args.label)
