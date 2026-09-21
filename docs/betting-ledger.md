# Betting ledger — initial implementation

Authenticated `/api/v1/ledger` routes and `/ledger` provide manual/paper singles.
No sportsbook execution, location eligibility determination or bankroll inference
is performed. The experimental fantasy model's limitations are recorded in
`fantasy-decision-models.md`.

Placement terms are immutable. Repeated request IDs return the original entry;
changed terms with the same key are rejected. Settlement corrections append new
events (including reopening), retaining previous evidence. Returned amounts
include the original stake. Paper and actual balances and currencies never mix.
No automatic settlement claims are made from boxscores alone.

Users can save absolute stake limits per currency for a single bet, total open
stake, sport, event, player and book. Null dimensions are unconfigured. Preflight
reports violations; paper entries exceeding limits are rejected. Actual wagers
already placed elsewhere remain recordable, with warnings, so a risk violation
cannot disappear from accounting. This is not bookmaker-side enforcement.
Correlated positions are conservatively grossed, never assumed to cancel.

Every five minutes, closing capture uses existing stored quote history only;
it spends no additional provider credits. Exact source/game/player/market/side/
line and an observation after placement but strictly before kickoff within thirty
minutes are required. Unknown kickoff stays pending, absent prices stay missing,
and changed kickoff/evidence appends an audit event. No cross-book substitution.
These are **observed price proxies**: quote history does not carry exact
settlement-rule identity, so verified CLV and automatic ROI claims are withheld.
Sparse ingestion can miss the true close. Manually entered rule text does not
prove provider-rule equivalence.

Best Bets now links each team/player side to a server-resolved quote-to-ledger
form. No economic terms are parsed from display labels. The form shows source,
event, side, line, price and availability. Paper entries recheck liveness at save;
actual entries allow receipt prices to differ from the displayed offer. No entry
is made until the user records it; amount and actual placement time are required.

## Receipt imports

`/ledger` accepts normalized JSON files or pasted JSON, at most 100 singles per
batch; a downloadable template is included. This is not a generic PDF/image OCR
or native bookmaker-export adapter. No such receipt was supplied for validation.
The parser rejects extra fields and requires exact app game/player IDs. No fuzzy
name matching, external AI upload, settlement guessing or secret extraction.

Authenticated `receipts/preview` validates without writing. `receipts/commit`
rechecks the preview signature and commits the entire valid batch atomically.
Book + local account nickname + receipt ID forms a stable duplicate key. Different
content under an existing key is rejected. Possible matching manual entries must
be explicitly linked with `existing_bet_id`; economics must match and existing
placement terms remain immutable. Normalized receipt claims and their digest are
retained in receipt audit events; these never overwrite closing or settlement
events. Repeated commit after success is a no-op. Use consistent account aliases.
Receipt imports are actual already-placed singles, not paper bets or instructions
to wager. Unsettled imports retain full exposure until an explicit settlement.

## Verified closing-rule matching

The verifier uses the existing `settlement_binding.bind` checks and an
operator-reviewed `config/ledger_closing_evidence.json` registry. The current
registry is deliberately empty: no quote/receipt-specific evidence has yet been
reviewed. Uploading text, selecting a jurisdiction or supplying a rule note does
not establish verification. [The Odds API's documented market responses](https://the-odds-api.com/liveapi/guides/v4/)
identify books, prices and observations but do not supply all the receipt-level
contract evidence this verifier requires. The [DraftKings football help page](https://sportsbook.draftkings.com/help/sport-rules/football)
did not expose a complete effective-dated contract in the retrieved response.

Registry schema (all mappings require source_url, exact source_snapshot text,
matching source_sha256, reviewed_by and reviewed_at):

- `rules[rule_id]`: book, product, jurisdiction, sport, market, source (same as
  source_url), verified status, empty unresolved list, effective_from/until,
  complete clauses (stat definition, participation, overtime, voids, pushes and
  scorer-specific exceptions where applicable). Rules must cover both times.
- `quotes[quote_uuid]`: rule_id; exact contract object containing game_id, kind,
  player_id, market, side, line, book, product, jurisdiction and period; observed_at
  and price_american matching the stored quote. For official closing evidence:
  designation `official_pregame_close` plus the exact current kickoff timestamp.
- `receipts[ledger_bet_uuid]`: same exact contract and rule_id, actual placed_at
  and price_american matching the ledger, independently reviewed receipt identity.

The registry is deployment-managed, not writable by the public receipt endpoint.
An operator must inspect the source, its scope and authenticity before registering
anything; a source hash proves integrity, not truth. A rules-matched observation
without official-close designation remains a proxy. Rescheduled/unknown kickoffs
invalidate prior closing status on the next capture. Rule/evidence changes are
re-evaluated and append an audit event rather than rewriting history.

Only matching same-line official closes expose `clv_percent`: 100 ×
(entry decimal odds / closing decimal odds − 1). Positive means a better entry
price. This is a price-improvement measure, **not no-vig EV, ROI or profit**.
Different lines, rules, books, products or jurisdictions cannot be pooled. A
two-sided no-vig benchmark and settlement-profit analytics are separate work.

Still unsupported: native book export adapters without sample receipts,
PDF/image OCR, parlays/bonuses, Board shortcut, portfolio return reports and large
ledger pagination. Verified live CLV awaits actual reviewed receipt and closing
evidence; this implementation does not relabel existing proxies as verified.

## Verification — September 14, 2026 (Central)

- Additive migration applied successfully to isolated and production Postgres.
- 37 focused ledger/fantasy/scheduler tests passed; dashboard typecheck and build passed.
- Authenticated ledger returned 200, unauthenticated access 401; health remained 200.
- Closing capture succeeded twice through both API and fresh-loop worker execution.
- Local `/ledger` page and its server-side capture action verified in the browser.
- Production ledger starts empty; no sample wagers or risk policies were inserted.
