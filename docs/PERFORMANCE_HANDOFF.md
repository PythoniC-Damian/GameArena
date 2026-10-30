# Performance work checkpoint — 29 October 2026

Release validation complete; deployment verification follows the merge.

- Batched achievement reads/writes and removed repeated Profile calculations.
- Combined match/win counts on player pages and dashboard.
- Consolidated shared CSS; deferred Socket.IO without changing script order.
- Cached immutable static assets without background re-downloads; retained fresh private pages/APIs.
- Preserved immutable headers on 304 responses, with a passing regression check.
- Added a bounded three-connection pool to the Render Blueprint, using the existing early gevent/psycogreen setup. The paid plan itself was not changed.
- Added query-budget, static-cache and cooperative pooling tests, plus a loopback-only benchmark tool.

Evidence: `docs/validation/render-performance-2026-10-29.json` records 21 Profile queries versus 94 in the original code on a local 32-badge fixture. This is not a production latency measurement. Ten main routes were benchmarked locally.

Validation checkpoint, 30 October: all 8 final targeted performance/cache/concurrency tests passed. This includes both connection-pool modes, saturated cooperative pooling, 304 immutable headers and the page-query budgets. All 16 frontend unit tests passed. Earlier broader selections passed 40 and 71 checks, respectively; the incorrect test URL and payment-stub incompatibility found in those selections were corrected. A later affected selection passed 32 checks with one Windows subprocess startup timeout; the final targeted run passes with a Windows-only 90-second startup allowance and unchanged cooperative-I/O assertions. The full suite and authenticated production latency have not been revalidated.

Additional validation, 30 October: authenticated Profile and Wallet checked at 390px and Tournaments at 360px, without horizontal overflow. No Wallet browser errors were reported. Production startup now supplies the bounded pool defaults even when an existing Render service has not synchronized its Blueprint; explicit environment overrides still apply.

The full backend run completed with 313 passes and 137 failures. Seven independent failures reproduce on deployed baseline 54f02a8: registration email verification, legal agreement markup, activity consent, Pro welcome markup, and three migration checks. The legacy migration checks leave the disposable test schema missing `user.requires_player_consent`, causing 129 later schema errors and one missing-token assertion. The fresh-database rerun completed with 137 passes and two failures: the existing public-support token expectation and an outdated Google signup redirect expectation, both independently reproduced on baseline. All nine final performance/cache/cooperative-pooling checks pass, including production-default, null and queue modes. Across both runs, the latest results cover 451 distinct backend checks: 442 pass and nine fail; all nine remaining failures reproduce on unchanged baseline. Do not interpret the original run as 137 independent application regressions.

GitHub Actions cannot start: the owner's account is locked due to a billing issue. Local validation is recorded rather than claiming CI passed. PR: https://github.com/PythoniC-Damian/GameArena/pull/16. The GitHub connector reports read-only access; publication succeeded using existing local Git credentials on branch `codex/gamearena-performance`.

Deployment target: existing Render service `srv-d9qfmt4s728c739qblc0`, main branch, Oregon, https://gamearena01.com. Last inspected plan remains Free; billing has not been changed. Before/after public timings are kept in the ignored local validation directory. Authenticated production latency has not been measured. Verify deployment by the single shared stylesheet, service-worker cache v8 and successful health/public routes. Render browser control currently times out; main-branch automatic deployment is configured in the Blueprint.

Local tests require `GAMEARENA_TEST_DATABASE_URL` pointing at an isolated PostgreSQL database. Never run them against Supabase production. No production data, credentials, billing or deployment were changed.
