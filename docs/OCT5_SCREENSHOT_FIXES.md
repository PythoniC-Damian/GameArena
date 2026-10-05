# Screenshot fixes — 5 October 2026

- `static/css/themes.css`: constrain the profile file picker and long text to the card. Display complete carousel images with `object-fit: contain`, rounded edges, and hero copy beside the image on desktop or below it on mobile. Automatic rotation is retained.
- `static/js/payment.js`: submit the actual CSRF-protected form, handle non-JSON/session failures, validate checkout links, and recover the button after errors.
- `app.py`: require a successful Paystack response and a valid HTTPS checkout link before recording a pending entry; roll back failed retries, distinguish timeout and invalid-response failures, and log safe failure categories without keys or payment payloads.
- `test_checkout_screenshots.py`: isolated payment initialization and rollback checks. `test_notification_flow.py`: existing mocks now include HTTP status.

## Validation
Eight backend tests passed against an isolated local PostgreSQL database. Five simulated payment-client checks passed. Python compilation, JavaScript syntax, and `git diff --check` passed. Existing deprecation warnings remain.

Browser control timed out twice. Fresh screenshots, responsive visual checks, and the native iPhone file-picker check could not be completed. No real payment was made. The exact reason for the live Paystack rejection remains unconfirmed; live provider/service logs are needed to identify configuration or provider failures. These code changes have not been pushed or deployed and do not establish that live checkout now succeeds.
