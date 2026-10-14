# Team testing deployment — free hosting

Status (14 October 2026): Render is connected to the application repositories.
Backend commit `7c2edd7` and frontend commit `3fbc015` have been pushed.
The separate Supabase Free project `pharmacy-erp-testing` is healthy, and its
private `erp_app` schema contains 565 suppliers, 6,740 medicines and 6,805
reference-stock records, transferred with explicit user approval. Saleable
medicine stock starts at zero. No customers, prescriptions, sales, original
employee credentials or original sync sessions were copied.

A separate test administrator login is stored in `.env.hosting.local` under
`STAGING_LOGIN_EMAIL` and `STAGING_LOGIN_PASSWORD`. Never commit this file.
No Render service has been published yet; hosted access and sync still require
deployment and verification. The prepared Render backend form uses Free,
Docker, Singapore, `/health`, and automatic deployment on commits. Its database
connection still needs to be added, followed by the frontend and exact CORS URL.

Testing project reference: `wizlnubijmsjbolfxxox` (Sydney). Its session pooler is
`aws-0-ap-southeast-2.pooler.supabase.com:5432`, database `postgres`, user
`postgres.wizlnubijmsjbolfxxox`. Enter its database password only in the private,
Git-ignored `.env.hosting.local` file. This file is for setup tooling, not the
running local app; never replace the local `.env` with staging settings.

## Proposed setup

- Render Static Site: React UI, built from `vijaysoni9097-stack/erp`.
- Render Free Web Service: FastAPI from `vijaysoni9097-stack/erp-backend`.
- A separate Supabase Free project: durable testing database and sync environment.
- Automatic deployment from the selected Git branch after each push.

Free Render services sleep after 15 minutes without traffic and take roughly a
minute to wake. Their SQLite files do not survive restarts. Do not deploy the
current SQLite database there. Free Render Postgres expires after 30 days, so it
is not the proposed durable database. Supabase Free projects have quotas and can
pause when inactive. Do not enable paid plans or paid overages for this setup.

## Prepared changes

- Frontend accepts `VITE_API_BASE_URL` ending in `/api/v1`; local development
  continues using the Vite proxy when unset.
- Backend accepts `CORS_ORIGINS` as a JSON list of exact approved frontend URLs.
- Container build excludes `.env`, SQLite files, backups and import exports.
- PostgreSQL startup uses a separate `erp_app` schema. `REQUIRE_POSTGRES=true`
  prevents accidental use of an ephemeral SQLite database on the hosted service.
- Stock writes and cloud stock application share a PostgreSQL transaction lock.
- `render.yaml` defines the free API and static UI, using existing backend `main`
  and frontend `feature/ui_0.2` branches, with automatic deployment on pushes.
- PostgreSQL smoke checks passed on an isolated local PostgreSQL 17 container:
  initial startup, restart/login, protected APIs, CORS, employee IDs, and competing
  sales without overselling. All 27 existing SQLite tests also passed.
- Vercel configuration exists as an alternative but is not the selected free host.

## Required before publication

1. Connect Render and GitHub, selecting only the two application repositories.
2. Create a separate free Supabase testing project; do not reuse the live pharmacy
   device identity, session data, employee credentials or sync outbox.
3. Initialize the testing database and import the approved catalog/stock data.
   PostgreSQL startup and concurrent sales are verified; hosted data import and
   end-to-end cloud sync still need verification against the separate project.
4. Provision test users and a separate sync device. Seed approved catalog and
   inventory test data without copying patient records or live sessions.
5. Deploy the backend with its database connection and device secrets in backend
   environment settings only. Never put these in VITE variables or Git.
6. Build UI with `npm ci && npm run build`, publish `dist`, set
   `VITE_API_BASE_URL=https://<backend-host>/api/v1` and rewrite `/*` to
   `/index.html`. Use Node 22.12 or newer in the 22.x series.
7. Configure the exact UI origin on the backend. Connect automatic deployments
   to the selected branch in each repository.
8. Verify login, role access, medicines, stock, uploads, conflict handling and
   database persistence across redeploys before sharing the URL.

The Dockerfile defaults to SQLite for local use; `render.yaml` overrides this
with a required PostgreSQL connection. Do not remove `REQUIRE_POSTGRES=true`
from the hosted configuration. Use a Supabase session-pooler connection with
TLS. Keep `erp_app` out of the exposed Supabase API schemas. Cloud sync stays
disabled until the testing pharmacy, user and device are enrolled.

Render Free blocks SMTP ports: password-recovery email will need an HTTPS email
provider adapter before that workflow is available online. Login itself does
not need SMTP. No hosted link or real cloud integration has been verified yet.

References:
- https://render.com/docs/free
- https://render.com/docs/deploys
- https://supabase.com/pricing
