# Anytime-TD market vs the engines (week 6, 2026-10-18)

**Question.** Do sportsbook anytime-touchdown prices say who scores better
than the engines do? If they do, v2's touchdown stats could come from the
market.

**Answer so far.** No. In week 6, v2 was at least as good as every version
of the market price. This is one week (12 games, 209 players, 40 scorers),
so it isn't conclusive either way. Rerun it each week with
`scripts/research_td_market.py`.

## Data

- **Prices.** Pregame quotes frozen by `td_market`: 1,188 quotes covering
  433 player-games, from DraftKings (427), Caesars (357), BetMGM (312) and
  Pinnacle (92). Collection started 2026-10-14, so week 6 is the only week
  so far.
- **Results.** This app's own player stats. A touchdown means rushing,
  receiving, fumble recovery or special teams; passing touchdowns don't
  count. A player with no stat line counts as not playing, because the bet
  is void then. The engines are also conditional on playing.
- **Rows scored.** The 209 players who have a market price, frozen v2, v1
  and ESPN projections, and a final game.

## Turning prices into probabilities

- **raw:** the average of the books' Yes prices, margin included. Mean 0.226
  against 0.191 observed, so the market overstates every player's chance.
- **pin_adj:** Pinnacle quotes both sides, so its margin can be removed
  directly. Each other book is shifted by its average gap to Pinnacle on the
  same players, measured in log-odds without using any results:
  DraftKings -0.06, BetMGM -0.11, Caesars -0.10.
- **team_scaled:** each team's player rates are capped at what its implied
  points support: 0.1065 rushing+receiving TDs per implied point, measured on
  nflverse 2021-2025 (2,718 team-games). Before the cap, the market's rates
  summed to 1.06x that figure (median; middle half 0.97-1.15).

## Results (week 6)

Lower is better. A negative difference means better than v2. The intervals
come from resampling whole games.

| Source | Brier | Log loss | vs v2 (95% interval) | Mean probability |
|---|---|---|---|---|
| **v2** | **0.1417** | **0.4423** | n/a | 0.196 |
| ESPN | 0.1455 | 0.4535 | +0.011 (-0.009, +0.032) | 0.199 |
| v1 | 0.1459 | 0.4579 | +0.016 (-0.004, +0.034) | 0.225 |
| Market, team_scaled | 0.1463 | 0.4560 | +0.014 (-0.001, +0.028) | 0.212 |
| Market, pin_adj | 0.1472 | 0.4567 | +0.014 (-0.002, +0.029) | 0.212 |
| Market, raw | 0.1482 | 0.4590 | +0.017 (-0.001, +0.035) | 0.226 |

The observed scoring rate was 0.191.

- **Blending v2's touchdown rate with the market** (pin_adj) also doesn't
  beat v2 alone: +0.003 with a 25% market weight, +0.006 with 50%.
- **Calibration.** Both v2 and the market are accurate below 30%. Above 30%
  both are too high: in the 30-50% band the market says 0.37 against 0.24
  observed, v2 says 0.35 against 0.26.
- **Fantasy points.** The market implies more touchdowns than v2: +0.15
  fantasy points per player on average (SD 0.44). That gap is consistent
  with the market's margin, not with a sharper read on who scores.

## Next

- Rerun weekly. Decide at weeks 9-10, by which point there will be about 4
  weeks and 50+ games.
- If the market pulls ahead by then (an interval below zero against v2), try
  a new v2 version that takes its touchdown stats from the market, with its
  own prospective record. Until then, nothing changes.
- The prices cost no extra ParlayAPI credits: the NFL props call already
  pays for them.
