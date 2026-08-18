# Production Deployment

This application uses Railway PostgreSQL and Alembic migrations. Railway runs the schema migration before starting the web process through `railway.toml`.

## Required Railway variables

```text
APP_ENV=production
STUDY_VERSION=1.0.0
DATABASE_URL=<Railway PostgreSQL connection URL>
ADMIN_SECRET_KEY=<long random secret>
ADMIN_API_KEY=<different long random secret>
OPENAI_API_KEY=<OpenAI API key>
OPENAI_MODEL=gpt-4.1-mini
PROLIFIC_COMPLETION_CODE=<Prolific completion code>
```

Set `PROLIFIC_COMPLETION_URL` instead of `PROLIFIC_COMPLETION_CODE` only when Prolific provides a complete redirect URL. Do not use any `your-...` or `change-this-...` values in production.

## Release procedure

1. Back up the Railway PostgreSQL database before applying a new migration.
2. Deploy the application. Railway runs `flask --app app db upgrade` before starting Gunicorn.
3. Confirm `GET /healthz` returns `{"status":"ok"}`.
4. Complete one pilot Prolific session and verify the final and initial-evaluation CSV exports.

## Prolific launch checklist

1. Set the published study URL as `https://<your-domain>/?PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}`.
2. Add the real completion code as `PROLIFIC_COMPLETION_CODE` in Railway. Do not place it in source control.
3. Test with a distinct pilot Prolific ID in the query string. The completion page must show the `RETURN TO PROLIFIC` button only after all study data has been saved.
4. Verify the participant's `prolific_pid`, `prolific_study_id`, `prolific_session_id`, four trials, recall responses, and final questionnaire in the CSV export.
5. Rotate any API key or secret that has been pasted into chat, a screenshot, or another shared location, then update its Railway variable.

Never edit a production table manually. Create a new Alembic migration for every schema change and test the upgrade against a copy of the database before deployment.