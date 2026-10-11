# Policies and performance review

Local changes only; no deployment or hosting-plan change.

Public pages: /privacy-policy (alias /privacy), /terms-of-use (alias /terms), /faq. Footer links also appear on login, signup and support. Registration shows terms agreement text and links; this is not a versioned acceptance audit record and does not add a marketing-consent checkbox. The existing recurring billing consent remains mandatory.

Content reflects local/managed authentication, stored unencrypted chat records and soft deletion, optional public profiles, bank/payout records, Paystack verification, manual privacy/support requests, fair-play rules and NGN 2,300 automatic Master renewal. Future tiers are not sold. Refund requests are reviewed manually; no automatic refund/deletion workflow is claimed. The contact email defaults to the user-confirmed contact address jegzdami@gmail.com, overridable through GAMEARENA_SUPPORT_EMAIL. Confirm the operator's legal identity/address, monitored email, eligibility and refund operating rules before publishing; a locally dated policy draft is not a claim of legal certification. Privacy-rights wording was checked against the NDPC: https://ndpc.gov.ng/ and https://ndpc.gov.ng/download/nigeria-data-protection-act-2023 .

## Observed public comparison

On 11 October 2026, read-only HTTP inspection found Masterspred redirects to /community, serves Next.js assets from Vercel, and reports X-Vercel-Cache: STALE. GameArena reports Render behind Cloudflare and private/no-store HTML. Both use gzip. A fresh phone-size browser sample measured Masterspred TTFB 64 ms vs GameArena 1,586 ms; DOMContentLoaded 2,954 vs 3,085 ms; largest-contentful paint about 4,000 vs 3,920 ms. These are single samples on one network, not a universal speed ranking. GameArena Server-Timing reported app 1,144 ms, DB 378 ms. Render free instances may sleep: https://render.com/docs/free . No authenticated Masterspred features or private implementation were inspected.

## Adapted improvements

- Prepare and fingerprint the randomized hero image catalogue only for the homepage, rather than every rendered page.
- Native responsive 480/960 WebP choices for tournament cards, with the existing 960 fallback for non-optimized assets.
- Load subsequent carousel slides when selected instead of prefetching all visible carousels' second images immediately. Keep rotation, swipe, keyboard controls and reduced-motion behavior.
- Preserve initial server-rendered unread counts and connection controls; refresh on socket connection, live changes, foregrounding and browser history restoration. Avoid redundant fresh-page pageshow requests.
- Keep private account/payment/chat HTML out of public shared caches. Existing immutable fingerprinted assets and short-lived public JSON cache remain.

Matching Vercel edge response time would also require hosting/cache architecture choices. A framework rewrite alone cannot remove Render sleep or database round trips. No paid infrastructure or migration was activated.

## Sharing preview (unchanged)

Masterspred explicitly declares https://themasterspred.com/og/masterspred-social.jpg at 1200x630 with Open Graph and a large-image Twitter card. Live GameArena contains no og:image/Twitter image and supplies app icons instead. WhatsApp appears to fall back to an icon for the compact layout. The large card is rendered from a supplied social graphic, not an automatic live homepage screenshot; layout and cached previews are controlled by the receiving app. No GameArena image, icon or sharing metadata was changed. Specification: https://ogp.me/ .
