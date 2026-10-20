# GameArena: proposed Ireland → Oregon database migration

Prepared 20 October 2026. This is a preparation plan, not a completed migration. The current Render web service was confirmed in Oregon. The masked runtime database hostname identifies Supabase Ireland (`eu-west-1`). The intended target is specifically **West US (Oregon), `us-west-2`**; a general Americas selection may choose a different region.

## Expected benefit and limits

Putting the web process and its database in Oregon should reduce geographic distance between them. Actual benefit must be measured using the same routes and comparable database resources. Separate providers in the same region do not automatically share a private network. This does not stop a Free Render web service sleeping, increase its CPU/RAM, or guarantee a faster experience than a European deployment for every player's location.

## Preparation before touching production

1. Owner creates a new empty Supabase project in the specific Oregon region, checking any project charges first. Keep the Ireland project running. Enter passwords privately; do not send connection strings, API secrets, encryption keys or recovery codes through chat.
2. Inventory the **live** configuration without revealing values: local vs Supabase Auth, avatar Storage, extensions, custom policies/triggers, Realtime, database webhooks, and every process that connects to the database. The repository supports optional managed Auth and Storage; their presence in code does not prove they are enabled live.
3. Record the running application version. Do not combine this move with the pending security/tournament feature deployment: validate the database against the version currently serving players.
4. Create a verified encrypted source backup and prove restoration on an isolated target. The existing `scripts/backup_database.py restore` command is deliberately restricted to empty `gamearena_restore_...` drill databases. **It is not a general Supabase-to-Supabase migration command** and must not have its guardrails bypassed.

## Rehearsal and comparison

Use Supabase's supported migration procedure, accounting for managed schemas and configuration. If Auth or Storage is used, plan their data/settings and file transfer separately rather than assuming a public-schema export copies the complete project. Preserve IDs, constraints, policies, sequences, role permissions and migration history. Handle any Vault/encryption requirements privately using the provider's documented procedure.

Restore into the new project first. Compare table counts and primary keys; reconcile each player's GP balances and wallet components, transaction references/statuses, fee records, pending payments/transfers and tournament entries. Check foreign keys, sequences, ownership and backend-only access restrictions. An equal total balance alone is insufficient evidence that all accounts are correct.

Use an isolated preview with payments, outgoing email, push notifications and workers disabled. Verify sign-in, profiles, tournament reads and authorization using controlled test accounts. Measure repeated server/database timings for the same requests against source and target; distinguish database time from client-network time and cold starts. Do not make test deposits, entries or withdrawals against cloned real accounts.

## Controlled cutover

Schedule a window outside active matches and payments. Stop player writes and background writers on the old database, account for payment callbacks/webhooks, and reconcile provider events during the window. A browser maintenance page alone does not pause all writers. Take the final consistent copy after the freeze, restore and validate it, then privately update all applicable runtime/migration/Auth/Storage settings and restart/redeploy the existing Oregon web service. Preserve application encryption/signing keys where needed to read existing encrypted records; do not rotate them casually during this move.

Smoke-test and reconcile before reopening writes. Confirm all workers use the new database. Prevent both copies receiving production writes. Retain the old project and verified backup until recovery is proven. If the target has already accepted writes, rollback requires reconciling those new records; merely restoring the old connection string can lose transactions. Do not delete either project during preparation.

## Current status

- Target project creation: awaiting owner confirmation.
- Production backup, data copy, comparison and cutover: **not performed**.
- Production settings, accounts and billing: **unchanged**.

Sources: [Supabase region selection](https://supabase.com/docs/guides/platform/regions), [changing a project region](https://supabase.com/docs/guides/troubleshooting/change-project-region-eWJo5Z), [supported backup/restore procedure](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore).
