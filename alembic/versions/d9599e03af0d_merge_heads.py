"""merge heads

Revision ID: d9599e03af0d
Revises: 6bf21ac304de, 95a207d70ce2
Create Date: 2026-11-08 12:50:07.330415

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9599e03af0d'
down_revision: Union[str, Sequence[str], None] = ('6bf21ac304de', '95a207d70ce2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
