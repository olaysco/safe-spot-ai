# Safe Spot

Safe Spot is a standalone Python web application for the hackathon.
It uses the selected version 1 interface as its design reference.
It does not use OpenAI Sites.

## Run locally

Use Python 3.13.
Run these commands from the project directory.

```sh
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/python -m app.manage seed
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>.
Read `.local/demo-accounts.txt` for the generated staff accounts.
The seed command preserves existing accounts and records.
Use fictional information for the demonstration.

Local data stays in `.local/safespot.db`.
Evidence images stay in `.local/uploads`.
Account details and local data are excluded from Git.

## Application functions

- Reporters describe an incident through guided steps.
- Reporters choose AI assistance on a separate screen, as in the mockup.
- Reporters check all answers before submission.
- Reporters track progress with a reference and private code.
- Case handlers filter reports and approve assignments.
- Assigned field officers record findings and approve risk control.
- Staff approve the exact outcome before recording it and closing the case.
- Changes cancel affected approvals.
- Managers see counts, progress charts, location groups, deadlines, and notifications.
- Staff confirm recurring incidents or reports about one event.
- Notification records prevent repeated alerts within the same day.

The interface uses JavaScript, HTML, and CSS.
FastAPI serves the interface and API from one origin.
SQLAlchemy supports local SQLite and a shared PostgreSQL database.
The server checks staff roles and record versions.

## AI and email connections

AI is optional.
The manual route remains available when a provider fails or is not configured.
The application does not simulate successful model responses.
The report description supports browser voice input when speech recognition is available.
The browser can send audio to its speech service.
Reporters must check the resulting text.
The application does not use Phi for this voice input.

Copy `.env.example` to `.env` for configuration reference.
The local server reads process environment variables, not `.env` automatically.
Export the required variables before you start the server.
Never commit credentials.

`DECISION_ENDPOINT`, `DECISION_DEPLOYMENT`, and `DECISION_API_KEY` configure Microsoft-Decision-1 triage suggestions.
`TEXT_AI_BASE_URL`, `TEXT_AI_MODEL`, and `TEXT_AI_API_KEY` configure an OpenAI-compatible text service, such as a Phi deployment.
The text service can suggest report details and draft outcome responses or manager summaries.
A live Microsoft model connection has not been verified.

Email uses capture mode by default.
Messages appear in the notification outbox without delivery.
SMTP delivery requires `EMAIL_MODE=smtp` and the SMTP environment variables described in `.env.example`.
An uncertain delivery remains visible for manual review.
The application does not automatically retry uncertain deliveries.

Recurring incident alerts use relationships confirmed by staff.
Automatic AI relationship detection is not implemented.
The manager view shows upcoming deadlines, not a trained incident forecast.
Location groups use report text, not verified map coordinates.

## Checks

```sh
.venv/bin/python -m pytest -q
node --check app/static/app.js
```

Tests cover case approval, role access, tracking privacy, image access, report assistance, and notification records.
Model responses in tests use controlled substitutes.
They do not prove a live provider connection.

## PostgreSQL container setup

Set `POSTGRES_PASSWORD` in `.env` before these commands.
Use a generated password with URL-safe characters.

```sh
docker compose up --build -d
docker compose exec app python -m app.manage seed
docker compose exec app cat .local/demo-accounts.txt
```

The container setup binds to the local computer.
It does not publish a team link.
For hosting, use HTTPS, persistent volumes, PostgreSQL, and one application worker for this version.
Set `PUBLIC_ORIGIN` to the exact hosted origin.
Set `COOKIE_SECURE=true` for HTTPS.
Keep staff access behind sign-in.
The public reporting route can remain available to anyone with the link.

The container setup is supplied but has not been executed in this workspace.
Database schema changes currently require a migration plan before existing shared data can be upgraded.

## Reporting targets

Internal response targets are demonstration settings.
They are not HSE service-level agreements.
Staff decide whether RIDDOR applies and record notification or receipt dates.
The application does not report to HSE.
Use the HSE link in the reporting review screen for current guidance.
