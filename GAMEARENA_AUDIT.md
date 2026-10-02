# GameArena project audit

Reviewed 2 October 2026. Scope: the current Project X checkout, including the Flask application, 31 HTML templates, static assets, deployment configuration, migrations, helper scripts, and existing tests. This is a source and static-validation audit; production behavior and visual layout have not been measured in a running browser.

## What GameArena is

GameArena is a server-rendered Flask/PostgreSQL mobile esports tournament platform. Players register or use Google login, verify email, find tournaments, pay entry fees through Paystack, compete in matches, submit and confirm results, raise disputes, and track placements and achievements. It includes deposits and withdrawals, global and direct chat through Socket.IO, notifications, privacy settings, blocks/reports, support, and administrator controls. Local images cover eFootball, Call of Duty Mobile, Free Fire, and PUBG. Adding another game currently needs consistent image mapping and game naming.

The existing foundation includes CSRF protection, security headers, private cache policies, signed payment webhooks, conditional updates for deposit idempotency, withdrawal reservations and reconciliation, uniqueness constraints, query indexes, some eager loading, bounded chat history, reduced-motion handling on several carousels, health checks, and request-duration logs. These protections should be preserved while optimizing.

## Confirmed defects and important flow gaps

| Priority | Evidence | Effect | Proposed change |
| --- | --- | --- | --- |
| First | `templates/payment.html:131` starts the handler with `nfunction` | The inline script cannot parse, leaving the Pay button without its handler. There are also stray `n` characters and `rounded_[20px]` class typos. | Repair the handler and markup; exercise checkout with Paystack test mode. |
| First | `templates/admin_leaderboard.html:102` uses an anchor; `app.py:2777` accepts POST only | Delete sends GET and receives method-not-allowed. | Use a POST form with CSRF and a clear confirmation. |
| First | `templates/settings.html:30` opens the settings form; line 59 opens another form inside it | Invalid nested forms can change form ownership and disrupt saving settings and unblocking. | Separate the unblock forms from the settings form, or explicitly associate buttons with independent forms. |
| First | `app.py:2835`, `app.py:3321` reject any existing membership | A pending payment is treated as already joined, preventing the normal UI from reopening checkout, despite backend initialization supporting pending records. | Distinguish pending, paid, free, failed, and refunded memberships; provide Resume payment. |
| First | Join route lacks a tournament-status check; listing Join links depend on capacity/authentication, not status | A finished/cancelled tournament can still expose a join path. Detail-page checks alone do not enforce server rules. | Enforce open registration in the backend and every entry point. |
| First | Capacity is checked before joining/initializing payment, with no serialized slot reservation; payment completion does not recheck capacity | Concurrent users and delayed successful payments can exceed capacity. | Reserve slots transactionally, expire abandoned reservations, and define handling for a payment that arrives after a reservation expires. Test concurrent last-slot requests. |
| First | `app.py:1454` completes the bracket and announces a champion without a prize ledger entry; cancellation only changes tournament status | The win-to-cash-out journey and cancellation refund journey are incomplete in this checkout. | Define prize allocation, dispute/finality rules, audited idempotent prize credits, and cancellation refunds before presenting them as completed automatic flows. |
| Next | `templates/_pwa_register.html:5` registers `/static/sw.js` without a root scope | Default scope is `/static/`, so the worker does not control `/`, `/dashboard`, or `/tournaments`. | Serve the worker at `/sw.js` and register root scope, or deliberately allow and register broader scope. Test actual page control. |
| Next | `templates/dashboard.html` has no Socket.IO client or notification event handler | Dashboard notifications are snapshots even though the page describes them as live. | Add a shared authenticated notification client, update unread badges, and reconcile missed events after reconnect. |
| Next | `templates/chat.html:167` emits then immediately clears the input | Rejected or disconnected sends have no reliable pending/failed state; reconnect does not fetch missed messages. | Add server acknowledgements, stable message IDs, pending/sent/failed UI, safe retries, and cursor-based catch-up. |
| Next | `templates/tournaments.html:124` puts `pb-28 md:pb-8` outside the class attribute | The intended mobile spacing is ineffective. | Repair the attribute and verify bottom navigation never covers the final content/action. |
| Next | OAuth saves provider picture URLs, but CSP allows only self/data/Unsplash image origins | Google-hosted profile pictures can be blocked by the browser. | Define a narrow supported avatar policy and fallback, consistently across OAuth, settings, and CSP. |

## Display and navigation improvements

Keep the existing dark emerald/cyan gaming identity, but make the tournament task easier to scan. Put game, start time with timezone, entry fee, available slots, prize allocation, rules, and the appropriate action together. Show Joined, Resume payment, Full, Registration closed, or Join based on actual server state.

