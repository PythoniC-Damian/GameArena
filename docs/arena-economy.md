# GameArena GP, shop, languages and organiser tools

GP is a fixed internal credit, not cryptocurrency. 100 GP = NGN 100. Existing
integer-naira ledger values, provider references, pending transfers and bank
payouts are preserved; only the GP denomination changes. Whole GP inputs avoid
rounding away customer money. Bank checkout and withdrawals explicitly show NGN.
This release does not add international acquiring, executable bank FX conversion or foreign payouts.

## Balances

- Purchased GP: existing withdrawable wallet balance less tracked wallet winnings.
- Winnings GP: a tracked subset of the withdrawable balance; initially zero.
- Bonus GP: separate credits, usable for cosmetics only, never withdrawable or
  usable for paid tournament entry.

Existing balances remain entirely withdrawable. Existing prizes paid directly to
banks are not double-credited as wallet winnings. This release does not mint
historical winnings, grant bonuses or move bank prize payouts into wallets.
New funded organiser events now provide an audited wallet-prize source; historical prizes are not credited again.
Tournament/shop cash spends consume purchased GP first, then winnings. Wallet cards withdraw only from the selected Purchased or Winnings source; legacy clients keep combined spending. Withdrawals persist the
winnings portion and restore the original allocation on a conclusive failure.
Fees stay at 1%, capped at NGN200. Provider requests remain NGN kobo.

## Arena Shop

Four permanent first-party profile frames: Arena Origin (free), Neon Circuit
(200 GP), Solar Crown (400 GP), Ember Core (600 GP). A purchase requires a visible
price confirmation and is atomic under the user's wallet lock. Duplicate and
concurrent purchases do not charge twice. Bonus GP is spent before cash.
Ownership survives Master expiry. Equipping validates ownership; removing a
shop frame restores the standard/current Master frame. Purchases have authentic
wallet receipts and appear in history and exports. No game publisher items,
player-to-player trading, loot boxes or competitive advantages are sold.

## Organiser Studio

Signed-in organisers save and edit private drafts, set GP amounts, format/rules,
capacity and UTC schedule, then submit for platform review. Only an unsuspended
administrator can publish, after explicitly checking rules, publisher permissions
and prize funding. Approval creates one normal GameArena tournament. Repeated
approval cannot publish duplicates. Published-event participant CSV exports are
restricted to the owner/platform administrator; emails/bank details are excluded.
Existing admin tools manage rooms, brackets and final results. New publication requires
verified email, an approved contact (manually verified by an administrator), good
standing, and explicit acceptance of organiser rules v1. Agreement version and UTC
acceptance time are stored. Drafts are free, bounded to 30 active events per owner;
mutations are limited to 20 per minute per account. Lists are bounded.

Publication atomically reserves the entire advertised prize from cash GP under
the host wallet lock. Bonus GP is never eligible. Insufficient funding leaves the
event unpublished and uncharged. New funded events accept GP entries only; players
can top up via Paystack. This makes entry refunds source-preserving and avoids
uncertain bank-refund promises. Historical published events are not retrofitted.

An administrator finishes the event using existing tournament controls, then
opens Studio > Funded events > Review settlement. Supply registered player IDs
and whole-GP allocations, plus an evidence/decision note and confirmation. Prizes
must total the funded pool; unresolved match disputes block settlement. This is
human-reviewed, not automatic COD result verification. Prizes are credited once
to Winnings GP. Recorded or pending legacy bank prize payouts block wallet credit.

The platform fee is 500 basis points (5%) of completed, non-refunded entry revenue,
rounded DOWN to whole GP. The organiser receives the remainder in Winnings GP;
the reserved advertised prize is paid in full. Free-entry events have zero revenue
fee. Financial records retain revenue, fee, source allocation, reviewer, time and
note. Unique wallet references and tournament/finance/user locks prevent duplicate
settlement. Owner-scoped receipts/CSV show authentic prize, reserve, income and
refund records with the correct incoming/outgoing direction.

Cancellation uses the same locked financial close: paid entries return to their
original Purchased/Winnings sources, the host reserve is restored, and no platform
fee is charged. Unreconciled entry records or pending external payments block close.
Completed/refunded events cannot be reopened or repaid. Admin edits cannot change
funded prices/prize/capacity or bypass the cancellation process. Rejected events
were never funded and have no platform fee.

## Languages

English, Spanish, French and Portuguese are available from the shared menu/footer
and Settings. Selecting a language submits immediately; no Apply click is needed (a noscript fallback remains). Guest choice is saved in the signed session; account choice is saved
server-side and used on subsequent visits. Core navigation, discovery, account,
wallet, shop and organiser text has local translation catalogs. No external AI
translation calls or translation API charges. Usernames, player chat, event names,
organiser rules and legal documents remain in their original language. Some older
feature descriptions and provider errors fall back to English. Catalogs live in
gamearena/locales; interface strings are explicitly marked with t() rather than
translating rendered user content. Legal translations require separate review.

