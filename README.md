# Safe Spot

Safe Spot is a health, safety, and environment (HSE) application that uses AI to turn safety concerns into action.
It helps teams create safer environments through simple reporting, informed decisions, and a clear record of action.

From the first report to risk control and case closure, Safe Spot connects reporters, case handlers, field officers, and managers.
People review the evidence and approve each critical decision.

## Features

- **Simple incident reporting.** Guided steps help people explain what happened, identify the location, and add photos without technical knowledge.
- **Voice input.** Reporters can speak their description in supported browsers, then check and edit the text.
- **AI assistance.** Connected models can extract report details, suggest categories and priorities, and prepare outcome responses and manager summaries.
- **Human approval.** Staff approve assignments, field findings, risk control, outcome responses, and closure. Changes cancel affected approvals.
- **Report tracking.** A reference and private tracking code let reporters check progress without a staff account.
- **Case management.** Handlers can filter reports by status, priority, officer, location, deadline, and reporter age group.
- **Field operations.** Assigned officers can record inspection findings, attach evidence, record required assistance, and confirm risk control.
- **Manager dashboards.** Counts, progress charts, location groups, and risk control times help managers identify work that needs attention.
- **Recurring incident review.** Staff can link recurring incidents or multiple reports about one event while retaining each report.
- **Alerts and reporting deadlines.** Scheduled checks flag overdue risk control and confirmed recurring incidents. Staff can record RIDDOR reporting decisions and dates.
- **Private evidence and decision history.** Staff permissions protect case records and images. The application records who approved each action and when.

AI features require a connected model service.
Manual reporting and case management remain available without AI.

## Deployment

### Run locally

Install Python 3.13.
Run these commands from the project directory.

```sh
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/python -m app.manage seed
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [Safe Spot](http://127.0.0.1:8000).
Demo staff accounts are saved in `.local/demo-accounts.txt`.

Local deployments use SQLite and local image storage.
Configure model connections and SMTP through the environment variables in [.env.example](.env.example).
The server reads exported environment variables; it does not load `.env` automatically.
Email remains in the application outbox until SMTP delivery is enabled.

### Deploy to Azure

Follow the [Azure deployment guide](infra/README.md) for setup, deployment, staff accounts, and updates.
