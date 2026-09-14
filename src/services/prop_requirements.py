"""Explicit gaps that cannot use a generic full-game boxscore model."""
import re


def requirement(stat):
    if stat in ('fantasy_points', 'fantasy_score', 'total_tds'):
        return 'requires_settlement_rules'
    if stat in ('first_td_scorer', 'last_td_scorer'):
        return 'requires_play_order_model'
    if stat.startswith('game_high_'):
        return 'requires_comparative_model'
    if re.match(r'^\d+[hq]_', stat) or '_in_each_' in stat:
        return 'requires_period_model'
    return None
