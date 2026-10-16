# Wallet, organiser and dependency review — 16 October 2026

Scope: source review of wallet deposits/withdrawals, entry payment, receipts/CSV,
organiser approvals/funding/settlement, FX display, HTML rendering and request
security configuration. Published advisories were checked through OSV for all
24 exact Python requirement pins. After updating, the isolated full requirements
resolution contained 59 packages; OSV returned no matches for those resolved
versions. This was a Windows test resolution, not a scan of the live Linux OS. No production attack traffic, real payment,
secret-file inspection or external penetration test was performed.

## Findings and changes

- Withdrawal requests had no dedicated HTTP abuse quota. Added a durable account
  limit of 5 attempts/minute before provider work. Forwarding-header changes do
  not reset the account quota, and unrelated accounts behind a shared proxy do
  not consume each other’s withdrawal quota.
  Entry mutations now have a separate 20/minute account limit. Existing account
  resolution, checkout, authentication and organiser quotas remain.
- Several financial JSON handlers assumed an object and raised server errors for
  arrays/booleans/strings. They now reject non-object payloads with HTTP 400.
  Legacy integer amounts are bounded before conversion or provider calls.
- Added a 5 MiB whole-request cap, allowing the existing 4 MiB profile image limit
  plus multipart overhead. Oversized bodies return HTTP 413. Images still undergo
  actual image decoding, dimension checks and normalization; filenames are not trusted.
- Free-entry confirmation GETs unnecessarily acquired a tournament write lock.
  They now read without that lock; POST capacity checks remain serialized, and
  unsuccessful exits release their locks.
- Four old dependency pins had published advisories; upgrade targets were checked
  against PyPI and OSV before testing:

| Package | Previous | Updated | Relevant primary advisories |
| --- | --- | --- | --- |
| Flask | 3.0.0 | 3.1.3 | [session cache variation](https://github.com/pallets/flask/security/advisories/GHSA-68rp-wp8r-4726) |
| Werkzeug | 3.0.1 | 3.1.9 | [multipart resource exhaustion](https://github.com/pallets/werkzeug/security/advisories/GHSA-q34m-jh98-gwm2), [Windows path handling](https://github.com/pallets/werkzeug/security/advisories/GHSA-g6x2-hccm-hh4m) |
| Requests | 2.32.3 | 2.33.0 | [netrc credential leakage](https://github.com/psf/requests/security/advisories/GHSA-9hjg-9r4m-mvj7), [temporary-file reuse](https://github.com/psf/requests/security/advisories/GHSA-gc5v-m9x4-r6x2) |
| python-dotenv | 1.0.0 | 1.2.2 | [symlink handling](https://github.com/theskumar/python-dotenv/security/advisories/GHSA-mf9w-mj56-hr94) |

An affected dependency version does not establish exploitation. For example,
production runs on Linux with the debugger disabled; dotenv is used for reading,
and reviewed provider request URLs are server-controlled. The framework form
parser and session behavior are directly relevant enough to patch regardless.
Advisory aliases (GHSA/PYSEC/CVE) are not separate independent vulnerabilities.

## Controls reviewed

Private receipts and history filter by the signed-in owner; organiser editing
requires ownership, review/settlement requires an administrator, and publishing
rechecks eligibility and full cash prize funding. Fees and GP values are server
calculated; display FX never changes ledger balances. Signed bank verification
is account-bound and expires; Paystack webhooks use HMAC verification. Financial
close uses row locks and unique references, rejects unresolved disputes/existing
payouts, and preserves Purchased/Winnings allocations on refunds. Bonus GP cannot
fund entries, cash prizes or withdrawals. CSRF remains enabled on mutations;
provider webhook exemption is protected by its signature.

Reviewed player text is Jinja-escaped; live search/activity/connection HTML comes
from those same-origin templates. Receipt export draws plain text to canvas.
CSV exports escape formula-leading user text. No SQL string concatenation of
wallet inputs or unescaped player-text rendering was found in the reviewed paths.
Production cookie flags and private cache headers remain configured.

## Limits and follow-up

This is a targeted review, not proof of absence of vulnerabilities. Infrastructure,
secret quality/rotation, live Supabase grants, hosting configuration and game-result
fraud require separate operational checks. Existing CSP still permits inline
scripts/styles; moving inline handlers to external code and introducing nonces
would strengthen XSS defense. Dependency results are a point-in-time advisory
check, not an assessment of every OS/container package or all reachable code.
Manual result review remains required for prize settlement.


Deployment IP follow-up: existing authentication IP buckets use the observed
socket peer. [Render documents that this is normally its proxy address](https://render.com/articles/how-render-handles-ddos-attacks).
A trusted, validated forwarding-chain configuration should be established before
relying on those existing buckets as independent per-visitor controls. The new
withdrawal and entry limits are account-bound, so they do not depend on proxy
identity or trust arbitrary client-supplied forwarding headers. Account-level
login limits also remain enabled. No proxy hop count was guessed in this release.


## Validation completed 17 October

109 distinct server cases passed across compatibility and focused reruns using
an isolated install of the exact release requirements. Coverage included money
conservation, repeat transfers, malformed/oversized requests, CSRF, per-account
withdrawal limits and shared-proxy isolation, authentication/recovery, private
messages, uploads, push permissions and asset behavior. Three older expectations
were aligned with the existing GP display and accepted-player conversation rules;
production consent protections were preserved. Chrome checks passed 32 localized
responsive views and verified hidden phone arrows with desktop arrows retained.

The 59-package resolved Python set returned zero advisory matches in the OSV
query. Python/JavaScript checks, stylesheet fingerprints and diff checks passed.
Filename-only Git checks found no tracked .env, .key or .pem files; private key
contents were not inspected. This does not inspect repository history or attest
to the strength of production secret values.
