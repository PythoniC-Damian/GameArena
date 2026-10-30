# Performance work checkpoint — 29 October 2026

Work in progress; not deployed. Resume validation before merging.

- Batched achievement reads/writes and removed repeated Profile calculations.
- Combined match/win counts on player pages and dashboard.
- Consolidated shared CSS; deferred Socket.IO without changing script order.
- Cached immutable static assets without background re-downloads; retained fresh private pages/APIs.
- Preserved immutable headers on 304 responses (latest regression check still needs running).
- Added a bounded three-connection pool to the Render Blueprint, using the existing early gevent/psycogreen setup. The paid plan itself was not changed.
- Added query-budget, static-cache and cooperative pooling tests, plus a loopback-only benchmark tool.

Evidence: `docs/validation/render-performance-2026-10-29.json` records 21 Profile queries versus 94 in the original code on a local 32-badge fixture. This is not a production latency measurement. Ten main routes were benchmarked locally.

Validation so far: 16 frontend unit tests passed. The first backend selection passed 40 checks with one incorrect test URL, subsequently fixed. The broader selection passed 71 checks with one payment-recovery stub incompatibility, subsequently fixed. The affected rerun passed 32 checks; one Windows subprocess exceeded its 35-second startup timeout. Its Windows startup allowance was raised to 90 seconds while retaining the same cooperative-I/O assertions. Final targeted validation is pending.

Next: run the targeted performance/cache/concurrency tests and finish responsive browser checks. Then verify Render/Supabase regions and compare authenticated live request timings after a reviewed deployment. The GitHub connector currently reports read-only access; local Git credentials are being used to attempt publication.

Local tests require `GAMEARENA_TEST_DATABASE_URL` pointing at an isolated PostgreSQL database. Never run them against Supabase production. No production data, credentials, billing or deployment were changed.
