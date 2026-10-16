# GameArena GP, shop, languages and organiser tools

GP is a fixed internal credit, not cryptocurrency. 100 GP = NGN 100. Existing
integer-naira ledger values, provider references, pending transfers and bank
payouts are preserved; only the GP denomination changes. Whole GP inputs avoid
rounding away customer money. Bank checkout and withdrawals explicitly show NGN.
This release does not add international acquiring, FX quotes or foreign payouts.

## Balances

- Purchased GP: existing withdrawable wallet balance less tracked wallet winnings.
- Winnings GP: a tracked subset of the withdrawable balance; initially zero.
- Bonus GP: separate credits, usable for cosmetics only, never withdrawable or
  usable for paid tournament entry.

Existing balances remain entirely withdrawable. Existing prizes paid directly to
banks are not double-credited as wallet winnings. This release does not mint
historical winnings, grant bonuses or move bank prize payouts into wallets.
Future funded wallet-prize/bonus award workflows need an audited credit source.
Cash spends consume purchased GP first, then winnings. Withdrawals persist the
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
Existing admin tools manage rooms, brackets and final results. Studio pricing,
organiser revenue sharing and automated prize escrow are not enabled.

## Languages

English, Spanish, French and Portuguese are available from the shared menu/footer
and Settings. Guest choice is saved in the signed session; account choice is saved
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
