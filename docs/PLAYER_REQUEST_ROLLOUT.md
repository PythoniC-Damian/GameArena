# Player request rollout

These changes are local on main. They have not been pushed or deployed.

At the next release, migration `20261009_legacy_messaging` marks existing accounts as exempt from player consent. Messaging stays open between any two existing accounts, including players without previous conversations. Existing pair records become accepted; message history and blocks are preserved. New registrations receive `requires_player_consent=true` from both the application and PostgreSQL default. A conversation involving either new account requires acceptance after one introduction. Running migrations again does not change that boundary.

The configured Render start command already runs `python scripts/migrate.py` before starting the server. This migration must complete before the updated app serves requests; no new environment setting is required.

Public profiles group Message and Add player/Cancel request with matching buttons. Block/report remain available in conversations and existing moderation/settings flows. Accepted/open pairs have no permanent relationship banner. Requests and acceptance produce the existing four-second notification toast, subject to the recipient's chat notification preference.

Request actions use CSRF-protected JSON responses and update their component and composer without replacing the page. Errors leave a retryable control and preserve drafts. Socket events and visibility/reconnection refresh recover relationship changes. Inbox/Requests tabs switch within the conversation. The reload splash no longer has an artificial minimum delay. These improvements do not remove network, database, or hosting wake-up latency, and no hosting/provider migration was performed.

Validation uses isolated PostgreSQL databases and synthetic browser accounts; production data is untouched.

Validation completed: 38 regression tests passed, followed by seven focused request/migration tests after the final adjustments. Browser checks at 390px confirmed matching 48px action buttons, request/cancel updates on the same profile, draft preservation when cancelling or switching Inbox/Requests, and no console errors. JavaScript syntax and Git whitespace checks passed. Production response times were not measured.
