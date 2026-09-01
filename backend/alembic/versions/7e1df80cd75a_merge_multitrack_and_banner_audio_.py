"""merge multitrack and banner audio overlay heads

Revision ID: 7e1df80cd75a
Revises: 412aa37515c0, bb81b5c2a6a1
Create Date: 2026-09-01 13:20:20.193919

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7e1df80cd75a'
down_revision: Union[str, Sequence[str], None] = ('412aa37515c0', 'bb81b5c2a6a1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
