# GameArena fixes — 4 October 2026



## Changes



- Hero images display without a border, rounded box or panel background. Image rotation and progressive loading remain.

- Buttons and form controls use the wallet reference: pill-shaped cyan-to-emerald primary buttons, rounded fields and cyan labels, with corresponding readable light-theme colors.

- When Supabase Storage and a persistent upload directory are absent in production, validated profile photos use the existing Supabase PostgreSQL database. Only one resized 384×384 WebP is kept per user in a private `profile_photo` table. Existing configured Storage/local storage paths remain supported. Public photo URLs are opaque and cacheable.

- Chat acknowledges saved messages before background notification work. Socket echoes correlate to client UUIDs; lost/disconnected socket delivery can recover through authenticated, CSRF-protected HTTP using the same ID. A unique index prevents duplicate saves, including concurrent retries. Drafts survive failed sends; normal Connected/Sent status clutter is removed.

- Swipe horizontally to reply. Hold for 550 ms, right-click, or focus a message and press Enter for actions. Own messages can be deleted for everyone after confirmation; other users cannot delete them. Deletion replaces stored text with a tombstone and updates quoted text, live recipients and reconnect history.

- Scoped typing indicators with animated dots expire automatically. Blocking and recipient messaging preferences are respected. Typing events do not write to the database.

- Bank loading requests JSON explicitly and distinguishes expired sessions, missing routes, HTML proxy errors, provider errors and timeouts. Retry can recover after a temporary error. Wallet accounting, provider verification and withdrawal idempotency remain unchanged.



## Migration prerequisite



Run the existing `python db_migrate.py` through the normal release process **before starting the updated application**. New migration `20261004_chat_delivery_and_profile_photos` adds nullable client-message IDs/deletion timestamps, unique indexes and the private normalized-photo table. It enables photo-table RLS and denies browser roles direct table access. This continues using Supabase PostgreSQL; no provider migration is involved.



The migration was exercised twice on isolated loopback PostgreSQL databases only. Production migrations, configuration and live financial records were not modified. The live site still needs the updated code and migration through your normal release process; no deployment was performed.



## Modified files



- `app.py`: persistent database photos, JSON API/session errors, send correlation/recovery, background notifications, deletion and typing permissions.

- `db_migrate.py`: repeatable additive migration.

- `user_media.py`: validated production photo fallback.

- `static/js/chat.js`, `templates/chat.html`: swipe/hold actions, correlated confirmation, HTTP recovery, deletion and typing UI.

- `static/js/wallet.js`: safe response handling and retry.

- `static/css/themes.css`: open hero and coordinated wallet-style controls in both themes.

- `scripts/preview_interface.py`: selectable local preview port.

- `test_oct4_updates.py`, `scripts/check_oct4_updates.py`: isolated backend and browser validation.



## Validation



28 targeted backend/interface tests passed, including five new contracts covering recovery, deletion/privacy, typing scope, production photo fallback and bank JSON/session handling. Syntax, JavaScript checks and Jinja parsing passed. Browser checks passed all 24 combinations of Home, direct Chat and Wallet at 360, 390, 768 and 1440 pixels in Dark and Light themes, with no horizontal overflow or duplicate headers. Typing, live delivery/confirmation, swipe replies, long press/Escape, live deletion, HTTP recovery and bank retry passed, with no JavaScript page exceptions. Local delivery measured 1,564.8 ms; this is not a production guarantee. The first layout pass found a 768-pixel hero overflow, corrected before the final passing run.



[Recorded browser results](validation/oct4-updates.json)  |  [Mobile hero](screenshots/oct4-home-dark-390.png)  |  [Desktop hero](screenshots/oct4-home-dark-1440.png)  |  [Mobile chat](screenshots/oct4-chat-light-390.png)  |  [Withdrawal controls](screenshots/oct4-wallet-390.png)



Live Paystack bank retrieval cannot be verified without an authenticated production session/provider configuration; browser retry is tested with a clearly isolated mocked bank response. No withdrawal, payment or production data mutation was made. Public inspection of the live bank URL was unavailable, so the screenshot's HTML response could be a session redirect, proxy error or outdated deployment; the code now handles each safely rather than displaying a JSON parser exception.


## Verification handoff follow-up

The owner confirmed receiving the live verification code and subsequently signing in successfully. Verification keeps the existing redirect to Login and now explicitly explains that transition, with an accessible success banner on Login. The code field supports numeric keyboards and one-time-code autofill. A chat-script encoding error was corrected to UTF-8. These latest local changes are not deployed.

Follow-up validation: 89 checks passed on the broad run. Three outdated asynchronous/provider tests and one sandbox temporary-directory setup error were corrected; all four affected checks then passed (93 distinct passing checks across the two runs). Python, JavaScript, Jinja and Git whitespace checks passed. The Codex browser freshly reviewed guest Home at 390 pixels with no horizontal overflow and one H1. Authenticated browser review then timed out; the earlier recorded 24-layout checks above were not rerun in this follow-up. See `docs/validation/fix-all-followup.json` and `docs/screenshots/fix-all-home-390.jpg`. Existing datetime/SQLAlchemy deprecation warnings remain.
