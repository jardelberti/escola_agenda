"""Add administrator credentials, revocable sessions, enrollment and throttling.

Revision ID: d4f2a3b5c6d7
Revises: c3e1a2b4d5e6
"""
from alembic import op
from auth_schema import upgrade_admin_auth

revision = 'd4f2a3b5c6d7'
down_revision = 'c3e1a2b4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    upgrade_admin_auth(op.get_bind())


def downgrade():
    raise RuntimeError('Reverter autenticação exige plano explícito; não remover credenciais automaticamente.')
