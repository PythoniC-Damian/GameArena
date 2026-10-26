# Declined friend requests — 26 October 2026

Declining a player request now records a 24-hour retry deadline for its sender. The profile/chat controls show a disabled Add player button and remaining time; the button is restored when the cooldown ends. The browser checks the countdown every 30 seconds and refreshes controls at expiry. The server enforces the deadline under the existing connection row lock, including direct POST attempts.

The person who declined can change their mind and send a request back immediately. Retrying never replenishes a previously used introduction allowance. Existing block, direct-message preference, CSRF and request rate limits remain in force.

Migration `20261026_friend_retry` follows `20261026_chat_mentions`, adds a nullable retry deadline, and starts a one-time 24-hour cooldown for historical declines that have no decline timestamp. Migration timestamps explicitly use UTC regardless of database timezone. Repeating the migration does not extend existing deadlines. Chat history and other connection statuses are preserved.

Validation: 13 isolated PostgreSQL friend-request/mention regressions passed; two focused cooldown tests rerun after the final rounding adjustment; Python/JavaScript syntax and whitespace checks; migration backfill and idempotency checked in the synthetic preview database. Mobile preview confirmed the disabled button/countdown and an enabled request after a shortened test deadline. Production deployment is not verified.
