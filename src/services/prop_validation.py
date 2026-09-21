"""Recommendation gates, not probability adjustments or automatic promotion."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.services.roster_stat_model import finite

APPROVALS = Path(__file__).resolve().parents[2] / "config/prop_validation_approvals.json"
LARGE_EDGE_PERCENT = 20
LARGE_PROBABILITY_GAP = 0.20


def decision_digest(row):
    """Bind approval to fixed-window evidence, not the regrading wall clock.

    An unchanged regrade can retain approval; corrected outcomes, metrics,
    protocol, market, sport or cohort require a new explicit review.
    """
    decision = {
        key: row[key]
        for key in ("sport", "kind", "market", "model_version", "prospective_scorecard")
    }
    return hashlib.sha256(
        json.dumps(decision, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def load_evidence(directory, versions, now=None):
    """Only fresh grading plus approval of the exact decision evidence can serve.

    Legacy sport-level calibration and manual distribution overrides are not
    prospective approval. Missing/malformed/stale evidence always fails closed.
    """
    now = now or datetime.now(timezone.utc)
    try:
        files = sorted(Path(directory).glob("*.json"))
        raw = files[-1].read_bytes()
        report = json.loads(raw)
        approvals = json.loads(APPROVALS.read_text())
        at = datetime.fromisoformat(report["graded_at"])
        if (
            report.get("schema_version") != 1
            or report.get("status") != "available"
            or not timedelta(0) <= now - at <= timedelta(hours=2)
        ):
            return {}
        sha = hashlib.sha256(raw).hexdigest()
        result = {}
        for row in report["reports"]:
            from src.services.prospective_review import protocol
            key = (row["sport"], row["market"])
            card = row.get("prospective_scorecard", {})
            review = card.get("review", {})
            if (
                row.get("kind") != "player"
                or row.get("model_version") != versions["cohort_version"]
                or review.get("promotion_eligible") is not True
                or review.get("blockers") != []
                or card.get('protocol') != protocol(row['sport'])
                or review.get("independent_games", 0) < 200
                or row.get("independent_games", 0) < 200
                or datetime.fromisoformat(card["decision_not_before"]) > now
            ):
                continue
            matches = [
                a
                for a in approvals
                if a.get("approved") is True
                and a.get("sport") == key[0]
                and a.get("market") == key[1]
                and a.get("model_version") == versions["model_version"]
                and a.get("cohort_version") == versions["cohort_version"]
                and a.get("decision_sha256") == decision_digest(row)
            ]
            if len(matches) == 1:
                result[key] = {
                    "status": "approved",
                    "report_sha256": sha,
                    "decision_sha256": decision_digest(row),
                    "evaluated_at": report["graded_at"],
                    "sample_size": row["sample_size"],
                    "independent_games": row["independent_games"],
                }
        return result
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        return {}


def linkage(player, game, roster=None):
    if game is None:
        return "unlinked_event"
    if player.sport != game.sport:
        return "player_game_sport_mismatch"
    if not game.home_team_id or not game.away_team_id or game.home_team_id == game.away_team_id:
        return "incomplete_event_teams"
    if roster is not None:
        from src.services.roster_evidence import reason
        return reason(roster, game)
    if not player.current_team_id:
        return "player_team_unverified"
    if player.current_team_id not in (game.home_team_id, game.away_team_id):
        return "player_game_team_mismatch"
    return None


def binding_reason(binding, game):
    if not isinstance(binding, dict) or game is None or game.game_time is None:
        return "provider_event_binding_unverified"
    from src.ingest.prop_events import event_binding

    if binding != event_binding(game):
        return "provider_event_binding_changed"
    return None


def assess(row, player, game, evidence):
    reasons = []
    link = linkage(player, game, row.get('roster_evidence'))
    if link:
        reasons.append(link)
    bound = binding_reason(row.get("event_binding"), game)
    if bound:
        reasons.append(bound)
    if not evidence:
        reasons.append("missing_version_bound_prop_validation")
    p = row.get("model_probability")
    prices = [row.get("over_price_american"), row.get("under_price_american")]
    if not finite(p) or not 0 < p < 1:
        reasons.append("invalid_probability")
    if any(v is not None and (not finite(v) or abs(v) < 100) for v in prices):
        reasons.append("invalid_price")
    evs = [v for v in (row.get("edge_percent"), row.get("under_edge_percent")) if finite(v)]
    if not evs or max(evs) <= 0:
        reasons.append("non_positive_ev")
    market = row.get("market_fair_probability")
    if (evs and max(evs) > LARGE_EDGE_PERCENT) or (
        finite(p) and finite(market) and abs(p - market) > LARGE_PROBABILITY_GAP
    ):
        reasons.append("large_edge_requires_review")
    # Normal O/U probabilities do not price integer-line pushes. Preserve them
    # for research, not positive-EV claims without an exact push distribution.
    line = row.get("line")
    if finite(line) and float(line).is_integer():
        reasons.append("integer_line_requires_push_model")
    return reasons
