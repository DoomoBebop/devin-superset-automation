"""
Webhook server — listens for GitHub issue events and triggers Devin automation.
Event: issues.opened or issues.labeled → launch remediation session.
"""

import os
import hmac
import hashlib
import logging
import threading
from flask import Flask, request, jsonify
from orchestrator import remediate_issue, get_open_issues, _results, print_summary

log = logging.getLogger(__name__)
app = Flask(__name__)

WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
AUTO_LABELS = {"security", "dependencies", "code-quality"}


def verify_signature(payload: bytes, sig_header: str) -> bool:
    if not WEBHOOK_SECRET:
        return True  # dev mode
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig_header)


@app.route("/webhook", methods=["POST"])
def github_webhook():
    payload = request.get_data()
    sig = request.headers.get("X-Hub-Signature-256", "")

    if not verify_signature(payload, sig):
        return jsonify({"error": "Invalid signature"}), 401

    event = request.headers.get("X-GitHub-Event", "")
    data = request.get_json()

    if event == "issues":
        action = data.get("action", "")
        issue = data.get("issue", {})
        labels = [l["name"] for l in issue.get("labels", [])]

        # Trigger on: opened with matching label, or labeled with matching label
        should_trigger = (
            action in ("opened", "labeled") and
            any(l in AUTO_LABELS for l in labels)
        )

        if should_trigger:
            log.info(f"Webhook triggered for issue #{issue['number']}: {issue['title']}")
            # Run async so webhook returns immediately
            t = threading.Thread(target=remediate_issue, args=(issue,), daemon=True)
            t.start()
            return jsonify({"status": "triggered", "issue": issue["number"]}), 202

    return jsonify({"status": "ignored"}), 200


@app.route("/status", methods=["GET"])
def status():
    """Observability endpoint — returns all task statuses."""
    from dataclasses import asdict
    return jsonify({
        "tasks": {k: asdict(v) for k, v in _results.items()},
        "summary": {
            "total": len(_results),
            "success": sum(1 for r in _results.values() if r.status == "success"),
            "failed": sum(1 for r in _results.values() if r.status == "failed"),
            "running": sum(1 for r in _results.values() if r.status == "running"),
            "pending": sum(1 for r in _results.values() if r.status == "pending"),
        }
    })


@app.route("/trigger/all", methods=["POST"])
def trigger_all():
    """Manual trigger — kick off remediation for all open issues."""
    label = request.args.get("label")
    issues = get_open_issues(label=label)
    if not issues:
        return jsonify({"status": "no open issues found"}), 200

    def run():
        import time
        for issue in issues:
            remediate_issue(issue)
            time.sleep(3)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return jsonify({"status": "triggered", "issues": [i["number"] for i in issues]}), 202


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    log.info(f"Starting webhook server on port {port}")
    app.run(host="0.0.0.0", port=port)
