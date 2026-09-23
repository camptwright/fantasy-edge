# B-06: prospective paper ledger

B-04 is explicitly deferred at the user's request.

The scheduled forecast capture now records qualified team/player advice in
the existing Postgres ledger. Only `actionable: true` with an explicit model
version can enter. Existing quote freshness, exact contract, pregame and
paper exposure checks run again at recording time. Each entry is a fixed
$1 paper observation, not a stake recommendation or actual wager.

An advisory lock and deterministic contract/model/cohort key prevent repeat
polls and price movement from generating duplicate paper bets. The original
price, quote ID, capture time, model evidence and eligibility metadata are
frozen. No old forecast is retrospectively turned into a paper placement.

The existing five-minute closing job processes these entries using its
exact-book, exact-line pregame matching. Official CLV remains gated on
reviewed rule, receipt and closing-designation evidence. Merely recording
the last observed quote is not sufficient. Unchanged deduplicated quotes
without a near-kickoff observation can still lack a closing match; timestamps
must not be fabricated to fill that gap.

`GET /api/v1/ledger/coverage` exposes per-source quote-history bounds,
automatic paper counts, settlement counts and closing-status counts. It
explicitly distinguishes quote history from verified closing history.

Remaining evidence work: accumulate qualifying live signals and their real
closing observations, provide reviewed settlement/closing rules, and settle
paper observations against those contracts. No automatic settlement was
introduced without verified rules. Zero qualifying signals remains a valid
zero, not a reason to relax model or roster gates.