Build one shared base template, header, navigation, flash-message component, and common JavaScript module. Pages currently duplicate navigation and menu handlers, while newer settings/support/public-profile screens have different structures. Use consistent desktop access to Dashboard, Wallet, Chat, Notifications, Settings, and Support. Keep mobile destinations predictable and preserve the intended tournament destination through login and verification.

Use visible focus styles, keyboard-operable menus, Escape dismissal, focus restoration/trapping for dialogs, accessible status announcements, and comfortable touch targets. The featured-carousel indicators are only `h-2 w-2`; enlarge their clickable area. Hidden cube faces need their links removed from keyboard navigation, not only `aria-hidden`. Provide a pause control and pause featured animation when offscreen, in a hidden tab, or keyboard-focused.

Reserve bottom navigation space centrally and include safe-area insets. Test 320/360/390px widths, landscape, enlarged text, the onscreen keyboard, long usernames, long tournament names, empty states, and large tables. Replace alert-driven payment UX with inline field errors and pending/success/failure states. Disable repeated submissions while pending, with server idempotency as the authoritative safeguard.

Use timezone-aware timestamps and explicitly display a timezone. Current database timestamps and `strftime` output are often naive, while chat feeds ISO timestamps directly into browser date parsing. This can make match schedules and message times inconsistent across users.

## Speed and latency

