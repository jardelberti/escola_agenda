"""add teacher is_active column and deactivate former teachers

Revision ID: c3e1a2b4d5e6
Revises: b2d9e1f8c345
Create Date: 2026-09-29 13:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3e1a2b4d5e6'
down_revision = 'b2d9e1f8c345'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    teacher_columns = [c['name'] for c in inspector.get_columns('teacher')]
    if 'is_active' not in teacher_columns:
        with op.batch_alter_table('teacher', schema=None) as batch_op:
            batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'))

    # Desativa os professores que não estão mais na escola
    inactive_registrations = ('451943', '472751', '467421', '454942', '2630', '471171')
    try:
        conn.execute(
            sa.text("UPDATE teacher SET is_active = FALSE WHERE registration IN ('451943', '472751', '467421', '454942', '2630', '471171');")
        )
    except Exception:
        pass


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    teacher_columns = [c['name'] for c in inspector.get_columns('teacher')]
    if 'is_active' in teacher_columns:
        with op.batch_alter_table('teacher', schema=None) as batch_op:
            batch_op.drop_column('is_active')
