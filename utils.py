"""
Funções utilitárias e decoradores compartilhados da Agenda Escolar.
"""
import os
from functools import wraps
from datetime import datetime
from flask import flash, redirect, url_for
from flask_login import current_user

def admin_required(f):
    """Protege rotas que exigem perfil de administrador."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Acesso restrito a administradores.', 'danger')
            return redirect(url_for('agenda.home'))
        return f(*args, **kwargs)
    return decorated_function

def clean_old_backups(folder, keep_latest=10, max_days=14):
    """
    Remove backups antigos para economizar espaço em disco.
    Garante que pelo menos os `keep_latest` arquivos mais recentes sejam preservados.
    Arquivos com mais de `max_days` dias são removidos se o limite de `keep_latest` for respeitado.
    """
    if not os.path.exists(folder):
        return []

    files = []
    for fname in os.listdir(folder):
        fpath = os.path.join(folder, fname)
        if os.path.isfile(fpath) and any(fname.endswith(ext) for ext in ['.sql', '.dump', '.tar', '.db']):
            files.append((fpath, os.path.getmtime(fpath)))

    files.sort(key=lambda x: x[1], reverse=True) # Mais recentes primeiro
    deleted = []
    now = datetime.now().timestamp()
    cutoff_seconds = max_days * 86400

    for idx, (fpath, mtime) in enumerate(files):
        if idx >= keep_latest and (now - mtime) > cutoff_seconds:
            try:
                os.remove(fpath)
                deleted.append(fpath)
            except OSError:
                pass
    return deleted
