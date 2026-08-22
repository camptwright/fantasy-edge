"""Ingest-time normalisation. CONSTRAINT #8.

Every provider spells things differently. Underdog says "Pts + Reb + Ast",
the Odds API says "player_points_rebounds_assists", ESPN says "PRA". If those
land in the database verbatim then a cross-source join finds nothing and the
"compare sources" feature silently returns one row per source instead of a
matched pair.

The fix is to normalise once, at the moment of ingest, so `stat_type` in
Postgres is always the canonical form. That makes the DB the single source of
truth and means no query has to remember the mapping.

The tradeoff: a wrong alias is baked in permanently (rows already written keep
the bad value). That is why the alias table is plain data - it is meant to be
read and audited by a human, not derived.
"""

from __future__ import annotations

import re
import unicodedata

# --------------------------------------------------------------- players ----

_PUNCT = re.compile(r"[^a-z0-9 ]")
_WS = re.compile(r"\s+")
# Providers disagree about suffixes. ESPN writes "Ken Griffey Jr.", Underdog
# writes "Ken Griffey". Dropping the suffix entirely makes them join.
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_player_name(name: str) -> str:
    """Canonical join key for a player name.

    "A.J. Brown" / "AJ Brown" / "A J Brown" all collapse to "aj brown", which
    is the whole point - these are the same human and providers cannot agree.
    """
    if not name:
        return ""
    # Strip accents: "Nikola Jokić" -> "Nikola Jokic".
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))

    lowered = ascii_only.lower()
    # Remove periods BEFORE splitting so "A.J." becomes "aj" rather than "a j".
    lowered = lowered.replace(".", "")
    lowered = _PUNCT.sub(" ", lowered)

    parts = [p for p in _WS.split(lowered) if p and p not in _SUFFIXES]
    return " ".join(parts)


# ----------------------------------------------------------------- stats ----

