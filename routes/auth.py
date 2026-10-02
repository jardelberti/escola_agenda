"""Registration login for teachers, password authentication for administrators."""
import secrets
import time
import click
from urllib.parse import urlsplit
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from models import db, Teacher, AdminAccessToken
from security import consume_attempt, reset_attempts, password_error, digest, issue_access_token, confirm_admin_password, end_login_session
from utils import admin_required

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('agenda.home'))
    registration = request.form.get('registration', '').strip()[:50]
    admin_step = request.form.get('admin_step') == '1'
    if request.method == 'POST':
        teacher = Teacher.query.filter_by(registration=registration).first()
        if teacher and not teacher.is_active:
            flash('Este cadastro está desativado pela administração. Entre em contato com a coordenação.', 'danger')
        elif teacher and teacher.is_admin and not admin_step:
            return render_template('login.html', admin_step=True, registration=registration)
        elif teacher and teacher.is_admin:
            label = 'admin:' + registration
            if not consume_attempt(label):
                flash('Muitas tentativas. Aguarde 15 minutos antes de tentar novamente.', 'danger')
            elif len(request.form.get('password', '')) > 128 or not teacher.check_password(request.form.get('password', '')):
                flash('Não foi possível entrar. Confira matrícula e senha. Se ainda não criou sua senha, use o link de ativação fornecido pelo responsável.', 'danger')
            else:
                reset_attempts(label)
                session.clear()
                login_user(teacher, remember=request.form.get('remember') == '1')
                session['admin_verified_at'] = time.time()
                flash(f'Bem-vindo(a), {teacher.name}!', 'success')
                return redirect(url_for('admin.admin_dashboard'))
        elif teacher:
            session.clear()
            login_user(teacher)
            flash(f'Bem-vindo(a), {teacher.name}!', 'success')
            return redirect(url_for('agenda.home'))
        else:
            flash('Matrícula inválida.', 'danger')
    return render_template('login.html', admin_step=admin_step, registration=registration)

@auth_bp.route('/admin/definir-senha', methods=['GET', 'POST'])
def setup_password():
    if request.method == 'POST':
        token = request.form.get('access_token', '')
        if not consume_attempt('setup-source:' + (request.remote_addr or 'unknown'), limit=30):
            flash('Muitas tentativas. Aguarde 15 minutos antes de tentar novamente.', 'danger')
            return render_template('admin_setup_password.html'), 429
        if len(token) > 200 or not consume_attempt('setup:' + digest(token)):
            flash('Muitas tentativas. Aguarde 15 minutos antes de tentar novamente.', 'danger')
            return render_template('admin_setup_password.html'), 429
        password = request.form.get('password', '')
        error = password_error(password)
        if password != request.form.get('password_confirm'):
            error = 'As senhas não coincidem.'
        if error:
            flash(error, 'danger')
            return render_template('admin_setup_password.html', access_token=token), 400
        access = db.session.execute(db.select(AdminAccessToken).where(
            AdminAccessToken.token_hash == digest(token),
            AdminAccessToken.expires_at > int(time.time()),
        ).with_for_update()).scalar_one_or_none()
        teacher = db.session.get(Teacher, access.teacher_id) if access else None
        if not teacher or not teacher.is_active or not teacher.is_admin:
            db.session.rollback()
            flash('Link inválido, expirado ou já utilizado. Solicite um novo link ao responsável.', 'danger')
            return render_template('admin_setup_password.html'), 400
        consumed = db.session.execute(db.delete(AdminAccessToken).where(AdminAccessToken.token_hash == access.token_hash))
        if consumed.rowcount != 1:
            db.session.rollback()
            flash('Este link já foi utilizado.', 'danger')
            return render_template('admin_setup_password.html'), 400
        teacher.set_password(password)
        db.session.commit()
        reset_attempts('admin:' + teacher.registration)
        end_login_session()
        flash('Senha definida! Entre com sua matrícula e a nova senha.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('admin_setup_password.html')

@auth_bp.after_request
def private_auth_pages(response):
    if request.endpoint in {'auth.login', 'auth.setup_password', 'auth.security_settings'}:
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
    if request.endpoint in {'auth.login', 'auth.setup_password'}:
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
            "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
    return response

@auth_bp.route('/admin/security', methods=['GET', 'POST'])
@admin_required
def security_settings():
    if request.method == 'POST':
        if not confirm_admin_password():
            return redirect(url_for('auth.security_settings'))
        action = request.form.get('action')
        if action == 'change_password':
            password = request.form.get('password', '')
            error = password_error(password)
            if password != request.form.get('password_confirm'):
                error = 'As senhas não coincidem.'
            if error:
                flash(error, 'danger')
                return redirect(url_for('auth.security_settings'))
            current_user.set_password(password)
        elif action == 'logout_all':
            current_user.auth_version = secrets.token_hex(32)
        else:
            return redirect(url_for('auth.security_settings'))
        db.session.execute(db.delete(AdminAccessToken).where(AdminAccessToken.teacher_id == current_user.id))
        db.session.commit()
        end_login_session()
        flash('Todos os dispositivos foram desconectados. Entre novamente para continuar.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('admin_security.html')

@auth_bp.cli.command('access-link')
@click.argument('registration')
@click.option('--base-url', default=None)
def access_link(registration, base_url):
    """Trusted SSH recovery. Secret link lasts 30 minutes and can be used once."""
    teacher = Teacher.query.filter_by(registration=registration, is_admin=True, is_active=True).first()
    if not teacher:
        raise click.ClickException('Administrador ativo não encontrado.')
    base_url = base_url or current_app.config['PUBLIC_BASE_URL']
    parsed = urlsplit(base_url)
    local_http = (parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1', '::1'}
                  and not current_app.config['SESSION_COOKIE_SECURE'])
    if ((parsed.scheme != 'https' and not local_http) or not parsed.netloc or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise click.ClickException('Informe a origem HTTPS do sistema, sem caminho ou parâmetros.')
    token = issue_access_token(teacher)
    click.echo(base_url.rstrip('/') + '/admin/definir-senha#' + token)

@auth_bp.route('/logout')
@login_required
def logout():
    end_login_session()
    flash('Você foi desconectado com sucesso.', 'info')
    return redirect(url_for('auth.login'))
