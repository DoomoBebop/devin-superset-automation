# Devin Superset Automation

Event-driven system that uses the **Devin API** to automatically remediate GitHub issues on a fork of Apache Superset.

Built for Cognition take-home — Nathan Raffy

---

## Architecture

```
GitHub Issue (opened/labeled)
        │
        ▼
  Webhook Server (Flask)
        │
        ▼
  Devin Session Created
  (prompt with issue context)
        │
        ▼
  Devin works autonomously:
  - Reads the codebase
  - Implements the fix
  - Opens a Pull Request
        │
        ▼
  Observability Layer
  - Metrics JSON
  - HTML Report
  - /status API endpoint
  - GitHub comments on issue
```

---

## Issues Remediated

| # | Title | Type |
|---|-------|------|
| [#1](https://github.com/DoomoBebop/superset-interview/issues/1) | Security: Upgrade cryptography package (CVE-2023-49083) | Security |
| [#2](https://github.com/DoomoBebop/superset-interview/issues/2) | Security: Upgrade Pillow to >=10.3.0 (CVE-2024-28219) | Security |
| [#3](https://github.com/DoomoBebop/superset-interview/issues/3) | Code quality: Remove unused imports in views/core.py | Code Quality |
| [#4](https://github.com/DoomoBebop/superset-interview/issues/4) | Dependency: Fix Werkzeug 3.x compatibility | Dependency |
| [#5](https://github.com/DoomoBebop/superset-interview/issues/5) | Code quality: Add type hints to db_engine_specs/base.py | Code Quality |

---

## Quick Start

### 1. Clone & configure

```bash
git clone https://github.com/DoomoBebop/devin-superset-automation
cd devin-superset-automation
cp .env.example .env
# Fill in DEVIN_API_KEY and GITHUB_TOKEN
```

### 2. Run webhook server (event-driven mode)

```bash
docker compose up automation
```

The server listens on `http://localhost:8080`.

Configure a GitHub webhook on your fork:
- URL: `http://your-server:8080/webhook`
- Content type: `application/json`
- Events: **Issues**

### 3. Run batch mode (process all open issues at once)

```bash
docker compose --profile batch run batch
# or with label filter:
docker compose --profile batch run batch python src/orchestrator.py --label security
```

### 4. Manual trigger via API

```bash
# Trigger all open issues
curl -X POST http://localhost:8080/trigger/all

# Trigger by label
curl -X POST "http://localhost:8080/trigger/all?label=security"
```

---

## Observability

### Live status endpoint

```bash
curl http://localhost:8080/status
```

Returns:
```json
{
  "summary": {
    "total": 5,
    "success": 3,
    "failed": 1,
    "running": 1,
    "pending": 0
  },
  "tasks": { ... }
}
```

### HTML Report

```bash
python src/reporter.py --metrics data/devin_metrics.json --out report.html
open report.html
```

### Metrics file

All task results are persisted to `data/devin_metrics.json` in real time.

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DEVIN_API_KEY` | Your Devin API key |
| `GITHUB_TOKEN` | GitHub personal access token (repo scope) |
| `GITHUB_REPO` | Target repo e.g. `DoomoBebop/superset-interview` |
| `GITHUB_WEBHOOK_SECRET` | Optional — secret for webhook signature verification |
| `METRICS_PATH` | Path for metrics JSON (default: `/app/data/devin_metrics.json`) |
| `PORT` | Webhook server port (default: `8080`) |

---

## Project Structure

```
├── src/
│   ├── orchestrator.py   # Core workflow: issue → Devin session → PR
│   ├── webhook.py        # Flask server: GitHub webhook → trigger
│   └── reporter.py       # HTML observability dashboard generator
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Why Devin here?

Traditional automation (bots, scripts, Dependabot) handles narrow, well-defined tasks.
Devin handles *ambiguous* remediation — it reads context, understands intent, and produces working code + PRs autonomously.

This system is the bridge: it provides the event trigger, session lifecycle management, and observability layer that makes Devin production-viable for an engineering team.
