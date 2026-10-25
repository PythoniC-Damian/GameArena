# Platform audit and controls — 25 October 2026

## Findings checked

A read-only live inspection of tournament 6 confirmed an open event with an expired structured date and a different date in its written rules. Repository inspection confirmed the single hardcoded featured collection, missing admin catalogue controls and tournament artwork inputs, ambiguous achievements, and the support/chat/notification usability gaps addressed here. No real payment, withdrawal, entry, result or prize settlement was submitted. The reported registered-player count and current Paystack merchant approval were not independently verified.

## Admin workflow

- Admin → Shop and site settings (`/admin/platform`) edits known item names, descriptions and whole GP prices, support contact, a public announcement, and the optional homepage Pro promotion. Existing ownership and ledger entries remain unchanged. Checkout rejects stale prices.
- Create tournament and Setup share fields for event name, format, rules, eligibility, placement prizes, payout method, UTC date and uploaded artwork. Creation requires 1–3 decoded JPEG/PNG/WebP images; editing may keep existing images. Organiser Studio still requires its existing three images.
- Leave the start time blank for **To be decided**. Unscheduled, expired or incomplete paid events cannot accept entry payments. Publish a future schedule, rules, placement amounts and payout method before taking entries. Accepted entry/payment history and drawn matches remain protected.
- GP-wallet prizes must use the funded Organiser Studio flow; selecting that label cannot create an unfunded wallet prize.

## Migration

`20261024_platform_controls` follows `20261021_shop_collections` and runs through the existing startup migration command. It adds event terms, private support replies and platform settings with backend table protections. It clears expired dates only for open events with no entries, matches or organiser finance records. It corrects the unused eFootball pilot's known dated rule text and hosting wording. It preserves all accepted event history. Reapplication preserves saved Shop prices. Production migration has not been observed yet.

## Player experience

All defined collection bundles appear as featured slides, advancing every four seconds with manual controls, pause, and reduced-motion support. Slides do not alter cosmetic selections. Checkout explains insufficient GP before submission. Profiles distinguish locked achievements and email verification. Notifications support category/unread filtering and pagination; historical malformed naira labels render correctly. Chat gains conversation search and UTC date separators. Registration and verification wording now reflect input requirements and page state. The homepage Pro popup is off by default.

Support provides private ticket history, statuses and replies with admin inline responses. Account settings offer a scoped JSON export and tracked data/closure requests. Closure requests require review; they do not immediately delete accounts or financial records.

## Verification

- Tournament launch/artwork/platform regression suite: 32 passed.
- Final platform audit rerun: 6 passed.
- Additional legacy bracket completion and Setup bracket creation regressions: 2 passed.
- Existing Shop and admin-entitlement tests passed; Node cosmetic preview tests: 3 passed.
- Python/JavaScript syntax and Git whitespace checks passed.
- Local browser checks: desktop collection controls and timed advance; 390px Shop and admin creation layouts without horizontal overflow. Preview data is synthetic and isolated from production.

## External work still needed

Render free-tier sleep requires an appropriate hosting plan; these edits do not upgrade compute. Paystack approval, live checkout/withdrawal availability, delivery of notifications and a full match-to-prize cycle still require controlled operational checks. Actual dates, eligibility, game rules and prize commitments must be supplied by the organiser; the application does not fabricate them. This is a verified set of product fixes, not a complete security or payment audit.
