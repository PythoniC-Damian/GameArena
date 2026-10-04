# Immediate chat sending and scaling preparation

Send immediately clears and focuses the composer. Each outgoing bubble owns a UUID, pending/sent/error state and Retry control. Up to four sends can be in flight while further sends queue; at most fifty unconfirmed messages are retained. The tab-scoped outbox is separated by account and conversation and can be retried after refresh. Acknowledging an earlier message cannot erase a later draft.

Socket recovery starts after 1.5 seconds rather than 5 seconds and uses the authenticated CSRF-protected HTTP endpoint with the same UUID. Manual retry also preserves identity. The database unique constraint protects against duplicate saves. Server-side duplicate acknowledgements no longer consume the send-rate budget; authentication, blocking and original limits remain. A Sent label confirms server persistence, not recipient read status.

The earlier additive chat/photo migration remains a release prerequisite. This change introduces no further schema migration. Production configuration, live messages and financial data were not modified.

## Validation

Ten isolated PostgreSQL tests passed, including five concurrent HTTP messages, repeat recovery without duplicates, twelve duplicate socket acknowledgements without exhausting the fresh-message rate limit, blocking, replies, deletion and existing photo/API contracts. Initial validation exposed late background notifications contaminating subsequent test fixtures; the isolated test teardown now waits for those tasks and all ten checks passed on recheck.

The browser fixture deliberately delays socket acknowledgement by six seconds and HTTP handling by four seconds. Five messages were submitted with an empty composer and enabled Send after every submission. Four bubbles initially showed Sending and one Queued. All five later showed Sent, exactly five rows existed, zero pending rows remained, and the subsequent typed draft stayed unchanged. Mobile width 390 had no overflow and no browser console errors. Screenshots and structured evidence are under docs/screenshots/chat-outbox-* and docs/validation/chat-outbox.json.

Real production delivery latency and horizontal capacity have not been measured. The isolated delay demonstrates nonblocking UI and safe transport recovery; it is not a production benchmark.

## Scaling dependencies

Optional SOCKETIO_MESSAGE_QUEUE connects Flask-SocketIO to a shared Redis pub/sub service (redis client pinned in requirements). Leave it unset for the current single-instance setup. Test/preview mode deliberately ignores it. No Redis service was provisioned or billed and cross-instance pub/sub has not been integration-tested.

Use multiple single-worker instances behind sticky-session-aware routing with the same shared queue and secret. Do not simply increase Gunicorn -w: Socket.IO rooms and polling need coordinated routing. A distributed anti-abuse limiter and production load/capacity tests are still needed before claiming horizontal readiness. Supabase connection latency/limits should be profiled; the existing NullPool remains because it avoids the earlier gevent locking regression.

Source: https://flask-socketio.readthedocs.io/en/latest/deployment.html

Files: static/js/chat.js (outbox/composer/recovery); static/css/themes.css (per-message states); app.py (retry rate handling and optional shared queue); requirements.txt and .env.example (optional Redis dependency/configuration); conftest.py (test task isolation); test_chat_outbox.py (burst/idempotency tests).
