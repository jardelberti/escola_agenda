"""add teacher whatsapp column

Revision ID: b2d9e1f8c345
Revises: a1f8c4e29b10
Create Date: 2026-09-29 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2d9e1f8c345'
down_revision = 'a1f8c4e29b10'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    teacher_columns = [c['name'] for c in inspector.get_columns('teacher')]
    if 'whatsapp' not in teacher_columns:
        with op.batch_alter_table('teacher', schema=None) as batch_op:
            batch_op.add_column(sa.Column('whatsapp', sa.String(length=30), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    teacher_columns = [c['name'] for c in inspector.get_columns('teacher')]
    if 'whatsapp' in teacher_columns:
        with op.batch_alter_table('teacher', schema=None) as batch_op:
            batch_op.drop_column('whatsapp')
