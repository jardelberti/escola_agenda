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

def sanitize_phone(phone_str):
    """
    Higieniza e normaliza números de WhatsApp no padrão internacional (DDI 55).
    Exemplos:
      '(47) 99123-4567' -> '5547991234567'
      '47991234567'     -> '5547991234567'
      '+55 47 99123-4567' -> '5547991234567'
    """
    if not phone_str:
        return None
    import re
    digits = re.sub(r'\D', '', str(phone_str))
    if not digits:
        return None
    # Se inserido com DDD brasileiro (10 ou 11 dígitos), prefixa o DDI 55
    if len(digits) in (10, 11):
        digits = f"55{digits}"
    return digits

def format_phone(phone_str):
    """
    Formata o número de telefone para exibição amigável na interface: (XX) XXXXX-XXXX.
    """
    if not phone_str:
        return ""
    import re
    digits = re.sub(r'\D', '', str(phone_str))
    if digits.startswith('55') and len(digits) in (12, 13):
        digits = digits[2:] # Remove o 55 para formatar nacional
    if len(digits) == 11:
        return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    elif len(digits) == 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return phone_str

