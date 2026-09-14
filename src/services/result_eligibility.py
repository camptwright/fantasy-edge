"""Keep unresolved player-game corrections out of new model inputs.

Exclude the whole player's game so aliases, composites and opportunity features
cannot retain an inconsistent subset. Applied/superseded proposals do not block.
"""
from sqlalchemy import exists, select
from sqlalchemy.orm import aliased
from src.models.facts import PlayerGameStat
from src.models.governance import ResultCorrection


def no_pending_correction():
    disputed = aliased(PlayerGameStat)
    return ~exists(select(ResultCorrection.id).join(disputed,
        disputed.id == ResultCorrection.stat_id).where(
            ResultCorrection.status == 'pending',
            disputed.player_id == PlayerGameStat.player_id,
            disputed.game_id == PlayerGameStat.game_id))
