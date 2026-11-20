# Safe Spot AI

[Open the live demo](https://safespot-web.kindpond-88c41bc7.uksouth.azurecontainerapps.io).

Safe Spot is a health, safety, and environment (HSE) application that uses AI to turn safety concerns into action.
It helps teams create safer environments through simple reporting, informed decisions, and a clear record of action.

From the first report to risk control and case closure, Safe Spot connects reporters, case handlers, field officers, and managers.
People review the evidence and approve each critical decision.

## Features

- **Simple incident reporting.** Guided steps help people explain what happened, identify the location, and add photos without technical knowledge.
- **Voice input.** Reporters can speak their description in supported browsers, then check and edit the text.
- **Photo analysis.** Reporters can add photos on the first page and request AI observations with separate consent. They check observations before use.
- **Transcript review.** Reporters can see interim speech and retain the original transcript separately from edited report text.
- **Assignment recommendations.** AI can suggest a department. Capacity rules compare available officers, and staff approve the assignment.
- **Capacity management.** Managers can change officer departments, availability, and case limits. The application records each change.
- **AI assistance.** GPT-5-mini on Azure extracts report details, suggests categories and priorities, and prepares outcome responses and manager summaries.
- **Human approval.** Staff approve assignments, field findings, risk control, outcome responses, and closure. Changes cancel affected approvals.
- **Report tracking.** One short reference lets reporters check progress without a staff account.
- **Case management.** Handlers can filter reports by status, priority, officer, location, deadline, and reporter age group.
- **Field operations.** Assigned officers can record inspection findings, attach evidence, record required assistance, and confirm risk control.
- **Manager dashboards.** Counts, progress charts, location groups, and risk control times help managers identify work that needs attention.
- **Recurring incident review.** Staff can link recurring incidents or multiple reports about one event while retaining each report.
- **Alerts and reporting deadlines.** Scheduled checks flag overdue risk control and confirmed recurring incidents. Staff can record RIDDOR reporting decisions and dates.
- **Private evidence and decision history.** Staff permissions protect case records and images. The application records who approved each action and when.

AI features require a connected model service.
Manual reporting and case management remain available without AI.
Photo analysis requires a model deployment that accepts images.
Speech input uses browser speech recognition and does not require a new model download.
Assignment capacity uses active case counts as an approximation, rather than estimated work hours.
Approval checks availability and capacity again before saving the assignment.

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

Open [Safe Spot Locally](http://127.0.0.1:8000).
Open [Safe Spot](https://safespot-web.kindpond-88c41bc7.uksouth.azurecontainerapps.io).
Demo staff accounts are saved in `.local/demo-accounts.txt`.
All three demo accounts use `password`.
Use `field@gmail.com`, `case@gmail.com`, or `manager@gmail.com` to sign in.
Staff notifications use the corresponding `functionzy+field`, `functionzy+case`, and `functionzy+manager` Gmail addresses.
The seed command also creates fictional officers and capacity profiles for Facilities, Security, and Health and Safety.
Their demonstration login addresses use `example.test` and the password `password`.
Managers can inspect and change capacity through the dashboard.

Local deployments use SQLite and local image storage.
Configure the model and email connections through the environment variables in [.env.example](.env.example).
The server reads exported environment variables; it does not load `.env` automatically.
Email remains in the application outbox until Zoho ZeptoMail or SMTP delivery is enabled.

### Deploy to Azure

Follow the [Azure deployment guide](infra/README.md) for setup, deployment, staff accounts, and updates.
