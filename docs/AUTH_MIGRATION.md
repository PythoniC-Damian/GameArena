# Supabase Auth cutover

## Verified production configuration

Dashboard inspection on 2026-10-06 identified:

- Supabase project: `cnliaiawirgjqijixnly` (GameArena).
- Supabase URL: `https://cnliaiawirgjqijixnly.supabase.co`.
- Render service: `srv-d9qfmt4s728c739qblc0` (gamearena), serving
  `https://gamearena-p8en.onrender.com` and `https://gamearena01.com`.
- Render deploy source: `PythoniC-Damian/GameArena`, branch `main`.
- Saved Supabase Site URL: `https://gamearena01.com`.
- Saved redirect allowlist: `https://gamearena01.com/auth/supabase/callback`.
- Supabase email confirmation is enabled. Google and custom SMTP were disabled
  at inspection; they still require configuration before activation.

The previously configured `gamearena.onrender.com` callback does not point to
the Render hostname listed on the live service. No production account import or
auth-provider cutover has been performed.

Supabase owns passwords, Google identities, verification codes and recovery codes.
Flask retains the application's HttpOnly signed session for its server-rendered
pages and Socket.IO. Provider tokens are not saved in browser cookies; transient
provider sessions are closed after establishing the application session. App
sessions expire after 12 hours; suspension and app password reset revoke access
through database checks. Changes made directly in Supabase do not automatically
revoke Flask sessions. This is an explicit integration boundary, not a complete
replacement of Flask sessions with Supabase sessions.

## Prepare before activation

1. Back up PostgreSQL and confirm the actual production service behind
   `https://gamearena01.com`. The old `gamearena.onrender.com` served different
   routes during review. Deploy this checkout to the service serving the custom
   domain; changing source alone does not change a running deployment.
2. Run `python scripts/migrate.py`. The additive migration links managed UUIDs
   while preserving every integer user ID and business foreign key.
3. Keep `AUTH_PROVIDER=local` during preparation. Set `SUPABASE_URL` and
   `SUPABASE_PUBLISHABLE_KEY` (or the legacy `SUPABASE_ANON_KEY`) on the server.
   Do not use a service-role key as the login key.
4. In Supabase Auth, enable email confirmations. Set Site URL to
   `https://gamearena01.com` and allow exactly
   `https://gamearena01.com/auth/supabase/callback` as an OAuth redirect.
   Add explicit localhost callbacks for development only.
5. Enable Google in Supabase using the Google client ID and secret. In Google
   Cloud, authorize Supabase's displayed callback URL (normally
   `https://PROJECT_REF.supabase.co/auth/v1/callback`). The final application
   callback is the custom-domain URL above, not the old Render URL.
   If deploying the fixes before cutover in local-auth mode, also authorize
   `https://gamearena01.com/auth/google/callback` in Google Cloud. The legacy
   `GOOGLE_REDIRECT_URI` variable is no longer used; the callback is derived
   from `PUBLIC_BASE_URL` in production.
6. Configure custom SMTP in Supabase (Resend SMTP is one option). Supabase's
   default delivery service is restricted and unsuitable for production. Local
   Flask Resend settings do not configure Supabase SMTP.
7. Configure the Confirm signup and Reset password email templates to show
   `{{ .Token }}` as the code. The UI uses code entry, not fragment-based links.
   For example: `<h2>Your GameArena code</h2><p>{{ .Token }}</p>`.
   Set code expiry to 900 seconds to match the UI. Keep the provider resend
   interval at least 60 seconds and provider email rate limits enabled.
8. Preview the existing-account import with
   `python scripts/import_supabase_users.py`. Review the account count. Supply
   `SUPABASE_SERVICE_ROLE_KEY` only to the import process and execute with
   `--apply` when ready. It sends no invitations or recovery emails. Remove the
   admin key from the web environment afterward if it is not used for Storage.
   Existing accounts receive random inaccessible managed passwords. Players
   use Forgot password to establish their new password; verified Google sign-in
   can also establish access. Unverified accounts use Resend Code first.
   Suspended accounts remain suspended in GameArena.
9. Test signup, confirmation, password login, Google login, recovery and reset
   on a staging Supabase project. Check balances and tournament history remain
   attached to the same IDs. Test an existing admin as well as a normal player.
10. Set `AUTH_PROVIDER=supabase` and restart the correct service. This disables
    local-password authentication and rejects old Flask sessions. Credentials
    are never checked against both providers. Do not activate until imports and
    staging checks succeed. Existing local code delivery jobs skip after cutover.

The code does not update your Supabase dashboard, Google Cloud, hosting plan or
production secrets automatically. Render Free cold starts are a hosting concern;
use an always-on service when reliable callbacks are required.

## Rollback

Before users change managed passwords, reverting `AUTH_PROVIDER=local` restores
the existing local login implementation and password hashes. Once passwords have
changed in Supabase, those hashes are stale: do not promise transparent rollback.
Keep the additive identity columns and business data; use an explicit recovery
plan rather than dropping tables.

References: [Google provider](https://supabase.com/docs/guides/auth/social-login/auth-google),
[SMTP](https://supabase.com/docs/guides/auth/auth-smtp),
[email templates](https://supabase.com/docs/guides/auth/auth-email-templates).
