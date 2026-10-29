# Settings and email verification

- Privacy & security links to optional email two-step verification and shows blocked players with unblock controls.
- Enabling and disabling the email step both require recent primary authentication and a code delivered to the verified account email. Password, direct Google and Supabase sign-in all pass through the same second-step completion function.
- Codes expire after five minutes, are single-use, and are stored as keyed digests. Requests and attempts are limited. Changing the setting invalidates older account sessions. The existing account email provider must work before users enroll; no production delivery was tested in this change.
- Private-chat and group/community notification switches are independent. Preferences are checked before creating notifications and again before queued push delivery. Messages remain available when alerts are muted. This does not introduce alerts for every community post.
- Languages use searchable native-name/English-name rows. Only the existing English, Spanish, French and Portuguese catalogs are selectable. Additional screenshot languages remain unavailable until translations are ready, as requested by the owner. Untranslated copy falls back to English; user content is never sent to a translation service. Long legal text still needs editorial translation review.
- Migration `20261029_settings_security` adds security challenge storage and notification preference columns without deleting existing records. Two-step verification defaults to off. Existing chat preferences remain respected.
- Mobile signup spacing, shared tournament footer and collapsible policy contents were refined. Winner-only pilot rules, payouts and tournament records were not changed.

Local verification uses synthetic accounts and an isolated PostgreSQL database, with email delivery mocked. Never copy production codes, passwords or keys into tests.
