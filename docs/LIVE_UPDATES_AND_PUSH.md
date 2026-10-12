# Live activity, search and device notifications

The activity page subscribes to a private admin Socket.IO room. A committed daily
visit and new inbox notifications invalidate the dashboard. It refetches private,
uncached HTML with a 250ms debounce, reconnect/foreground resync and a 15-second
reconciliation interval for missed events, registrations and calendar rollover.
No page refresh is needed. Ordinary users cannot join the admin room or fetch
its live endpoint. The existing distinct-player and historical-coverage rules remain.

Search progressively queries after two characters and 250ms of idle typing.
Requests are cancelled and versioned so older results cannot overwrite newer
input. It reuses the full-page search's public-profile and suspended-user filters,
includes avatars/initials and never exposes email or account secrets. The normal
GET form still works without JavaScript. Results are capped at eight per section.

Web Push uses the existing standards stack: service worker, Push API, VAPID and
pywebpush. Socket.IO is only for connected clients. Device delivery is queued via
RQ when configured, otherwise starts a background delivery task. It rechecks the
recipient, read status and notification preferences, and removes expired endpoints
on provider 404/410 responses. Settings includes an explicit opt-in, opt-out and
self-only, CSRF-protected, rate-limited test notification. A queued test is not a
provider delivery guarantee. Browser/OS permissions, connectivity and hosting
availability still affect delivery. iOS/iPadOS require a supported version and
launching the app from the Home Screen before opting in.

Owner-managed keys (never disclose them to the assistant):

    python -m pip install -r requirements.txt
    python scripts/generate_push_keys.py --contact jegzdami@gmail.com

The owner opens `.local-test/webpush.env` privately and copies VAPID_PUBLIC_KEY,
VAPID_PRIVATE_KEY and VAPID_SUBJECT into Render Environment. The private key must
remain server-side; it is never returned by the app. Do not rotate existing keys
without planning subscription renewal. The directory is ignored by Git. No key
file is read, generated or uploaded by this implementation/testing workflow.

After deployment, open Settings on the actual phone, enable notifications and
press Send test notification. Then close the GameArena app/tab and have another
account send a direct message. Verify the phone receives an OS notification and
its tap opens the correct GameArena page. Mocked automated tests do not replace
this final device/provider check.