Run scripts/migrate.py before starting the new code. The additive Alembic migration
adds source-tracking columns, saved language and private inventory/draft tables,
then applies backend-only RLS. Never reverse balances to change GP display units.

## Currency display and match-value quotes

GP is the default saved wallet display currency. The shared wallet/history selector
uses only current ISO fiat codes for which the source provides a rate. The ISO
list is pinned to the SIX publication date recorded in gamearena/currencies.json.
Update that list as ISO codes change. A live check returned 154 supported fiat
rates out of 155 ISO fiat entries; unsupported currencies are not fabricated.

GET /api/exchange-rates fetches the public ExchangeRate.fun USD feed and normalizes
it to NGN (1 GP = NGN1). It validates positive finite rates, expected base, required
currencies, at least 130 supported fiat codes and a source timestamp no older than
two hours. Requests have connection/read timeouts. Cache freshness is one hour,
with a process lock coalescing concurrent fetches and optional shared Redis backing
through CACHE_REDIS_URL. Multiple cold processes can each make one request before
the shared cache fills. Failed fetches are throttled for 60 seconds. Last-known
data can be shown for up to 24 hours with a stale flag, never as a fresh quote.
No new private API key or paid provider signup is needed for this public feed.
Source reliability is external; the timestamp and stale status are shown in UI.

POST /wallet/display-currency saves the authenticated account's preference, with
CSRF protection. Other currencies are indicative displays: stored balances, GP
prices, original receipt data and provider NGN requests remain unchanged. Deposit
inputs and actual bank-payout confirmation retain explicitly labelled NGN values.
History CSV retains original accounting values rather than current display FX.

POST /api/match-value-quote accepts a decimal amount and ISO currency. Fresh source
rates calculate the GP value server-side, rounded UP to a whole GP so the quoted
amount is not underfunded. The signed quote is bound to the account and expires
in five minutes. verify_match_quote verifies signature, owner and expiry. Future
match creation must consume this quote and hold the fixed GP amount atomically;
never trust a client-side currency amount or recalculate matched stakes at payout.
The wallet calculator previews this flow. It does not create wager matches, reserve
funds or launch the previously discussed future individual matchmaking feature.

Production access check: ExchangeRate.fun returned HTTP403 from Render. The code
therefore includes the public CC0 Currency API daily USD feed via jsDelivr, then
its documented Cloudflare mirror. UI identifies this DAILY fallback and preserves
its published UTC date. Daily snapshots have a 48-hour maximum source age; older
snapshots are rejected. Both sources use the same one-hour cache. Quotes are
indicative fixed GP values from the explicitly identified source, not executable
bank FX offers. A provider accessible from Render is required for hourly source
updates; refreshing the fallback hourly does not make its daily data hourly.


## Wallet layout and performance (October 16 follow-up)

Purchased, Winnings and Bonus are horizontally swipeable cards, with keyboard,
dots and previous/next controls, a shared saved display currency and an eye that
masks all cards. Bonus offers the shop rather than a cash withdrawal. Detailed FX
source timestamps and fee explanations are inside Rates & fees. Daily/stale/outage
indicators remain visible, and withdrawals require an exact fee/payout confirmation.

Wallet entry totals and pending counts now share one aggregate query, avoiding a
DB round trip. Organiser state has a compound owner/status index, bounded lists,
a durable active-draft quota and database-backed mutation limits. Private wallet
pages and APIs are never cached publicly. Existing optional Redis cache, queue,
rate-limit and worker configuration remains in docs/STACK_UPGRADE.md; no paid
resource or hosting upgrade was applied. The proven single gevent worker and
NullPool remain unchanged. Capacity/TTFB gains require measurements on the actual
deployment; code-level changes alone are not a production scaling guarantee.


Validation for the follow-up: 10 organiser/source financial tests, 10 existing
Arena economy/locale tests, and 61 wallet/provider/FX/migration/asset regressions
passed (81 distinct backend cases). Chrome checks passed 32 combinations of four
languages, four pages and two widths, plus source selection, swipe/dot navigation,
balance privacy, native form language switching, FX outage fallback and NGN payout
display. Fixtures and mocked providers were local and synthetic; no live charge,
withdrawal, prize payout or paid hosting provisioning was performed. Windows pytest
plugin autoload was disabled for the successful regression run after a native
runner fault. Python/JS syntax, stylesheet fingerprints and git diff checks passed.
Production deployment is tracked separately from these local validation results.
