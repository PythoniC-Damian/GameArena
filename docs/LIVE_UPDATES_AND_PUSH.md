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

## Public-key format errors

The settings endpoint now validates only the configured public key as an
uncompressed, 65-byte P-256 curve point. It canonicalizes surrounding quotes,
whitespace and Base64 padding. Invalid values are not returned to the browser;
only character/decoded-byte counts and a safe error explanation are returned.
No private-key file is accessed by the validation or tests. The browser also
checks the byte length before requesting notification permission. This improves
diagnosis; it cannot establish which value is active on Render until deployed.

## Default opt-in invitation

Signed-in users on supported browsers see a compact notification invitation on
normal pages when they have no subscription and have not refused permission.
Permission is requested only after they click Enable notifications. Later snoozes
the invitation for seven days on that browser/account. Refused permission is
respected. Settings always retains the explicit enable/disable controls.
Previously enabled subscriptions are linked automatically to the current account
without a new OS prompt, with a short per-tab cache to avoid a write on every page.
No existing notification preferences are overwritten and no private keys are read
by the assistant. Native browser consent cannot be silently granted by GameArena.

Notification clicks prefer an already-open matching page; otherwise they focus an
existing GameArena window before navigating it. A closed, rejected or null client
navigation falls back to opening a new window. Malformed/external targets fall
back to the notification inbox. Browser window-opening restrictions still apply;
the service worker update must be active before testing new clicks.

## iPhone and iPad onboarding

Browser-tab users on iPhone/iPad (including iPad's desktop-style identification)
get an install guide instead of a disabled Enable button. It explains Safari's
Share > Add to Home Screen, the Open as Web App option, launching the icon and
explicit notification permission. The same guide is always accessible from
Settings on these devices. The site-wide invitation respects the existing Later
snooze. It cannot automate Apple's Home Screen installation or permission prompt.

Home Screen mode is detected through navigator.standalone and display-mode.
Already-installed apps proceed directly to the existing opt-in workflow. Older
installed devices without Push support get an OS-version explanation instead of
being told to install again. No email/SMS sends or fallback subscriptions are
added by the installation guide. Confirm on a physical iPhone after deployment;
emulated browser tests verify UI branches, not actual Apple push delivery.
