# Arena Shop collections

Deploy through the normal Render start command, which runs scripts/migrate.py first. Revision 20261021_shop_collections adds nullable cosmetic_card and cosmetic_nameplate columns to the existing user table. It retains frame settings, wallet balances and every CosmeticOwnership row. No new payment-provider setup is required for spending an existing GP balance.

The catalogue in gamearena/market.py is authoritative. Existing frame keys and prices stay supported. Bundles grant their components and a bundle ownership row in one transaction. A bundle costs the smaller of its listed GP price and the sum of unowned component prices. Purchasing a bundle does not equip it automatically.

Purchases hold a user row lock, verify the server-calculated price and confirmation, spend bonus GP first and then the existing cash/winnings accounting, create one completed cosmetic_purchase ledger record, and grant only unowned components. Retrying an owned purchase cannot charge again. A stale price requires confirmation again; it cannot silently debit a different amount.

Frame, card and nameplate equipment are independent. The original /shop/equip request without a slot continues to clear or equip the frame. Explicit clears use slot=frame, card or nameplate. Bundle equipment checks all component ownership. Styling appears on the owner profile, public player profile and managed match player cards. Result previews in the shop are labelled examples and never modify actual results.

The catalogue uses original CSS artwork without third-party game or celebrity images. The optional client preview never changes the wallet or stored equipment. Buy and Equip are separate CSRF-protected submissions, and purchases require a visible price confirmation. Owner verification must use synthetic local balances; no real purchases should be executed by an agent.

Active administrator accounts receive role-based access to the entire catalogue and Master benefits. No cosmetic ownership, wallet debit, fabricated payment or subscription record is created for this access. Regular accounts retain purchase and subscription checks. Removing administrator status removes the included entitlement; existing legitimate purchases and paid membership periods are preserved. Admin membership checkout returns to appearance settings without calling Paystack. Reminder delivery includes active administrators. Existing provider subscriptions, if any, retain their cancellation controls.

Appearance controls share the effective frame across the Master editor, private profile, public profile and match cards. Selecting a specific Master frame unequips the Shop frame without deleting its ownership. Keep equipped frame changes only the profile theme. Shop cards layer over the theme; nameplates remain independent. Framed avatars use a rounded square shape.
