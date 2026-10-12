# Player activity dashboard

Open `/admin/activity` while signed in as an administrator, or use the activity
link in `/admin`. Shows registered players, unique active players today, during
the last seven calendar days and during the last 30 calendar days; daily chart,
accessible daily values and player names with last active date and active days.
All day boundaries use Lagos time (UTC+1), including today.

One player counts once per day and once in the 30-day total, regardless of the
number of visits or messages. Activity includes signed-in document visits,
successful player form actions, sent chat messages and tournament entries.
Automatic GET polling, assets, push/read endpoints and admin accounts are excluded.
Recipients are not counted simply because another person messaged them.

Prior browsing/login history was not recorded. Historic days use existing chat
and entry records only and may undercount visitors. Zero means no observed
activity. The coverage limitation appears on the page. Deleted users cease to
contribute; pending tournament entries count as observed activity, not revenue.

Daily visit tracking writes at most one row per player per day, uses a signed
session marker to avoid repeated writes and a conflict-safe database key for
concurrent devices. A separate transaction avoids committing application work.
Tracking errors are logged and never fail the original user request.

The migration creates `user_activity_day` and restricts browser/API access with
RLS and revoked client grants. It stores only user ID and day, not URLs, IPs,
message contents or device identifiers. The privacy policy describes this use.
No third-party analytics service or paid dependency is added. Apply the migration
through the existing deployment command before launching the updated app.
