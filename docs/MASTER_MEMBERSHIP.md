# Master local release

Master includes membership badges, avatar frames, profile surface themes, 30-day recorded performance, saved tournaments and start reminders. Grandmaster and Legendary are future tiers. Default application light/dark mode remains free; the premium theme is a cosmetic profile accent.

The owner selected NGN 2,300/month with automatic renewal. Paystack checkout, verified activation, recurring invoice reconciliation, payment-method management and cancel-at-period-end are implemented. Checkout remains off by default: no live plan, charge or membership grant has been created during this work. Entitlement is the server-owned `User.master_expires_at`; there is no public endpoint granting or extending it. Expiration hides premium cosmetics and prevents premium writes while preserving bookmarks and allowing their removal.

## Local test

Run `python scripts/migrate.py` against the existing loopback preview .env, then `python scripts/preview_master.py`, and restart `python app.py`. Sign in as `preview@example.com` with the previously configured demo password `GameArenaPreview2026!`. Open `/pro` or Account menu > GameArena Pro. The demo setup refuses external databases and production. It does not change real accounts.

## Reminders

`python scripts/master_reminders.py` is intended to run every minute in a scheduler. Bookmarks produce a preference-aware notification once within an hour of a future tournament start; no registration deadline is inferred. No scheduled date means reminders cannot be enabled. Rescheduled events may produce a new reminder. Inactive memberships, suspended accounts and finished/cancelled events do not receive reminders. Row locks and a transaction keep reminder markers and notifications atomic. Run the script locally for testing; production scheduling has not been changed. Background Socket.IO delivery needs the existing shared Redis message queue; notifications remain in the inbox without it. Push uses the existing configured provider.

## Deployment later

Apply the additive `20261010_master_membership` migration before serving new code. No existing users are automatically enrolled, no wallet/payment records change, and the legacy messaging migration stays intact. Do not deploy until the owner has tested and authorized release.

## Paystack activation after local review

Use a Paystack monthly NGN plan for exactly 230000 kobo with no finite invoice limit. Configure `PAYSTACK_MASTER_PLAN_CODE`, the existing secret key and secure `PUBLIC_BASE_URL`, then set `MASTER_BILLING_ENABLED=1` only when ready. The app verifies the plan price/interval before checkout. Existing signed `/paystack/webhook` handles membership events alongside tournament/wallet events; do not replace the existing webhook URL. Only card checkout is requested for this first recurring-billing version. Checkout requires explicit recurring consent. Cancel requires confirmation; paid access lasts until its expiry. No card numbers or authorization codes are stored. Paystack subscription cancellation tokens stay server-side. Membership billing records are separate from tournament entries and wallet balances.

Production preflight must exercise Paystack test-mode checkout, subscription.create, initial charge, successful/failed invoice.update and cancellation events, then enable the matching live plan when the owner authorizes deployment. Plan configuration and live testing have not been performed by this task. Monthly expiry follows Paystack's billing-date rule (days 29–31 move to 28). A callback checks the same reference as the webhook; duplicates cannot extend access again.

Paystack references: https://paystack.com/docs/payments/subscriptions/ and https://paystack.com/docs/api/subscription/.

For the Windows preview, the ignored local .env uses `SOCKETIO_ASYNC_MODE=threading` to avoid Eventlet websocket disconnect errors. Production retains its existing automatic async-driver selection unless explicitly configured.

## Validation

29 isolated PostgreSQL tests passed across Master benefits/billing, existing payment recovery, player requests and chat inbox. Paystack calls were mocked. Browser checks cover `/pro` and `/profile` at 360, 390, 768 and 1440 pixels, persistence after refresh, bookmark/reminder actions and JavaScript errors.

A broader 35-test run passed 33 checks and exposed two pre-existing failures in `test_product_updates.py`: the reply test assumes unrestricted messaging for newly created users, and the logout push-cleanup test posts without the required confirmation. Both failures reproduce on unchanged HEAD. Production behavior and these unrelated tests were not changed.


The homepage shows a dismissible Pro introduction once per browser session (also for visitors). On phones the three tier cards use native horizontal swipe scrolling; desktop shows the three columns together. Master links to the membership/payment section; active members manage their existing membership. Unconfigured checkout displays a disabled Subscribe button with an explanation. Grandmaster and Legendary remain explicitly planned and unavailable for purchase; no ad-free benefit is advertised while the app has no ad placements.
