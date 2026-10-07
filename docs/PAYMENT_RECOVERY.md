# Payment confirmation and recovery

Paystack success and a pending GameArena entry are separate states until the
server validates and applies the transaction. Never ask a customer with a
successful transaction to pay again as a recovery procedure.

The live webhook is `https://gamearena01.com/paystack/webhook`. Its handler
authenticates the raw payload using Paystack's HMAC SHA-512 signature.
The browser callback verifies the reference with Paystack's server API.

An earlier checkout reference can be replaced by a retry. Recovery therefore
uses the user and tournament IDs in trusted Paystack metadata when an exact
reference lookup fails. Customer email alone is never sufficient. The handler
checks successful status, currency, the entry's quoted amount, and reference;
wallet deposit references cannot be reassigned to tournament entries.

Paystack may charge the requested entry amount plus its fees. Verification
requires the requested amount to match the entry price when supplied, and the
charged amount to equal that price or exactly that price plus provider fees.
It does not accept arbitrary overpayments or underpayments.

Retries check the currently saved reference for success before opening another
checkout and retain the entry's quoted price. Confirmation atomically changes
one pending entry to paid. Repeated callback/webhook delivery cannot grant a
second entry or wallet credit.

## Recover an existing payment after deployment

1. Verify its successful status, requested amount, fees and reference in the
   live Paystack dashboard. Check that the deployed app uses this integration's
   live secret key; a test key cannot verify a live transaction.
2. Deploy the repaired payment code. Configuring a webhook does not itself
   change the deployed application or repair earlier entries.
3. Have the owner of the entry sign in and open
   `https://gamearena01.com/verify-payment?reference=TRANSACTION_REFERENCE`.
   This invokes server verification and checks entry ownership. A successful
   transaction with missing or inconsistent metadata requires investigation;
   do not bypass verification or manually mark it paid based on a screenshot.
4. Confirm the entry shows paid. Check future webhook deliveries. A newly
   configured webhook does not guarantee replay of historical transactions.

Regression tests live in `test_payment_recovery.py` and
`test_checkout_screenshots.py`; they use an isolated PostgreSQL database.
