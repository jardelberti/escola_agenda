"""Additive, idempotent schema upgrade used by Alembic and deployment bootstrap."""
from sqlalchemy import inspect, text
import secrets
from models import AdminAccessToken, AuthAttempt


def upgrade_admin_auth(connection):
    columns = {column['name'] for column in inspect(connection).get_columns('teacher')}
    for name, sql_type in [('password_hash', 'VARCHAR(255)'), ('auth_version', 'VARCHAR(64)')]:
        if name not in columns:
            connection.execute(text(f'ALTER TABLE teacher ADD COLUMN {name} {sql_type}'))
    AdminAccessToken.__table__.create(connection, checkfirst=True)
    AuthAttempt.__table__.create(connection, checkfirst=True)


def secure_restored_admin_accounts(connection):
    """Old dumps need the new columns; restored cookies/links must never revive."""
    upgrade_admin_auth(connection)
    connection.execute(text('DELETE FROM admin_access_token'))
    admin_ids = connection.execute(text('SELECT id FROM teacher WHERE is_admin = true')).scalars().all()
    for teacher_id in admin_ids:
        connection.execute(text('UPDATE teacher SET auth_version = :version WHERE id = :id'),
                           {'version': secrets.token_hex(32), 'id': teacher_id})
