# GameArena 1v1 competition flow

COD Mobile and eFootball organisers can publish a single-elimination format before accepting entries. Supported capacities: 2, 4, 8, 16, 32, 64 and 128. Existing custom events retain their format. Start with a small free pilot.

## Operating an event

1. An approved organiser creates the event draft and uploads three images; platform staff review publication and prize funding.
2. Open the published event and publish its mode, map/settings, winning score, tie, no-show and disconnection rules. This format cannot be added after eligible players have entered, or changed once published.
3. Open check-in with an explicit UTC deadline. Registration closes. Entrants confirm their own in-game ID and accept the rules. IDs are self-reported; duplicate normalized IDs are rejected within the event.
4. Draw the bracket only when every eligible entrant is checked in, pending payments are reconciled, no entrant is suspended and the field is a power of two. Before the deadline the field must also be full. Otherwise extend check-in or use the established reviewed cancellation/refund flow; do not discard entrants.
5. Player one of each pairing hosts the private room in the actual game. Room details remain private to the assigned players and platform staff. Both players join and mark ready before reporting scores.
6. A player reports both final scores, a consistent winner and screenshot evidence. Only the opponent can confirm. A dispute or reported no-show pauses the match. The admin panel links to a paginated competition review queue.
7. Independent platform staff record an evidence-based decision under the published rules. They can confirm a participant as winner or reopen with a fresh room/readiness step. They cannot adjudicate their own match. Previous evidence versions remain private and retained.
8. Once all matches in a round are confirmed, winners advance once. The final marks the competition finished. Financial settlement remains the separate admin-reviewed GP process; no result confirmation initiates a bank transfer.

## Boundaries

GameArena coordinates play; it does not create publisher rooms or connect to an official game-result API. Scores, IDs and screenshots are player evidence, not proof of authenticity or publisher verification. Battle royale scoring and byes are outside this version.

The public guide is `/tournaments/guide/1v1`; matching guidelines and each event's actual rules appear on its detail page. Interface guidance is available in English, Spanish, French and Portuguese. Player-authored rules are retained in the organiser's original language.

## Implementation and validation

Four new backend-only tables store configuration, check-in, lobby state and private evidence. The migration secures only those tables; it does not re-lock existing financial tables. Evidence accepts decoded JPEG/PNG/WebP up to 4 MB and 12 megapixels, strips metadata and preserves the full scoreboard aspect ratio, with a maximum of 1600 pixels per side. Ten evidence versions per player/match are retained. Images are stored durably in the application database; account for storage as event volume grows.

Mutations lock the tournament before the match. State checks reject late or duplicate changes. Socket.IO subscriptions require an eligible membership or approved organiser/platform role; broadcasts contain only a tournament ID. Private status polling provides recovery and never returns room credentials. Updates preserve unfinished forms. Changes to closed competitions are rejected.

Regression coverage includes a four-player tournament through the final, concurrent draws, private rooms/evidence, CSRF, deadline and payment gates, score/winner consistency, no-show review, replays, independent staff decisions and migration grants. Browser checks cover phone/desktop layouts, translated screens and preservation of unsent input on live updates.
