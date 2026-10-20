# Security implementation and verification — 19 October 2026

Status: implemented and checked locally; **not deployed**. Existing tournament work is preserved. No live transfers, production exploit attempts, owner credential changes or external dashboard configuration were performed.

## Implemented

- Encrypted authenticator enrollment, rate-limited single-use codes and 128-bit recovery codes stored as digests. Administrator enrollment is required by default in production. Enrolled players must also complete MFA on subsequent sessions. HTTP and Socket.IO enforce the policy.
- Fresh sign-in before sensitive financial/admin writes; rejected withdrawals do not reserve or debit funds. Owner tools revoke sessions or reset genuinely lost MFA after explicit account confirmation.
- Private admin audit records and redacted structured alert logs; optional bounded owner email delivery. Emergency flag pauses new withdrawals before provider calls.
- Optional private Cloudflare origin-header verification outside both Flask and Engine.IO, with Host validation and an exact health-check exception. It needs private configuration on both Cloudflare and Render before activation.
- Per-response script nonces, removal of inline wallet click handlers, restricted WebSocket destinations, and account-security interface translations in Spanish, French and Portuguese.
- Authenticated encrypted database archives, verification and guarded restore tooling; private Windows DPAPI configuration and an owner-run daily scheduling script. Storage remains local as requested; no owner backup key, private configuration or actual scheduled task was created.
- Weekly dependency-update configuration and CI dependency/history-secret checks. Fixed the patched selector-parser advisory and verified frontend compatibility.

## Evidence

| Check | Result |
| --- | --- |
| Security, backup-integrity and auth-transport run | 24 passed |
| Additional owner recovery, bounded alerts and account-isolation run | 6 passed; four repeat cases and two additional cases, giving 26 distinct focused checks across these runs |
| Earlier wallet/interface/database-access regression run | 40 passed; one transient local PostgreSQL connection timeout; the affected test passed when rerun |
| Actual backup/restore drill | Encrypted a synthetic PostgreSQL fixture, authenticated the archive, restored exact rows into a new isolated database, and refused a second restore over its populated target |
| Migration | Isolated preview upgraded to `20261019_account_security`; both new tables have row-level security enabled |
| Python dependencies | 53 resolved packages; no known advisories in the local pip-audit result |
| Frontend | Frozen install, TypeScript/Vite production build and Tailwind CSS compilation passed; final audit retains one high development-only advisory described below |
| Current source secret scan | No findings after narrowly marking the public RFC 6238 test vector; private environment/ignored local files were excluded |
| Committed-history secret scan | Three possible credential matches in an old environment backup; fully redacted reports, no secret values displayed |
| Browser | Wallet withdrawal dialog and account-security navigation worked under the strict script policy; no CSP console errors; French selection translated the security interface immediately |
| Windows backup scripts | Both passed PowerShell syntax parsing; neither was run with owner credentials |

## Unresolved owner/infrastructure items

The owner said the historical credentials are uncertain and will check/replace them privately. The candidates are in `.env.local-postgres-backup`, commit `21224bb50d540766a2bc06ea27994c80e494f832`. Treat genuine values as exposed until revoked. No history was rewritten, and the findings were not suppressed.

The unpatched high [braces advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) remains in Tailwind development dependencies. The documented Render Python/static build does not install this npm package. Do not expose developer tooling or accept untrusted build patterns. The new audit workflow intentionally flags this finding rather than reporting a clean scan.

Dashboard MFA is still owner-controlled and unverified. Origin protection, external alert delivery and actual scheduled encrypted backups still require private configuration. No offsite backup destination, immutable external audit archive or full managed IDS has been activated. Review [SECURITY_OPERATIONS.md](SECURITY_OPERATIONS.md) before deployment and complete staging checks, owner MFA enrollment and verified backup setup. Production restoration and live payment settlement were not tested by this work.
