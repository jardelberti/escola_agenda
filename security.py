"""Administrative authentication shared by login, recovery and sensitive actions."""
import hashlib
import secrets
import time
from functools import wraps
from flask import flash, redirect, request, session, url_for
from flask_login import current_user, confirm_login, logout_user
from sqlalchemy import case
from models import db, Teacher, AuthAttempt, AdminAccessToken

RATE_WINDOW = 15 * 60
CONFIRMATION_WINDOW = 5 * 60


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def consume_attempt(label, limit=5):
    """Reserve atomically in the shared DB, so both Gunicorn workers enforce it."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    now = int(time.time())
    key = digest(label)
    insert = pg_insert if db.engine.dialect.name == 'postgresql' else sqlite_insert
    expired = AuthAttempt.window_start <= now - RATE_WINDOW
    statement = insert(AuthAttempt).values(key=key, window_start=now, attempts=1)
    statement = statement.on_conflict_do_update(
        index_elements=['key'],
        set_={'window_start': case((expired, now), else_=AuthAttempt.window_start),
              'attempts': case((expired, 1), else_=AuthAttempt.attempts + 1)},
    ).returning(AuthAttempt.attempts)
    attempts = db.session.execute(statement).scalar_one()
    # Keep only recent windows; arbitrary invalid links must not grow this table forever.
    db.session.execute(db.delete(AuthAttempt).where(AuthAttempt.window_start < now - 86400))
    db.session.commit()
    return attempts <= limit


def reset_attempts(label):
    db.session.execute(db.delete(AuthAttempt).where(AuthAttempt.key == digest(label)))
    db.session.commit()


def password_error(password):
    if not 15 <= len(password) <= 128:
        return 'Use uma senha com 15 a 128 caracteres. Uma frase longa é uma boa opção.'
    if len(set(password.lower())) < 5 or password.lower() in {
        '123456789012345', '1234567890123456', 'passwordpassword', 'senhasenhasenha123',
    }:
        return 'Escolha uma senha menos previsível, como uma frase com várias palavras.'
    return None


def issue_access_token(teacher):
    # Serialize concurrent issuances so only the newest link survives.
    db.session.execute(db.select(Teacher.id).where(Teacher.id == teacher.id).with_for_update()).scalar_one()
    token = secrets.token_urlsafe(32)
    db.session.execute(db.delete(AdminAccessToken).where(AdminAccessToken.teacher_id == teacher.id))
    db.session.add(AdminAccessToken(token_hash=digest(token), teacher_id=teacher.id,
                                    expires_at=int(time.time()) + 30 * 60))
    db.session.commit()
    return token


def confirmation_needed():
    verified_at = session.get('admin_verified_at', 0)
    return not 0 <= time.time() - verified_at < CONFIRMATION_WINDOW


def end_login_session():
    logout_user()
    session.clear()
    # Clearing the session must not discard Flask-Login's cookie-deletion instruction.
    session['_remember'] = 'clear'


def confirm_admin_password():
    """Always checks a submitted password; callers may allow a recent confirmation."""
    label = 'admin:' + current_user.registration
    if not consume_attempt(label):
        flash('Muitas tentativas. Aguarde 15 minutos antes de tentar novamente.', 'danger')
        return False
    password = request.form.get('admin_password', '')
    if len(password) > 128 or not current_user.check_password(password):
        flash('Confirme sua senha de administrador para continuar.', 'danger')
        return False
    reset_attempts(label)
    session['admin_verified_at'] = time.time()
    confirm_login()
    return True


def recent_admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if confirmation_needed() and not confirm_admin_password():
            flash('A operação não foi executada. Preencha sua senha e envie novamente.', 'warning')
            return redirect(url_for('admin.backup_restore_page'))
        return view(*args, **kwargs)
    return wrapped
