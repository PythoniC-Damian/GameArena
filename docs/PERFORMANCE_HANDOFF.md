# Performance work checkpoint — 29 October 2026

Work in progress; not deployed. Resume validation before merging.

- Batched achievement reads/writes and removed repeated Profile calculations.
- Combined match/win counts on player pages and dashboard.
- Consolidated shared CSS; deferred Socket.IO without changing script order.
- Cached immutable static assets without background re-downloads; retained fresh private pages/APIs.
- Preserved immutable headers on 304 responses, with a passing regression check.
- Added a bounded three-connection pool to the Render Blueprint, using the existing early gevent/psycogreen setup. The paid plan itself was not changed.
- Added query-budget, static-cache and cooperative pooling tests, plus a loopback-only benchmark tool.

Evidence: `docs/validation/render-performance-2026-10-29.json` records 21 Profile queries versus 94 in the original code on a local 32-badge fixture. This is not a production latency measurement. Ten main routes were benchmarked locally.

Validation checkpoint, 30 October: all 8 final targeted performance/cache/concurrency tests passed. This includes both connection-pool modes, saturated cooperative pooling, 304 immutable headers and the page-query budgets. All 16 frontend unit tests passed. Earlier broader selections passed 40 and 71 checks, respectively; the incorrect test URL and payment-stub incompatibility found in those selections were corrected. A later affected selection passed 32 checks with one Windows subprocess startup timeout; the final targeted run passes with a Windows-only 90-second startup allowance and unchanged cooperative-I/O assertions. The full suite and authenticated production latency have not been revalidated.

Next: finish responsive browser checks, run the full CI suite before merge, verify Render/Supabase regions and compare authenticated live request timings after a reviewed deployment. The local preview opened and signed in successfully, but mobile checks are unfinished. The GitHub connector reports read-only access; publication succeeded using existing local Git credentials on branch `codex/gamearena-performance`.

Local tests require `GAMEARENA_TEST_DATABASE_URL` pointing at an isolated PostgreSQL database. Never run them against Supabase production. No production data, credentials, billing or deployment were changed.
