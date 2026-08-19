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
AI_CHAT_RATE_LIMIT=30 per hour
PROLIFIC_COMPLETION_CODE=<Prolific completion code>
```

Set `PROLIFIC_COMPLETION_URL` instead of `PROLIFIC_COMPLETION_CODE` only when Prolific provides a complete redirect URL. Do not use any `your-...` or `change-this-...` values in production.

For stronger shared rate limiting across multiple Railway instances, create a Railway Redis service and set `RATELIMIT_STORAGE_URI` to its private `REDIS_URL` reference. Without it, the application still deploys and limits each instance independently with in-memory storage. The hard cap of five AI responses per profile remains enforced in PostgreSQL in either configuration.

## Release procedure

1. Back up the Railway PostgreSQL database before applying a new migration.
2. Deploy the application. Railway runs `flask --app app db upgrade` before starting Gunicorn. This release is an additive migration; it does not require a PostgreSQL reset.
3. Confirm `GET /healthz` returns `{"status":"ok"}`.
4. Complete one pilot Prolific session and verify the final and initial-evaluation CSV exports.

## Attention-check review

The study uses a fixed, varied sequence of instruction checks across its four trial positions. Participants can continue after an incorrect response so that their data is available for manual review. The CSV exports include the submitted response, expected response, and a `*_correct` value for every pre- and post-evaluation check.

For a Prolific participant, match `prolific_pid` in the export to the Prolific dashboard. The application also stores `prolific_study_id` and `prolific_session_id`; these identify the study and launch session, but the Prolific ID is the value to use when reviewing the participant's submission.

Follow Prolific's current attention-check policy before rejecting a submission. For studies lasting five minutes or more, a participant must fail at least two valid attention checks before rejection. Review and reject submissions manually in the Prolific dashboard; this application does not reject, return, or screen out participants automatically.

## Prolific launch checklist

1. Set the published study URL as `https://<your-domain>/?PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}`.
2. Add the real completion code as `PROLIFIC_COMPLETION_CODE` in Railway. Do not place it in source control.
3. Test with a distinct pilot Prolific ID in the query string. The completion page must show the `RETURN TO PROLIFIC` button only after all study data has been saved. Production rejects sessions not started with all three Prolific query parameters.
4. Verify the participant's `prolific_pid`, `prolific_study_id`, `prolific_session_id`, four trials, recall responses, final questionnaire, and attention-check results in the CSV export.
5. Rotate any API key or secret that has been pasted into chat, a screenshot, or another shared location, then update its Railway variable.

Never edit a production table manually. Create a new Alembic migration for every schema change and test the upgrade against a copy of the database before deployment.