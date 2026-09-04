"""games.nhl_game_id - the NHL API's own game identifier.

Revision ID: 0008_nhl_game_id
Revises: 0007_mlb_game_pk
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_nhl_game_id"
down_revision = "0007_mlb_game_pk"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("games", sa.Column("nhl_game_id", sa.String(length=16), nullable=True))
    op.create_unique_constraint("uq_games_nhl_game_id", "games", ["nhl_game_id"])


def downgrade():
    op.drop_constraint("uq_games_nhl_game_id", "games", type_="unique")
    op.drop_column("games", "nhl_game_id")
