"""
Rotas de autenticação da Agenda Escolar (Login e Logout por matrícula).
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import Teacher

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('agenda.home'))

    if request.method == 'POST':
        registration = request.form.get('registration')
        teacher = Teacher.query.filter_by(registration=registration).first()

        if teacher:
            login_user(teacher)
            flash(f'Bem-vindo(a), {teacher.name}!', 'success')
            return redirect(url_for('agenda.home'))
        else:
            flash('Matrícula inválida.', 'danger')

    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você foi desconectado com sucesso.', 'info')
    return redirect(url_for('auth.login'))
