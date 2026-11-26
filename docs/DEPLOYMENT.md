# Deployment and operations guide

> Hosting on Render? Follow `docs/RENDER.md` (blueprint, step by step). This guide describes the same components in general.

No Docker is used. This guide assumes Linux hosts (or any platform that can run Python processes), a managed PostgreSQL (Neon),
a managed Redis, Cloudflare R2, and a TLS-terminating reverse proxy or load balancer.

## 1. Components

| Process | Command | Notes |
|---|---|---|
| Web + WebSocket (ASGI) | `daphne -b 0.0.0.0 -p 8000 config.asgi:application` (or `uvicorn config.asgi:application --workers 4`) | Serves REST and `/ws/staff/`. Run several instances behind the proxy. |
| Worker | `celery -A config worker -l info --concurrency 4` | Email, backups, payment reconciliation. |
| Scheduler | `celery -A config beat -l info` | **Exactly one instance.** Schedule lives in `CELERY_BEAT_SCHEDULE` (payment reconcile every 5 min; backup 02:00 UTC; prune 03:00; weekly verify). |
| Frontend | `npm ci && npm run build`, serve `frontend/dist` from a CDN or static host | Single-page app; route every path to `index.html`. |

`DJANGO_SETTINGS_MODULE=config.settings.prod` for all Python processes. Production settings refuse to start without Redis, a long secret key,
Brevo email and Monime payments configuration.

## 2. Domains and routing

* Platform host: `PLATFORM_DOMAIN` (e.g. `example.com`), also listed in `PLATFORM_HOSTS`. Marketing site and `/admin`.
* Each restaurant: `https://example.com/<slug>` (no wildcard DNS or certificate needed) or a verified custom domain.
* The proxy must pass the original `Host` header unchanged (tenant resolution depends on it), set `X-Forwarded-Proto: https`, and forward WebSocket upgrades for `/ws/`.
* Set the proxy idle timeout for WebSockets above 60 s (the server pings every 25 s).
* `ALLOWED_HOSTS` must list the platform domain (and any custom domains); never `*`.
* Trust `X-Forwarded-For` only from your own proxy (rate limits and audit IPs use it).

## 3. Environment variables (names only; never commit values)

