# GameArena infrastructure upgrade

These changes strengthen the existing Flask/Jinja application. They do not replace authentication, Socket.IO, PostgreSQL, Paystack, wallet accounting or the existing page routes. Supabase remains the database provider.

## Code organization

- `gamearena/models.py` and `gamearena/forms.py` contain the existing twenty model and eight form definitions, extracted without field/constraint changes. `app.py` re-exports the same names for existing scripts and tests.
- `gamearena/extensions.py`, `bootstrap.py` and `database.py` separate extension creation and validated startup settings. The bootstrap creates the Flask shell; this is not yet a complete multi-instance application factory. Existing protected routes remain in `app.py`.
- `gamearena/public_api.py` groups the existing public JSON endpoints in a Blueprint. Old URL-building names still work without duplicate URL registrations.
- `gamearena/services/email.py` retains the existing Resend/SMTP transport and logging protections. Provider acceptance does not establish inbox delivery.
- `gamearena/observability.py` records request duration, database duration and query count without request bodies or query strings. Slow requests are logged at warning level; request IDs are sanitized.

## Redis and delivery workers

All integrations are optional and disabled by default. No live services were provisioned.

1. Provision trusted persistent Redis and a separate delivery worker. Use private networking or TLS and access controls. Delivery queues need `noeviction` and persistence; consider separating the expendable cache from queues when load grows.
2. Set `JOB_REDIS_URL` on web and worker. Both need the same database, secret key, email and VAPID configuration. Start `python scripts/run_worker.py`; confirm it is healthy before setting `BACKGROUND_JOBS_ENABLED=true` on web.
3. Jobs carry an account ID, purpose and HMAC token version, or a notification ID. They do not place email addresses, codes or notification bodies in their arguments. JSON serialization avoids pickle payloads. Queue access is still trusted infrastructure.
4. The worker reloads current account codes and expiry, skips superseded/expired/verified codes, and checks current notification preferences. Resend retries use a stable idempotency key. Transient failures retry after 10, 30 and 60 seconds. Queued account email expires after ten minutes; push after five. Failed jobs remain for one hour for investigation.
5. A queue-admission failure uses the existing delivery path. A worker failure after successful admission requires queue monitoring; it does not trigger an unsafe duplicate synchronous send.

Set `CACHE_REDIS_URL` for twenty-second snapshots of successful public tournament/ranking JSON only. HTML, account pages, chat and financial endpoints are excluded. Redis cache outages fall back to database queries. Authenticated responses retain `private, no-store`.

Set `SOCKET_RATE_LIMIT_REDIS_URL` to enforce atomic per-account sliding windows across connections/instances. The existing database-backed HTTP limiter remains. When the configured Redis limiter fails, socket mutations fail closed. Set a distinct `CACHE_NAMESPACE` per environment. Keep `SOCKETIO_MESSAGE_QUEUE` for cross-instance room broadcasts, with sticky routing and the same secret. Do not increase Gunicorn workers arbitrarily or claim scale readiness before load testing.

