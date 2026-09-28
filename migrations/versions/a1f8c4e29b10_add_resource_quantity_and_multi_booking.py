"""add resource quantity and multi-booking support

Revision ID: a1f8c4e29b10
Revises: 5b7950738002
Create Date: 2026-09-28 16:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1f8c4e29b10'
down_revision = '5b7950738002'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    # 1. Adicionar coluna quantity na tabela resource se não existir
    res_columns = [c['name'] for c in inspector.get_columns('resource')]
    if 'quantity' not in res_columns:
        with op.batch_alter_table('resource', schema=None) as batch_op:
            batch_op.add_column(sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'))

    # 2. Remover restrição única antiga de 1 agendamento por horário
    try:
        with op.batch_alter_table('booking', schema=None) as batch_op:
            batch_op.drop_constraint('_resource_date_shift_slot_uc', type_='unique')
    except Exception:
        pass

    # 3. Criar índice único parcial para impedir que o mesmo professor reserve duas vezes
    booking_indexes = [idx['name'] for idx in inspector.get_indexes('booking')]
    if 'uq_booking_teacher_active' not in booking_indexes:
        try:
            with op.batch_alter_table('booking', schema=None) as batch_op:
                batch_op.create_index(
                    'uq_booking_teacher_active',
                    ['resource_id', 'teacher_id', 'date', 'shift', 'slot_name'],
                    unique=True,
                    postgresql_where=sa.text("status = 'booked'"),
                    sqlite_where=sa.text("status = 'booked'")
                )
        except Exception:
            pass

    # 4. Atualizar o recurso Projetor existente para Projetores com quantidade 2
    try:
        conn.execute(sa.text("UPDATE resource SET name = 'Projetores', quantity = 2 WHERE LOWER(name) LIKE '%projetor%' AND quantity = 1;"))
    except Exception:
        pass


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    booking_indexes = [idx['name'] for idx in inspector.get_indexes('booking')]
    if 'uq_booking_teacher_active' in booking_indexes:
        with op.batch_alter_table('booking', schema=None) as batch_op:
            batch_op.drop_index('uq_booking_teacher_active')

    with op.batch_alter_table('booking', schema=None) as batch_op:
        batch_op.create_unique_constraint('_resource_date_shift_slot_uc', ['resource_id', 'date', 'shift', 'slot_name'])

    res_columns = [c['name'] for c in inspector.get_columns('resource')]
    if 'quantity' in res_columns:
        with op.batch_alter_table('resource', schema=None) as batch_op:
            batch_op.drop_column('quantity')
