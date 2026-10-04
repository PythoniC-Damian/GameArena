# GameArena verification email setup

Email-only changes preserve the rest of the application and all existing uncommitted edits.

## Required live configuration

In Resend, add `gamearena01.com` under Domains and copy its exact sending DNS records into the Cloudflare zone. DKIM and return-path authentication records are specific to the domain/region. New domains may use CNAME records instead of the older SPF TXT/MX arrangement. Use the values Resend supplies; do not guess them, replace website records or overwrite existing root-domain receiving MX records. Wait until Resend reports sending verification complete.

Set these values on the existing Render service:

```text
EMAIL_PROVIDER=resend
EMAIL_FROM=GameArena <noreply@gamearena01.com>
RESEND_API_KEY=<your existing Resend sending key>
```

The key must have sending permission for this domain. Enter it directly in the host's protected Environment settings; do not share or commit it. `EMAIL_FROM` can be another address on the verified domain. A support mailbox can receive the delivery test; Resend's sending domain does not itself create a mailbox.

The live deployed commit already supports Resend over HTTPS. Its Render `EMAIL_FROM` was `onboarding@resend.dev`, which is the restricted testing sender. Changed only that environment variable to `GameArena <noreply@gamearena01.com>` with Save only, then used Restart service with the owner's explicit approval. Render confirms the restart, and the deployed commit remains `a25c52e54680b48f2e64cc94638dbdc8c9f6f1b3`. **Correction: Restart service retains the running instance's previous environment values and does not activate saved changes.** Render's Environment page must use **Save and deploy**, which reuses the existing build with updated environment variables. This activation still needs the owner's approval under the earlier no-deploy restriction. No new code was pushed or deployed. The newer local email hardening still requires the normal release process.

## Behavior and speed

- Resend uses HTTPS with an eight-second network timeout. Domain/DNS verification is setup work, not an extra network lookup on each registration.
- Render defaults to Resend and fails promptly if the key is absent or rejected, rather than attempting its blocked SMTP ports. Local/supported SMTP remains available with `EMAIL_PROVIDER=smtp` or `auto`.
- Successful sends require a provider message ID. Error logs classify missing keys, authorization failures, rate limits and timeouts without exposing email addresses, codes, keys or provider response bodies.
- A content-based idempotency key prevents duplicate provider sends for identical requests.
- Code generation, expiry, verification, authentication and resend protections remain unchanged. No background job is claimed to have delivered a security code before Resend accepts it.

## Live validation still required

Send one verification email to the owner's explicitly selected inbox. Check Resend's event log for Delivered and confirm inbox receipt (including spam). Then complete verification with the received code. API acceptance alone does not prove inbox delivery.

### Latest owner-confirmed result

The owner has now confirmed receipt of the verification code in the selected Gmail inbox. Live inbox delivery is therefore confirmed by the recipient. The owner reports that clicking Verify Email leaves the browser loading; successful live account verification is **not** yet confirmed. Browser inspection still times out, including attempts to read the verification tab, so no specific live cause has been established and no speculative application changes were made. The owner was asked to try the same verification flow in Chrome/Edge outside Codex, using the latest code.

Re-ran the isolated registration-to-code-verification test: `test_email_delivery.py::test_registration_code_arrives_in_provider_payload_and_verifies` passed (one test, four existing datetime deprecation warnings, 22.31 seconds). This validates the local route behavior, not the live verification request. Successful verification redirects to Login with a success message.

## Live domain setup completed October 4, 2026

Added `gamearena01.com` to the existing Resend account, with sending enabled in Ireland (`eu-west-1`). Added the three exact records supplied by Resend in Cloudflare, all with Auto TTL:

| Type | Name | Target/content | Proxy |
| --- | --- | --- | --- |
| TXT | `resend._domainkey` | Resend's domain-specific public DKIM key | DNS only |
| CNAME | `rsend` | `rsend-euw1.forge.rmta.net` | DNS only |
| CNAME | `send` | `send.forge.rmta.net` | DNS only |

Resend now reports **Verified** for the domain and all three records. The original root A record and `www` CNAME were preserved. Receiving was not enabled and no root MX records were added. Domain sending verification does not create a support mailbox.

The original GameArena API key is present in Resend and configured on Render; it was not revealed, rotated or changed. During inspection, Resend's onboarding Add API Key button unexpectedly created a separate Onboarding key and exposed it in diagnostic output. With the owner's explicit approval, that unused key was revoked immediately. Resend now lists only the original GameArena key.

The owner's selected test inbox is `wegamearena@gmail.com`. The owner explicitly approved using one live test account and submitted the registration form privately. Registration reported Email already registered, so no duplicate account was created. Opened the existing verification page and clicked Resend Code once for this authorized inbox. The application reported that it could not send the verification email. Inbox delivery remains unverified. Browser access subsequently timed out for both Resend and Render, so the failed provider request could not be inspected. The saved sender has not yet been activated via Save and deploy.

On returning to Resend, receiving had been enabled and the domain's overall status had changed to Partially Verified because the receiving MX record was Pending. All three sending records remain Verified. No receiving DNS or receiving settings were changed during this Render configuration step.

Proof: `docs/screenshots/email-domain-verified.jpg`, `docs/screenshots/email-dns-configured.jpg`, `docs/screenshots/email-render-sender-saved.jpg`, `docs/screenshots/email-render-restarted.jpg`, and `docs/screenshots/email-onboarding-key-revoked.jpg`.

Files: `app.py` (email sender/provider handling only), `.env.example` (email configuration examples), `test_email_delivery.py` (mocked provider and registration/verification checks), and this guide. Other pending project changes predate this email task and are preserved.

References: [Resend verified domains](https://resend.com/docs/dashboard/domains/introduction), [domain management](https://resend.com/docs/dashboard/domains/manage-domains), [Render Free SMTP restrictions](https://render.com/docs/free), [Render environment save options](https://render.com/docs/configure-environment-variables), [Render restart preserves old configuration](https://render.com/docs/deploys#restarting-a-service).

Validation: 12 mocked-provider/email-flow tests passed, including registration through actual code verification. These are isolated loopback PostgreSQL tests, not evidence of live inbox delivery. No real email was sent. Syntax and Git whitespace checks passed.

## Latest live result reported by the owner

The owner subsequently confirmed receiving the verification code at wegamearena@gmail.com and signing in successfully to the dashboard. This supersedes the earlier failed-delivery status above. Direct browser inspection of the reported slow verification transition was not completed; isolated tests check verification persistence and the redirect to Login. The local success message now explicitly invites the player to log in to enter the arena. No further sender or DNS changes are needed based on that successful delivery.
