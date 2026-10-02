"""Explicit credentials for test fixtures only; production never imports this module."""
from models import db

TEST_PASSWORD = 'Frase exclusiva dos testes 2026!'


def authenticated_id(teacher):
    if teacher.is_admin and not teacher.password_hash:
        teacher.set_password(TEST_PASSWORD)
        db.session.commit()
    return teacher.get_id()