Reference: [RQ](https://python-rq.org/docs/), [Socket.IO deployment](https://flask-socketio.readthedocs.io/en/stable/deployment.html).

## Database and migrations

`DATABASE_POOL_MODE=null` preserves the existing gevent-compatible default, with a bounded connection timeout. An optional bounded `queue` pool supports pre-ping, size, overflow, timeout and recycle settings. Do not enable it in production until tested under the actual Gunicorn/gevent deployment and Supabase connection budget. Pooling is not a substitute for measuring slow queries or geographic latency.

The new release command is `python scripts/migrate.py`. It runs existing additive migrations and an Alembic revision which verifies the recorded legacy history before baselining. It does not rename business tables or rewrite financial records. Incomplete history is refused. Baseline downgrades are deliberately refused. Both migration phases use an advisory lock to serialize concurrent migration processes. App imports do not run this release command.

Use `MIGRATION_DATABASE_URL` if migrations need a direct/session Supabase connection rather than the runtime pooler. Keep the same actual database. Future explicit revisions go in `migrations/versions`; automatic model-to-schema generation is not configured. Back up the production database and review future revisions before applying them.

Reference: [Supabase connections](https://supabase.com/docs/guides/database/connecting-to-postgres), [Alembic](https://alembic.sqlalchemy.org/en/latest/).

## Frontend and responsive checks

The carousel has a strictly checked TypeScript source at `frontend/carousels.ts`. Vite builds the carousel and existing Tailwind/app/theme styles into fingerprinted assets; Jinja reads the build manifest. No React migration is introduced. Other scripts retain JavaScript for gradual adoption. The existing unbuilt files remain the fallback if assets are absent. Bundled and fallback carousel behavior must stay aligned when editing either source.

Use Node 22.12+ and the pinned pnpm version: `pnpm install --frozen-lockfile`, then `pnpm build`. The lockfile and explicit esbuild build permission make installs repeatable. Build artifacts are ignored by Git and must be generated during deployment or packaged with a release. Successful manifest assets receive immutable cache headers.

`.github/workflows/checks.yml` runs PostgreSQL backend checks and builds assets, then starts a separate loopback preview and runs browser tests at 360, 390, 768 and 1440 pixels. Browser fixtures use synthetic accounts and do not make payments or submit withdrawals. Mobile projects use WebKit. Browser tests and this remote CI workflow have not been executed during this task; their presence is not proof of passing UI checks.

`scripts/benchmark_local.py` refuses remote databases and reports local backend p50/p95 measurements. These exclude browser rendering, network latency, cold starts and live Paystack/Resend time. They establish no before/after improvement or production SLA.

## Hosting, Storage and Cloudflare

`render.yaml` now takes `DATABASE_URL` externally instead of provisioning an unrelated Render database. Automatic deployment is disabled in the repository template. This does not change the existing Render dashboard settings or service tier. The start command now selects the documented gevent-websocket Gunicorn worker with one process to support WebSocket upgrades. This Linux deployment command has not been executed locally. The current minimal build uses the working unbuilt frontend fallback; to deploy compiled assets, use a Node-capable build environment and run the pnpm build commands after Python dependencies install.

`ops/render-worker.example.yaml` is a reviewed-source template for billed Redis and worker resources, not an applied deployment. Upgrade the existing web service to an appropriate always-on tier separately after budget approval and profiling. No payment secrets are needed by the delivery worker. Live provider failures and multi-instance capacity remain unverified.

`ops/supabase-avatars.sql` prepares a public-read avatar bucket with WebP-only uploads and a size limit, while leaving existing buckets unchanged. Apply only to the existing Supabase project when ready. Uploads remain server-side; do not expose the service-role key. Set `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` and `SUPABASE_AVATAR_BUCKET` on web. Until then the existing bounded PostgreSQL/persistent storage fallback remains. No bucket or storage policy was changed live.

`ops/cloudflare-static-cache-rule.json` is a static-assets-only rule respecting origin cache controls, excluding the service worker and manifest. It is not installed in Cloudflare. Do not replace all zone rules or enable blanket caching of authenticated/financial pages.

Reference: [Render limitations](https://render.com/docs/free), [Cloudflare cache settings](https://developers.cloudflare.com/cache/how-to/cache-rules/settings/), [Supabase Storage](https://supabase.com/docs/guides/storage/buckets/creating-buckets).

## Release boundaries

No push, deployment, production schema change, paid provisioning, secret modification or live financial transaction was performed. The live application will not gain these infrastructure features merely from local file changes. Dependency installation, reviewed deployment configuration and explicit activation are required. Browser screenshots and live delivery/payment confirmation remain outstanding.

## Recorded local validation

- Full isolated PostgreSQL regression suite: 127 passed, 108 warnings, 606.47 seconds. Existing datetime/SQLAlchemy deprecation warnings remain.
- Final targeted infrastructure/migration checks after hardening: 19 passed, 9 warnings. This includes JSON queue execution, deduplication, stale-token suppression, cache outage fallback, private response headers, atomic Lua limits, local queue-pool reuse and repeatable baseline preservation.
- TypeScript checks and Vite production build passed: carousel JS 2.15 KB / 0.90 KB gzip; bundled styles 57.43 KB / 12.17 KB gzip.
- Model/form AST comparison confirmed all twenty models and eight forms unchanged.
- Python compilation, JavaScript syntax, dependency consistency and whitespace checks passed.
- Redis behavior was tested with fakeredis/Lua, not a production Redis service. Production persistence, horizontal routing, worker monitoring and load capacity remain unverified.
- Browser control timed out again. Responsive browser tests, fresh screenshots and the remote GitHub workflow were authored but not run.
- Local response measurements are in `docs/validation/stack-local-latency.json`; they are current measurements, not evidence of a speed improvement.

Modified-file groups: `app.py` and `gamearena/` (modular backend and infrastructure); `db_migrate.py`, `alembic.ini`, `migrations/`, `scripts/migrate.py` (migration baseline); `frontend/`, package/build configuration, `_design_assets.html` (typed assets and fallback); requirements/environment examples (optional dependencies); hosting files and `ops/` (reviewable configuration); tests/workflow/benchmark and validation docs (verification).
