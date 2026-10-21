# Performance operations

The Blueprint enables automatic deployment on commits to the linked branch. Verify Render Settings > Build & Deploy > Auto-Deploy reads On Commit after syncing the Blueprint. It retains the free compute plan until the owner upgrades the web service.

## Owner hosting step

Open the gamearena web service > Compute > Edit. Select the $7/month 0.5 CPU / 512 MB instance, review the amount, and save. Upgrade the web service, not the separate database or workspace subscription. Paid compute removes free-tier idle spin-down. Check actual dashboard pricing before accepting.

## Cloudflare

Public /static/ assets already send public cache headers: fingerprinted assets are immutable for one year; unversioned assets have a one-day lifetime. In the zone Cache Rules, if a rule is needed, match URI Path starts with /static/, set cache eligibility to Eligible for cache, and respect origin cache-control. Respect query strings so ?v= versions remain distinct. Do not apply Cache Everything to the whole site. Do not cache wallet, accounts, payments, receipts, or personalised HTML. Revalidate /sw.js and manifests.

## Measure before increasing spend

Check the existing request_completed logs for duration_ms, db_ms and db_queries, and Render CPU/memory metrics during typical use. Server-Timing exposes app and query time without request bodies or tokens. Compare repeated warm visits with the first visit after inactivity; this change does not claim to eliminate network or database-region latency. SQL timings exclude some connection setup/wait time.

The database region has not been changed. Keep the current database until a separately reviewed backup, restore and cutover is ready. An uptime monitor may check /health; monitoring is not a hosting-capacity upgrade.
