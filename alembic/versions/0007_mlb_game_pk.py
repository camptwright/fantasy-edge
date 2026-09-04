"""games.mlb_game_pk - MLB Stats API's own game identifier.

Revision ID: 0007_mlb_game_pk
Revises: 0006_sleeper_league_sport
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_mlb_game_pk"
down_revision = "0006_sleeper_league_sport"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("games", sa.Column("mlb_game_pk", sa.String(length=16), nullable=True))
    op.create_unique_constraint("uq_games_mlb_game_pk", "games", ["mlb_game_pk"])


def downgrade():
    op.drop_constraint("uq_games_mlb_game_pk", "games", type_="unique")
    op.drop_column("games", "mlb_game_pk")
