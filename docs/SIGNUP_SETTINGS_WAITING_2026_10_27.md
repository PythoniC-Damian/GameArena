# Signup, Join and Settings — 27 October 2026

## Google
Registration now offers a dedicated Sign up with Google form with CSRF protection and a required terms/privacy checkbox. It enters the same provider flow as Google login: direct Google OAuth or Supabase Google PKCE according to the existing AUTH_PROVIDER setting. The verified provider callback creates new accounts and signs existing accounts in without duplicate users. No keys, provider credentials or callback URLs were changed.

A read-only request to the live `/login/google` returned HTTP 302 to `accounts.google.com/o/oauth2/v2/auth`. Following the public authorization URL exposed Google's `redirect_uri_mismatch` error: the OAuth client's authorized redirect URIs must include exactly `https://gamearena01.com/auth/google/callback`. The live Google sign-in/signup flow is blocked until that private Google Cloud setting is corrected. Opening the private console was blocked by automatic approval review; the user chose to add the redirect URI privately themselves. No provider setting or credential was changed. Callback/account creation and managed PKCE paths passed with synthetic provider responses; real Google account consent was not completed.

## Tournament entry
Open event cards and detail pages show Join again. When registration is not ready, Join opens a free waiting-list confirmation. An explicit CSRF-protected POST records interest separately from UserTournament, WalletTransaction and prize/entry accounting. It is idempotent, does not reserve slots, and does not charge GP or auto-enrol the player later. Ready events continue through the existing confirmed-entry/payment flow. Finished/cancelled events remain closed. Admin deletion of an otherwise deletable empty event also removes its free interest records.

Migration `20261027_waiting_list` creates the backend-only tournament_interest table, its per-event index and unique player/event constraint. It follows `20261026_friend_retry` and was applied twice safely to isolated test/preview databases. It changes no balances or existing entries.

## Settings
`/settings` is now a category list: Account, Privacy & security, Notifications, Gaming, Appearance & accessibility, Language and Account data & support, with links to Master and Arena Shop. Each row opens its own page. Category saves update only that category's fields; legacy full settings POSTs remain supported. Existing profile-photo uploads, password recovery, device notification controls, blocked players, language selection, data export and tracked account requests are preserved. No unavailable Telegram functions are advertised.

Visual inspection at 390px confirmed category navigation and account/appearance controls without horizontal overflow. An always-loaded navigation stylesheet prevents an older optional Vite bundle from overriding the current floating/glowing light/dark menu styles.

Validation: the final canonical redirect and tournament launch suite passed 19 tests; the focused new signup/settings/waiting-list and payment-readiness checks passed. An older canonical-host test fixture was updated to authorize its synthetic production host in the trusted-host list. Coverage includes new scoped settings, Google signup/login identity, PKCE, waiting-list idempotency/privacy, CSRF and no-GP-charge checks; existing authentication, legacy settings and tournament payment/readiness regressions; syntax/whitespace checks. Preview uses synthetic accounts. Production deployment is not verified here.
