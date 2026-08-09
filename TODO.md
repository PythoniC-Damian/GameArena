# TODO — Fix Community Chat 500 Error (Internal Server Error on /chat)

## Goal
Fix the Internal Server Error (500) on the community chat (/chat) caused by orphaned
GlobalChatMessage rows referencing deleted/missing users (present in production Postgres),
and harden the code against future orphaned data.

## Steps
- [x] 1. Harden `app.py` `/chat` route to filter out messages whose `user` is None
- [x] 2. Harden `templates/chat.html` loop to never crash on a None user (safe fallback)
- [x] 3. Add cleanup script (`cleanup_orphaned_chat.py`) to delete orphaned chat rows
- [x] 4. Verify with test_chat_fix.py (no regression) and syntax checks (SYNTAX_OK)
- [x] 5. Commit and push to main (commit b1faba6, triggers Render auto-deploy)
- [ ] 6. Run cleanup_orphaned_chat.py against the production Postgres DB (with DATABASE_URL set)
- [ ] 7. Confirm /chat returns HTTP 200 after deploy

