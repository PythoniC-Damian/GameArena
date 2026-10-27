# Privacy controls and compliance handoff — 27 October 2026

## Implemented
- Adult-only account policy. Email signup validates a transient birth date; new Google/Supabase identities require the signed, ten-minute signup declaration. Existing accounts, including administrators, must confirm adult eligibility before ordinary account use. HTTP and socket mutation checks apply. No birthday or identity document is stored. This is self-declared age assurance, not verified identity.
- Underage/unconfirmed users retain access to support, account requests and exports. Existing balances and financial records are preserved; support must review closure/refunds individually.
- Signed, HttpOnly, SameSite device choice lasting at most 180 days; Secure over HTTPS. Optional first-party visit/funnel analytics default off. Equal accept/reject controls, a footer preference route and CSRF-protected no-JavaScript forms allow withdrawal. Rejection deletes the signed-in user's optional visit records without deleting operational records. Cookies contain only policy version and analytics choice; no birthday.
- Optional visit records expire after 90 days through daily opportunistic cleanup on requests, with an hourly retry after failure. The explicit `flask --app app purge-usage-data` command performs the same cleanup. No payment, dispute, chat or tournament-entry data is purged by this function.
- Policies identify GAMERENA NEXUS TECHNOLOGIES LTD, public support wegamearena@gmail.com and owner-authorized privacy contact jegzdami@gmail.com. Terms describe adult-only access; data export includes the declaration timestamp/version. No invented registration number, address, transfer approval or professional certification.
- Migration `20261027_privacy_age` follows `20261027_waiting_list`; it adds nullable declaration columns without backfilling existing users as adults. Release startup must run the existing migration command before serving the new code.

## Validation
The initial signup/auth/privacy/legal run passed 28 tests and exposed four test-fixture issues following the deliberate age-policy change (missing birthday/preflight and an incorrect test import). After correcting those fixtures, all 13 focused privacy, signup and consent-aware reporting tests passed. Mobile preview at 390px had no horizontal overflow; both cookie actions were visible and rejection remained saved after reload. No live accounts, payments or provider settings were changed during testing.

Legacy authentication tests disable only the new HTTP age gate for pre-existing fixture accounts; the dedicated tests explicitly enable it and verify admin gating, financial POST rejection and socket authorization. Signup birth-date validation always remains active. Existing activity/funnel tests explicitly opt into analytics.

## Owner/professional work still required
1. Supply the company's public contact address in `GAMEARENA_PUBLIC_CONTACT_ADDRESS`. Verify the exact registered company name and any identifiers before publication. The spelling above is the owner's supplied spelling.
2. Engage a licensed Nigerian data-protection compliance organisation or qualified counsel. Determine NDPC classification, registration/audit and DPO duties; keep their assessment and filing evidence. No adviser has been contacted or hired by this code change.
3. Review age assurance for paid events. A self-declared date is not documentary proof or a guarantee of compliance. Assess additional verification if risk or applicable rules require it; do not collect identity documents ad hoc in chat.
4. Review Render, Supabase, Cloudflare, Google, email/push and Paystack contracts, subprocessors and locations; document applicable overseas-transfer mechanisms. A privacy notice is not a substitute for those safeguards.
5. Approve and implement a category-specific retention schedule for financial, incident/security, support and dispute records, deletion holds and backups. Only optional activity/funnel retention is automated here. Do not invent a statutory retention period or erase required financial evidence.
6. Audit live browser requests and dashboard-injected Cloudflare/other scripts. The implemented choice controls GameArena's own optional analytics; it does not magically block third-party tracking added outside this repository. Ensure any such optional tooling waits for appropriate consent.
7. Record processes for privacy requests, marketing consent/unsubscribe if promotional emails are introduced, and incident response. Review paid-tournament/wallet obligations and payment-provider approval separately.

These changes reduce identified gaps; they are not a legal certification or assurance against fines.