1. **Reduce image bytes first.** `static/images` totals 26,004,061 bytes (about 26 MB), which is the asset inventory, not a measured page download. Individual files range up to 4.4 MB; featured posters are approximately 2.6–3.7 MB. Generate properly sized WebP/AVIF derivatives, responsive `srcset`/`sizes`, and small thumbnails. Prioritize the first visible hero image and defer secondary imagery. Set explicit image geometry. Remove source-image duplicates from deploy artifacts where appropriate.
2. **Compile Tailwind at build time.** Templates load the runtime CDN script instead of a production stylesheet. Ship a minified generated stylesheet and preserve dynamically used classes during compilation. Tailwind explicitly describes its Play CDN as development-only: [official documentation](https://tailwindcss.com/docs/installation/play-cdn).
3. **Bound HTML data queries.** Home and tournaments load all tournaments plus all participant objects. Wallet, dashboard memberships, and several admin views also use unbounded queries. Limit home to selected upcoming/featured data; paginate lists and history; implement server-side filtering. Calculate participant counts and monetary totals in SQL instead of materializing whole relationships.
4. **Fix remaining lazy relationship loads.** Global chat loads messages and then accesses their users. HTML tournament details loads matches without eager-loading players, winners, submitters, chat authors, and disputes used by the template. Dashboard memberships also access tournaments in templates. Add targeted eager loading and bounded subcollections, then verify query counts against representative data. Existing API/dashboard eager loading is useful but not comprehensive.
5. **Review connection setup.** `NullPool` opens fresh PostgreSQL connections at each checkout. This may contribute latency, especially when rate-limit updates commit before the handler's queries. Benchmark against a correctly configured pool or external pooler under the deployed Gevent setup. Do not blindly replace the documented workaround for a prior locking failure.
6. **Bound external requests.** Three Paystack initialization calls have no timeout. Set explicit connect/read timeouts, handle non-JSON and provider errors, and reconcile unknown outcomes before retries. Requests otherwise has no default timeout: [official documentation](https://requests.readthedocs.io/en/latest/user/quickstart/).
7. **Remove avoidable waiting.** The splash screen is skipped on ordinary navigation, but reload/authentication flows enforce a 1.2-second minimum plus fade-out and wait for full window load. Use task-local pending states and render usable content as soon as it is ready.
8. **Separate background work.** Email is synchronous. `celery_worker.py` imports a nonexistent `celery` object and Celery is absent from requirements. Implement an actual durable worker/outbox for mail and payment reconciliation, or remove the misleading runner. Report queued versus delivered email truthfully.
9. **Measure deployment behavior.** `render.yaml` specifies a free web plan. If production follows it, idle spin-down can explain long first requests; Render documents a 15-minute idle threshold: [official documentation](https://render.com/docs/free). Measure cold and warm startup separately before selecting hosting changes. The live deployment plan was not verified.
10. **Scale real-time services deliberately.** The deployment uses one Gunicorn Gevent worker and no Socket.IO message queue. Verify actual WebSocket upgrades and fallback transport. Multiple server instances require coordinated messaging and appropriate routing; simply increasing Gunicorn workers is not the documented solution: [Flask-SocketIO deployment guidance](https://flask-socketio.readthedocs.io/en/stable/deployment.html).

Request-duration logs already exist. Add per-route p50/p95/p99, database query time/count, external provider timing, WebSocket acknowledgement timing, disconnect/reconnect rates, browser errors, and cache hit rate. Keep secrets and payment details out of telemetry.

## Caching plan

Existing static HTTP caching lasts one day; public JSON APIs have short cache lifetimes; authenticated responses use private/no-store. The service worker deliberately avoids private HTML/API caches. Keep that privacy boundary.

- Use content-hashed CSS, JavaScript, and image derivative URLs with long immutable cache lifetimes. Revalidate the service worker and manifest.
- Fix worker scope, restrict cleanup to GameArena-owned cache names, and bound runtime-cache size. The current activation deletes every cache whose name differs from the current one, and cache writes are not attached to the fetch event lifetime.
- Add a small static offline page rather than storing authenticated wallet/chat/dashboard pages in shared Cache Storage.
- Cache public tournament summaries and leaderboards briefly at the server/CDN where useful, with invalidation after registration, payment, result confirmation, or admin edits. Existing cache headers alone do not create a server-side cache or guarantee a CDN is using it.
- Preserve session-aware cache handling for HTML. Never share balances, room passwords, direct messages, or personalized membership state between users.

Service worker scope behavior is documented by [MDN](https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorkerContainer/register).

## Validation completed and remaining

Completed without importing or starting the application:

- Parsed 61 Flask route handler functions and checked 274 template URL references: no missing endpoint names; one POST-only endpoint incorrectly linked with an anchor.
- Syntax-checked 17 nonempty inline JavaScript blocks after replacing Jinja expressions with placeholders; only the payment script failed. This is a static check, not full rendered-template or browser validation. The standalone service worker parsed successfully.
- Parsed all 18 Python files: 17 passed; `write_wallet.py:4` has an unterminated triple-quoted string. This helper is not part of the main app startup path.
- Found `test_prize_flow.py:7` uses `tmp_path` without declaring the fixture argument. That test will raise a NameError once reached. Despite its name, it checks SQLite rejection, not prize distribution. `test_app.py` is a separate mock app, not an end-to-end test of GameArena.

Integration tests could not run: the default Python command points to an unusable Windows execution alias; the existing test virtual environment references an unavailable interpreter; the bundled Python runtime has no pytest/Flask/PostgreSQL dependencies; and no isolated `GAMEARENA_TEST_DATABASE_URL` is configured. No production database was used. No live browser, Lighthouse, load-test, or measured speed score is claimed.

Next validation should use a reproducible environment and isolated PostgreSQL database:

| Area | Scenarios |
| --- | --- |
| Navigation | Every page for guests, players, and admins; login destination preservation; back/forward; mobile menus; active destinations; keyboard and screen-reader behavior. |
| Money | Test-mode checkout, cancel/retry/resume, duplicate clicks, duplicate/out-of-order webhooks, provider timeouts, withdrawal idempotency, unknown transfer outcomes, refunds, and prize credits. |
| Tournament | Free/paid joins, closed/full states, two users competing for the last slot, matchmaking, result confirmation, disputes, bracket advancement, and payout exactly once. |
| Real time | Send acknowledgement, offline/reconnect, missing-message recovery, duplicate suppression, unread/read synchronization, blocks/privacy, and suspended users. |
| Display | Small phones through desktop, zoom, landscape, keyboard, slow/broken images, long content, offline pages, and reduced motion. |
| Performance | Cold/warm loads, first/repeat visits, constrained mobile network/CPU, large data sets, sustained HTTP and Socket.IO concurrency, query counts, error rates, and cache effectiveness. |

Use Core Web Vitals goals of LCP at most 2.5 seconds, INP at most 200 ms, and CLS at most 0.1 at the 75th percentile of real visits, with separate device cohorts. These are targets, not current results: [threshold guidance](https://web.dev/articles/defining-core-web-vitals-thresholds). Set warm server-response and chat-acknowledgement budgets after baseline measurements; exclude provider checkout duration from the app's own processing metric.

## Recommended delivery order

1. Repair payment, Delete, Settings forms, pending-payment recovery, and registration-state enforcement. Make the core journey usable and enforce capacity transactionally.
2. Establish prize/refund behavior and regression tests, then automate browser checks of the high-value journeys.
3. Compress responsive images, compile CSS, simplify unnecessary waiting, and unify navigation/components.
4. Paginate HTML data, aggregate counts, remove lazy-load query growth, bound provider requests, and add reliable real-time delivery states.
5. Fix PWA scope and implement versioned caching, observability, background jobs, and measured hosting/scaling changes.

Keep Flask for this work. A framework rewrite would not by itself repair these flows or reduce oversized assets. Split the large `app.py` into focused blueprints/services as the affected areas are improved, and move sample seeding/admin bootstrap out of normal imports: startup currently queries/writes the database, renames a Free Fire tournament, and inserts missing sample games.
