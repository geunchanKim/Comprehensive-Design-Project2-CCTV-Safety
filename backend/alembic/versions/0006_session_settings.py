"""Store immutable experiment settings per session."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "session_settings",
        sa.Column("session_id", sa.String(128), primary_key=True),
        sa.Column("settings", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("session_settings")