# Canonical stat names on the right. Keys are lowercased with whitespace
# collapsed and separators unified to a single space before lookup, so one
# entry covers "pts_reb_ast", "pts reb ast" and "Pts+Reb+Ast".
STAT_ALIASES: dict[str, str] = {
    # basketball
    "pts": "points",
    "point": "points",
    "points": "points",
    "reb": "rebounds",
    "rebs": "rebounds",
    "rebound": "rebounds",
    "rebounds": "rebounds",
    "ast": "assists",
    "asts": "assists",
    "assist": "assists",
    "assists": "assists",
    "stl": "steals",
    "steal": "steals",
    "steals": "steals",
    "blk": "blocks",
    "block": "blocks",
    "blocks": "blocks",
    "to": "turnovers",
    "tov": "turnovers",
    "turnover": "turnovers",
    "turnovers": "turnovers",
    "3pm": "three_pointers_made",
    "3 pointers made": "three_pointers_made",
    "three pointers made": "three_pointers_made",
    "fg3m": "three_pointers_made",
    "pts reb ast": "points_rebounds_assists",
    "pts rebs asts": "points_rebounds_assists",
    "points rebounds assists": "points_rebounds_assists",
    "pra": "points_rebounds_assists",
    "pts reb": "points_rebounds",
    "pts rebs": "points_rebounds",
    "pts ast": "points_assists",
    "pts asts": "points_assists",
    "reb ast": "rebounds_assists",
    "rebs asts": "rebounds_assists",
    "stl blk": "steals_blocks",
    "blk stl": "steals_blocks",
    "fantasy points": "fantasy_points",
    "fantasy pts": "fantasy_points",
    "double double": "double_double",
    "triple double": "triple_double",
    # football
    "pass yds": "passing_yards",
    "pass yards": "passing_yards",
    "passing yards": "passing_yards",
    "pass tds": "passing_touchdowns",
    "passing tds": "passing_touchdowns",
    "passing touchdowns": "passing_touchdowns",
    "pass completions": "passing_completions",
    "completions": "passing_completions",
    "pass attempts": "passing_attempts",
    # nflverse's raw player-stats column is the bare "attempts" (passing
    # attempts) - without this entry it fell through to a slugified
    # "attempts", a third spelling alongside "pass_attempts"-style joins
    # from other sources. CONSTRAINT #8.
    "attempts": "passing_attempts",
    "interceptions thrown": "interceptions_thrown",
    "int": "interceptions_thrown",
    "rush yds": "rushing_yards",
    "rush yards": "rushing_yards",
    "rushing yards": "rushing_yards",
    "rush attempts": "rushing_attempts",
    "carries": "rushing_attempts",
    "rush tds": "rushing_touchdowns",
    # nflverse's raw column is "rushing_tds" (-> "rushing tds" after
    # separator normalization), which doesn't match the "rush tds" key
    # above. Same canonical target as "rush tds" - CONSTRAINT #8.
    "rushing tds": "rushing_touchdowns",
    "rec yds": "receiving_yards",
    "receiving yards": "receiving_yards",
    "rec": "receptions",
    "receptions": "receptions",
    "rec tds": "receiving_touchdowns",
    # nflverse's raw column is "receiving_tds" (-> "receiving tds"), which
    # doesn't match the "rec tds" key above. Same canonical target -
    # CONSTRAINT #8.
    "receiving tds": "receiving_touchdowns",
    "kicking points": "kicking_points",
    "tackles": "tackles",
    "tackles assists": "tackles_assists",
    # hockey
    "sog": "shots_on_goal",
    "shots on goal": "shots_on_goal",
    "goals": "goals",
    "saves": "saves",
    "goalie saves": "saves",
    "points hockey": "points",
    # baseball
    "hits": "hits",
    "hits runs rbis": "hits_runs_rbis",
    "hrr": "hits_runs_rbis",
    "total bases": "total_bases",
    "tb": "total_bases",
    "rbis": "rbis",
    "rbi": "rbis",
    "runs": "runs",
    "strikeouts": "strikeouts",
    "ks": "strikeouts",
    "pitcher strikeouts": "strikeouts",
    "earned runs": "earned_runs",
    "hits allowed": "hits_allowed",
    "walks": "walks",
    "stolen bases": "stolen_bases",
    "home runs": "home_runs",
    "hr": "home_runs",
}

# Period qualifiers. Underdog writes "1H Points" / "1Q Pts"; we want a
# canonical `1h_points` prefix rather than a separate column, so that a plain
# `points` query is unambiguously full-game.
_PERIOD = re.compile(r"^(1h|2h|1q|2q|3q|4q|1p|2p|3p|1st half|2nd half)\b", re.I)
_PERIOD_CANON = {
    "1st half": "1h",
    "2nd half": "2h",
}

_SEPARATORS = re.compile(r"[+/_\-,&]")


def normalize_stat_type(raw: str) -> str:
    """Map a provider's stat label to the canonical form.

    Unknown stats are not dropped - they are slugified and stored as-is, so a
    new market shows up in the data rather than vanishing. Finding an unmapped
    slug in the DB is the signal to add an alias.
    """
    if not raw:
        return ""

    text = raw.strip().lower()
    text = _SEPARATORS.sub(" ", text)
    text = _WS.sub(" ", text).strip()

    prefix = ""
    match = _PERIOD.match(text)
    if match:
        token = match.group(1).lower()
        prefix = _PERIOD_CANON.get(token, token) + "_"
        text = text[match.end():].strip()

    canonical = STAT_ALIASES.get(text)
    if canonical is None:
        # Unmapped: slugify so it is at least stable and joinable with itself.
        canonical = text.replace(" ", "_")

    return f"{prefix}{canonical}" if canonical else ""


# ------------------------------------------------------------------ teams ----


def normalize_team_name(name: str) -> str:
    """Loose team key. Providers vary on "LA Lakers" vs "Los Angeles Lakers"."""
    if not name:
        return ""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = _PUNCT.sub(" ", ascii_only.lower())
    return _WS.sub(" ", lowered).strip()