Core: `DJANGO_SETTINGS_MODULE`, `DJANGO_SECRET_KEY` (50+ random characters), `PLATFORM_DOMAIN`, `PLATFORM_HOSTS`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`.
Data: `DATABASE_URL` (Neon **pooled** string), `DIRECT_DATABASE_URL` (for migrations), `DB_CONN_MAX_AGE`, `REDIS_URL`.
Email: `EMAIL_PROVIDER=brevo`, `BREVO_API_KEY`, `BREVO_SENDER_EMAIL`, `BREVO_SENDER_NAME`.
Payments: `PAYMENT_PROVIDER=monime`, `MONIME_ACCESS_TOKEN`, `MONIME_SPACE_ID`, `MONIME_BASE_URL`, `MONIME_WEBHOOK_SECRET` (`MONIME_API_KEY` is still accepted as an older name for the access token).
Backups: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` (optionally `R2_ENDPOINT_URL`), `BACKUP_ENCRYPTION_KEY` (a Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`; store it in a secret manager **separately from the backups**: without it every backup is unreadable), `BACKUP_RETAIN_DAYS`, `BACKUP_KEEP_MIN`.
Security: `MFA_ENFORCEMENT=true` (production refuses to start otherwise), `MFA_REQUIRED_ROLES` (default `restaurant_admin`; platform administrators are always included), `MFA_ENCRYPTION_KEY` (optional Fernet key; defaults to one derived from the secret key), `UPLOAD_SCANNER=clamav`, `CLAMAV_HOST`/`CLAMAV_PORT` or `CLAMAV_SOCKET`, `UPLOAD_SCAN_FAIL_CLOSED=true`. Backups also take `BACKUP_MEDIA_MAX_MB` (uploaded media larger than this is skipped with a warning; use bucket versioning instead).
Other: `GOOGLE_OAUTH_CLIENT_ID`, `PUBLIC_URL_SCHEME=https`, `TERMS_VERSION`, `PRIVACY_VERSION`.

## 4. First deploy

1. Create the Neon database; run `python manage.py migrate` using `DIRECT_DATABASE_URL`.
2. `python manage.py collectstatic --noinput`.
3. Create the first platform administrator with the `create_platform_admin` command (credentials via environment variables, not arguments).
4. Start web, worker and beat.
5. **Run `python manage.py preflight`** in the production environment. Every line must be PASS (add `--strict` to fail on warnings).
6. Sign in to `/admin` → **System**: all checks should be Healthy, take a first backup and press **Verify**.
7. Register a test restaurant, place a test order, check the payment webhook reaches `/api/v1/payments/webhooks/...`.

### Components added later
* **ClamAV:** run `clamd` (package `clamav-daemon`) reachable from the web processes; keep signatures fresh with `freshclam`. `preflight` and the System page check it.
* **Two-factor onboarding:** the first platform administrator signs in, is sent to the enrolment screen, and scans the QR code. Keep the recovery codes offline. A lost authenticator is reset by another platform administrator (staff) or by an operator with `python manage.py mfa_reset <email>`.
* **Time zones:** set each restaurant's time zone under Website content, Operations (default UTC). Reports, "today" and reservation times follow it.

## 5. Routine releases

1. Deploy code, run `migrate` (migrations are additive; deploy code that tolerates both schemas when removing columns).
2. Restart web workers one at a time; restart the Celery worker (`acks_late` means in-flight tasks are retried); restart beat once.
3. Re-run `preflight`. Watch **System** for ten minutes.

## 6. Backups and recovery

* Backups are encrypted logical dumps of the platform database in R2, daily at 02:00 UTC, verified weekly. Uploaded media (logos, product and gallery photos, avatars) is saved as a second encrypted archive with each backup (up to `BACKUP_MEDIA_MAX_MB`); restore it with `restore_backup <id> --apply --confirm <id> --media`.
* For large databases rely on Neon point-in-time recovery as the primary tool; these archives are the application-level safety net.
* **Restore** is available on Admin, System (password + authenticator code + typed phrase, with an automatic verified safety snapshot and maintenance mode: see `docs/RENDER.md`). Disaster recovery into a new empty database by an operator:
  1. Create a NEW empty PostgreSQL database; point `DATABASE_URL` at it; `python manage.py migrate`.
  2. `python manage.py restore_backup --list`, choose the newest key.
  3. `python manage.py restore_backup --key <key>` (verifies it decrypts and parses).
  4. `python manage.py restore_backup --key <key> --apply --confirm RESTORE` (refuses unless the database is empty; atomic).
  5. Run `preflight`, switch traffic, then rotate secrets if the incident involved a leak.
* Practise this on a staging database each quarter. Restoring has only been rehearsed on SQLite so far.

## 7. Monitoring

* `GET /healthz` (liveness) and `GET /readyz` (database and cache; 503 when degraded) for load balancer probes.
* `/admin` → **System** for platform administrators: database latency, cache, broker, channel layer, backup freshness and verification, migrations, email failures, stuck or mismatched payments.
* Alert externally on: `/readyz` failing, no successful backup for 26 h (System shows critical), growing `failed` emails, payments with `mismatch` status (needs a human), and worker/beat processes not running (the app cannot see a dead beat: monitor the process).
* Logs are structured JSON on stdout; ship them to your log service. Bodies of emails, passwords, tokens and card data are never logged.

## 8. Capacity and load verification (do this on staging before launch)

* `python manage.py concurrency_check --threads 20 --i-understand-this-writes-test-data` on a staging PostgreSQL database proves stock cannot be oversold and idempotency holds under parallel requests. It has only been run on SQLite (which serialises writers), so **row locking is unproven on PostgreSQL until you run it there**. It creates a suspended `ZZ concurrency-check` restaurant that cannot be deleted; never run it on production.
* Use a load tool (k6, Locust) against staging for the public menu, checkout, and staff order list. The test-suite enforces query budgets (counts must not grow with data) and a 3,000-order report smoke test, but those are not throughput numbers.
* Redis: confirm rate limiting (`429`) and the channel layer across two web processes (a staff screen on process A must receive an event caused on process B).

## 9. Security checklist

* `python manage.py check --deploy` reports no Django security warnings with the production settings (drf-spectacular schema warnings about untyped API views are cosmetic).
* Rotate `DJANGO_SECRET_KEY` only with a planned logout of all users (JWT signing uses it). Staff deactivation, password change and "sign out everywhere" revoke tokens immediately via the token version.
* Webhooks are verified by signature and treated as hints; the server re-queries the provider.
* See `docs/SECURITY.md` for the verification status and the suggested penetration-test scope. Still not done: an external penetration test (must be commissioned) and real-service verification of ClamAV, Redis, PostgreSQL, R2, Brevo and Monime.
