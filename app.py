# Adicione 'session' aqui
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, session
import os
import json
import subprocess
import shutil
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, date
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, session
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from functools import wraps
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from sqlalchemy import func
from models import db, Usuario, Escola, UsuarioEscola, Resource, ScheduleTemplate, Booking
from flask_migrate import Migrate
from celery import Celery
from logging import getLogger

migrate = Migrate()
mail = Mail()
login_manager = LoginManager()
serializer = None  # Será inicializado depois

# --- INICIALIZAÇÃO E CONFIGURAÇÃO DA APLICAÇÃO ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'uma-chave-secreta-muito-dificil-de-adivinhar'

# Configura o Serializer com a secret key
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# --- CONFIGURAÇÃO DO BANCO DE DADOS ---
DATA_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'data')
os.makedirs(DATA_DIR, exist_ok=True)
database_uri = os.environ.get(
    'DATABASE_URL', 'sqlite:///' + os.path.join(DATA_DIR, 'agenda.db'))
if database_uri.startswith("postgres://"):
    database_uri = database_uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
BACKUP_FOLDER = os.path.join(DATA_DIR, 'backups')
os.makedirs(BACKUP_FOLDER, exist_ok=True)

# --- CONFIGURAÇÃO DE E-MAIL (lendo do .env) ---
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get(
    'MAIL_USE_TLS', 'True').lower() in ['true', 'on', '1']
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = (
    'Agenda Escolar', os.environ.get('MAIL_DEFAULT_SENDER'))

# --- CONFIGURAÇÃO CELERY ---
app.config['CELERY_BROKER_URL'] = os.environ.get(
    'CELERY_BROKER_URL', 'redis://localhost:6379/0')
app.config['CELERY_RESULT_BACKEND'] = os.environ.get(
    'CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')


def make_celery(app):
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL']
    )
    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)
    celery.Task = ContextTask
    return celery


celery = make_celery(app)

# --- LIGA AS EXTENSÕES COM A APLICAÇÃO (DEPOIS de configurar) ---
db.init_app(app)
migrate.init_app(app, db)
mail.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Você precisa fazer login para acessar esta página."
login_manager.login_message_category = "warning"


@celery.task
def restore_task_bg(filepath, db_uri_str):
    """Executa o pg_restore em segundo plano."""
    log = getLogger(__name__)
    log.info(f"Iniciando restauração do arquivo: {filepath}")
    try:
        # Extrai os detalhes da conexão da URI
        parsed_uri = urlparse(db_uri_str)
        db_name, user, password, host, port = parsed_uri.path.lstrip(
            '/'), parsed_uri.username, parsed_uri.password, parsed_uri.hostname, parsed_uri.port

        env = os.environ.copy()
        env['PGPASSWORD'] = password

        command = [
            'pg_restore',
            '--host', host,
            '--port', str(port),
            '--username', user,
            '--dbname', db_name,
            '--no-password',
            '--clean',
            '--if-exists',
            filepath
        ]

        # Executa o comando sem capturar a saída para evitar deadlocks
        subprocess.run(command, check=True, env=env, stdin=subprocess.DEVNULL)
        log.info(f"Restauração do arquivo {filepath} concluída com sucesso!")

    except Exception as e:
        log.error(f"Falha na restauração do backup: {str(e)}")
    finally:
        # Remove o arquivo de upload após a tentativa de restauração
        if os.path.exists(filepath):
            os.remove(filepath)
            log.info(f"Arquivo de backup temporário {filepath} removido.")


@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

# --- DECORATOR PARA PROTEGER ROTAS DE ADMINISTRAÇÃO ---


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Acesso restrito a administradores.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# --- ROTAS DE AUTENTICAÇÃO ---


@app.route('/')
def root():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    return redirect(url_for('login'))


# Em app.py


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = Usuario.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user)

            # --- NOVA LÓGICA AQUI ---
            # Encontra a primeira associação de escola do usuário
            primeira_associacao = user.escolas.first()
            if primeira_associacao:
                # Guarda o ID da escola na sessão do usuário
                session['escola_id'] = primeira_associacao.escola_id
            else:
                # Se o usuário não estiver em nenhuma escola (raro, mas possível)
                session['escola_id'] = None

            flash(f'Bem-vindo(a), {user.nome}!', 'success')
            return redirect(url_for('home'))
        else:
            flash('E-mail ou senha inválidos.', 'danger')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você foi desconectado com sucesso.', 'info')
    return redirect(url_for('login'))

# --- ROTAS PRINCIPAIS ---


# Em app.py
@app.route('/home')
@login_required
def home():
    # Verifica se o ID da escola está na sessão
    escola_id = session.get('escola_id')
    if not escola_id:
        flash("Você não está associado a nenhuma escola.", "warning")
        return redirect(url_for('logout'))  # Ou uma página de erro

    # Busca apenas os recursos da escola do usuário logado
    resources = Resource.query.filter_by(escola_id=escola_id).order_by(
        Resource.sort_order, Resource.name).all()

    return render_template('index.html', resources=resources)


@app.route('/resource/<int:resource_id>')
@login_required
def select_shift(resource_id):
    """Esta rota agora carrega a nova página de agenda dinâmica."""
    escola_id = session.get('escola_id')
    # Garante que o recurso pertence à escola do usuário
    resource = Resource.query.filter_by(
        id=resource_id, escola_id=escola_id).first_or_404()

    # --- CORREÇÃO AQUI ---
    # Busca apenas os usuários associados à escola atual
    usuarios = Usuario.query.join(UsuarioEscola).filter(
        UsuarioEscola.escola_id == escola_id).order_by(Usuario.nome).all()

    # --- LÓGICA ATUALIZADA PARA A DATA INICIAL ---
    # Pega a data de hoje como base
    initial_date = date.today()
    weekday = initial_date.weekday()  # Segunda-feira é 0, Sábado é 5, Domingo é 6

    # Se for Sábado (5), avança 2 dias para a próxima Segunda-feira
    if weekday == 5:
        initial_date += timedelta(days=2)
    # Se for Domingo (6), avança 1 dia para a próxima Segunda-feira
    elif weekday == 6:
        initial_date += timedelta(days=1)

    return render_template('agenda.html', resource=resource, teachers=usuarios, current_date=initial_date)


@app.route('/api/agenda/<int:resource_id>/<string:date_str>')
@login_required
def get_agenda_data(resource_id, date_str):
    """(VERSÃO CORRIGIDA E ROBUSTA) Retorna os dados da agenda em formato JSON."""
    escola_id = session.get('escola_id')
    # Verifica se o recurso acessado pertence à escola
    Resource.query.filter_by(
        id=resource_id, escola_id=escola_id).first_or_404()

    try:
        current_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Formato de data inválido'}), 400

    templates = ScheduleTemplate.query.filter_by(resource_id=resource_id).all()
    # Adiciona o filtro de escola na busca por agendamentos
    bookings = Booking.query.filter_by(
        resource_id=resource_id, date=current_date, escola_id=escola_id).all()

    booked_slots = {(b.shift, b.slot_name): b for b in bookings}

    agenda_data = {}
    for template in templates:
        shift_slots = []

        if not isinstance(template.slots, list):
            continue

        for slot in template.slots:
            if not isinstance(slot, dict) or 'name' not in slot or 'type' not in slot:
                continue

            booking = booked_slots.get((template.shift, slot['name']))

            booked_by_name = None
            if booking:
                if booking.status == 'closed':
                    booked_by_name = 'Fechado'
                else:
                    booked_by_name = booking.teacher_name

            slot_info = {
                'name': slot.get('name', 'Inválido'),
                'type': slot.get('type', 'aula'),
                'booked_by': booked_by_name,
                'booking_id': booking.id if booking else None,
                # --- CORREÇÃO AQUI ---
                # Trocamos booking.teacher_id por booking.usuario_id
                'is_mine': booking.usuario_id == current_user.id if booking else False,
                'is_admin': current_user.is_admin
            }
            shift_slots.append(slot_info)
        agenda_data[template.shift] = shift_slots

    return jsonify(agenda_data)


@app.route('/agenda/close', methods=['POST'])
@login_required
def close_slot():
    if not current_user.is_admin:
        return jsonify({'error': 'Acesso negado'}), 403

    escola_id = session.get('escola_id')
    resource_id = request.form.get('resource_id')
    date_str = request.form.get('date')
    shift = request.form.get('shift')
    slot_name = request.form.get('slot_name')

    # Validação
    Resource.query.filter_by(
        id=resource_id, escola_id=escola_id).first_or_404()

    try:
        booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        if Booking.query.filter_by(resource_id=resource_id, date=booking_date, slot_name=slot_name, shift=shift, escola_id=escola_id).first():
            flash('Este horário já foi agendado ou fechado.', 'warning')
        else:
            new_booking = Booking(
                escola_id=escola_id,
                resource_id=int(resource_id),
                date=booking_date,
                slot_name=slot_name,
                shift=shift,
                usuario_id=current_user.id,  # <-- CORREÇÃO AQUI
                teacher_name="Fechado",
                status='closed'
            )
            db.session.add(new_booking)
            db.session.commit()
            flash('Horário marcado como fechado com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ocorreu um erro ao tentar fechar o horário: {e}', 'danger')

    return redirect(url_for('select_shift', resource_id=resource_id, date=date_str, shift=shift))


@app.route('/agenda/book', methods=['POST'])
@login_required
def book_slot():
    escola_id = session.get('escola_id')
    resource_id = request.form.get('resource_id')
    date_str = request.form.get('date')
    slot_name = request.form.get('slot_name')
    shift = request.form.get('shift')

    # Validação para garantir que o recurso pertence à escola
    Resource.query.filter_by(
        id=resource_id, escola_id=escola_id).first_or_404()

    if Booking.query.filter_by(resource_id=resource_id, date=datetime.strptime(date_str, '%Y-%m-%d').date(), slot_name=slot_name, shift=shift, escola_id=escola_id).first():
        flash('Este horário foi agendado por outra pessoa.', 'warning')
        return redirect(url_for('select_shift', resource_id=resource_id, date=date_str, shift=shift))

    book_for_teacher = current_user
    if current_user.is_admin:
        selected_teacher_id = request.form.get('teacher_id')
        if selected_teacher_id:
            # --- CORREÇÃO AQUI ---
            # Trocamos Teacher por Usuario
            book_for_teacher = Usuario.query.get(int(selected_teacher_id))

    new_booking = Booking(
        escola_id=escola_id,
        resource_id=int(resource_id),
        date=datetime.strptime(date_str, '%Y-%m-%d').date(),
        slot_name=slot_name,
        shift=shift,
        usuario_id=book_for_teacher.id,
        teacher_name=book_for_teacher.nome
    )
    db.session.add(new_booking)
    db.session.commit()
    flash('Horário agendado com sucesso!', 'success')
    return redirect(url_for('select_shift', resource_id=resource_id, date=date_str, shift=shift))


@app.route('/agenda/booking/delete/<int:booking_id>')
@login_required
def delete_booking(booking_id):
    escola_id = session.get('escola_id')
    # Busca o agendamento E verifica se ele pertence à escola do usuário
    booking = Booking.query.filter_by(
        id=booking_id, escola_id=escola_id).first_or_404()
    resource_id = booking.resource_id
    date_str = request.args.get('date')
    shift = request.args.get('shift')  # Captura o turno da URL

    if current_user.is_admin or booking.usuario_id == current_user.id:
        db.session.delete(booking)
        db.session.commit()
        flash('Agendamento removido com sucesso.', 'success')
    else:
        flash('Você não tem permissão para remover este agendamento.', 'danger')

    # Redireciona com 'date' e o 'shift'
    return redirect(url_for('select_shift', resource_id=resource_id, date=date_str, shift=shift))

# --- ROTAS DE ADMINISTRAÇÃO (sem alterações) ---


@app.route('/admin')
@admin_required
def admin_dashboard():
    escola_id = session.get('escola_id')
    # ADICIONA O FILTRO DE ESCOLA NA CONSULTA DE RECURSOS
    resources = Resource.query.filter_by(escola_id=escola_id).order_by(
        Resource.sort_order, Resource.name).all()
    return render_template('admin_dashboard.html', resources=resources)


def reorder_resources():
    escola_id = session.get('escola_id')
    ordered_ids = request.form.get('order', '').split(',')
    if ordered_ids and ordered_ids[0] != '':
        for index, resource_id_str in enumerate(ordered_ids):
            # Garante que o admin só possa reordenar recursos da sua própria escola
            resource = Resource.query.filter_by(
                id=int(resource_id_str), escola_id=escola_id).first()
            if resource:
                resource.sort_order = index
        db.session.commit()
        flash('A ordem dos recursos foi salva com sucesso!', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/resource/add', methods=['POST'])
@admin_required
def add_resource():
    name = request.form.get('name')
    # 1. Pega o ID da escola da sessão do usuário
    escola_id = session.get('escola_id')

    if not escola_id:
        flash('Erro: Não foi possível identificar a sua escola. Por favor, faça login novamente.', 'danger')
        return redirect(url_for('admin_dashboard'))

    if name:
        # 2. Adiciona o escola_id ao criar o novo recurso
        new_resource = Resource(
            name=name,
            description=request.form.get('description'),
            icon=request.form.get('icon') or 'bi-box',
            escola_id=escola_id
        )
        db.session.add(new_resource)
        db.session.commit()
        flash('Recurso adicionado com sucesso!', 'success')
    else:
        flash('O nome do recurso é obrigatório.', 'danger')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/resource/edit/<int:resource_id>', methods=['POST'])
@admin_required
def edit_resource(resource_id):
    escola_id = session.get('escola_id')
    # Garante que o admin só possa editar um recurso da sua própria escola
    resource = Resource.query.filter_by(
        id=resource_id, escola_id=escola_id).first_or_404()
    name = request.form.get('name')
    if name:
        resource.name = name
        resource.description = request.form.get('description')
        resource.icon = request.form.get('icon') or 'bi-box'
        db.session.commit()
        flash('Recurso atualizado com sucesso!', 'success')
    else:
        flash('O nome do recurso não pode ficar em branco.', 'danger')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/resource/delete/<int:resource_id>')
@admin_required
def delete_resource(resource_id):
    escola_id = session.get('escola_id')
    # Garante que o admin só possa deletar um recurso da sua própria escola
    resource = Resource.query.filter_by(
        id=resource_id, escola_id=escola_id).first_or_404()

    # A lógica de deleção em cascata já remove os Bookings e ScheduleTemplates associados
    db.session.delete(resource)
    db.session.commit()
    flash('Recurso e todos os seus dados foram removidos com sucesso!', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/resource/copy/<int:original_id>', methods=['POST'])
@admin_required
def copy_resource(original_id):
    # Pega o ID da escola da sessão do usuário
    escola_id = session.get('escola_id')
    if not escola_id:
        flash('Erro: Não foi possível identificar a sua escola.', 'danger')
        return redirect(url_for('admin_dashboard'))

    # Garante que o recurso original pertence à escola do usuário
    original_resource = Resource.query.filter_by(
        id=original_id, escola_id=escola_id).first_or_404()

    new_name = request.form.get('new_name')
    new_icon = request.form.get('new_icon') or 'bi-box'

    if not new_name:
        flash('O novo nome do recurso é obrigatório.', 'danger')
        return redirect(url_for('admin_dashboard'))

    new_resource = Resource(
        name=new_name,
        description=original_resource.description,
        icon=new_icon,
        sort_order=original_resource.sort_order + 1,
        escola_id=escola_id  # Adiciona o ID da escola à nova cópia
    )
    db.session.add(new_resource)
    db.session.commit()  # Commit para que o new_resource tenha um ID

    # Copia os templates de horário do recurso original para o novo
    for template in original_resource.schedule_templates:
        new_template = ScheduleTemplate(
            resource_id=new_resource.id,
            shift=template.shift,
            slots=template.slots
        )
        db.session.add(new_template)

    db.session.commit()
    flash(
        f'Recurso "{original_resource.name}" copiado com sucesso para "{new_name}"!', 'success')
    return redirect(url_for('admin_dashboard'))

# Em app.py, junto com as outras rotas de administração


@app.route('/admin/resources/reorder', methods=['POST'])
@admin_required
def reorder_resources():
    escola_id = session.get('escola_id')
    ordered_ids = request.form.get('order', '').split(',')
    if ordered_ids and ordered_ids[0] != '':
        for index, resource_id_str in enumerate(ordered_ids):
            # Garante que o admin só possa reordenar recursos da sua própria escola
            resource = Resource.query.filter_by(
                id=int(resource_id_str), escola_id=escola_id).first()
            if resource:
                resource.sort_order = index
        db.session.commit()
        flash('A ordem dos recursos foi salva com sucesso!', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/schedules/<int:resource_id>', methods=['GET', 'POST'])
@admin_required
def manage_schedules(resource_id):
    escola_id = session.get('escola_id')
    # Garante que o admin só possa gerenciar horários de um recurso da sua própria escola
    resource = Resource.query.filter_by(
        id=resource_id, escola_id=escola_id).first_or_404()

    if request.method == 'POST':
        # ... (o resto da lógica da função continua igual)
        shift = request.form.get('shift')
        slot_names = request.form.getlist('slot_name')
        slot_types = request.form.getlist('slot_type')
        slots_data = [{"name": name, "type": type}
                      for name, type in zip(slot_names, slot_types) if name]
        schedule = ScheduleTemplate.query.filter_by(
            shift=shift, resource_id=resource_id).first()
        if schedule:
            schedule.slots = slots_data
        else:
            schedule = ScheduleTemplate(
                shift=shift, slots=slots_data, resource_id=resource_id)
            db.session.add(schedule)
        db.session.commit()
        flash(
            f'Horários do turno {shift} para {resource.name} salvos com sucesso!', 'success')
        return redirect(url_for('manage_schedules', resource_id=resource_id))

    matutino_schedule = ScheduleTemplate.query.filter_by(
        shift='matutino', resource_id=resource_id).first()
    vespertino_schedule = ScheduleTemplate.query.filter_by(
        shift='vespertino', resource_id=resource_id).first()
    return render_template('admin_schedules.html',
                           resource=resource,
                           matutino_schedule=matutino_schedule,
                           vespertino_schedule=vespertino_schedule)


@app.route('/admin/teachers', methods=['GET', 'POST'])
@admin_required
def manage_teachers():
    # Futuramente, vamos pegar a escola do admin logado.
    # Por enquanto, como só temos uma, vamos usar a primeira.
    escola_atual = Escola.query.first()
    if not escola_atual:
        flash('Nenhuma escola encontrada. Crie uma escola primeiro.', 'danger')
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        # 1. Obter os novos dados do formulário
        nome = request.form.get('name')
        email = request.form.get('email')
        senha = request.form.get('password')  # Campo novo
        papel = 'admin' if 'is_admin' in request.form else 'professor'
        matricula = request.form.get('registration')  # Agora é opcional

        # 2. Validações
        if not all([nome, email, senha]):
            flash('Nome, e-mail e senha são obrigatórios.', 'danger')
        elif Usuario.query.filter_by(email=email).first():
            flash('O e-mail informado já está cadastrado.', 'warning')
        else:
            # 3. Criar o novo usuário e associá-lo à escola
            novo_usuario = Usuario(nome=nome, email=email)
            novo_usuario.set_password(senha)

            associacao = UsuarioEscola(
                usuario=novo_usuario,
                escola=escola_atual,
                papel=papel,
                matricula=matricula
            )

            db.session.add(novo_usuario)
            db.session.add(associacao)
            db.session.commit()
            flash('Usuário cadastrado com sucesso!', 'success')
        return redirect(url_for('manage_teachers'))

    # Busca apenas usuários associados à escola atual
    membros = UsuarioEscola.query.filter_by(escola_id=escola_atual.id).all()
    return render_template('admin_teachers.html', membros=membros)


@app.route('/admin/user/edit/<int:user_id>', methods=['POST'])
@admin_required
def edit_user(user_id):
    # Por enquanto, estamos assumindo que a edição ocorre no contexto da primeira escola
    escola_atual = Escola.query.first()

    usuario = Usuario.query.get_or_404(user_id)
    associacao = UsuarioEscola.query.filter_by(
        usuario_id=user_id, escola_id=escola_atual.id).first_or_404()

    new_email = request.form.get('email')

    # Verifica se o novo e-mail já está em uso por OUTRO usuário
    existing_user = Usuario.query.filter(
        Usuario.id != user_id, Usuario.email == new_email).first()
    if existing_user:
        flash(
            f'O e-mail "{new_email}" já está em uso por outro usuário.', 'danger')
        return redirect(url_for('manage_teachers'))

    # Atualiza os dados do usuário
    usuario.nome = request.form.get('name')
    usuario.email = new_email

    # Atualiza os dados da associação
    associacao.papel = 'admin' if 'is_admin' in request.form else 'professor'
    associacao.matricula = request.form.get('registration')

    db.session.commit()
    flash('Usuário atualizado com sucesso!', 'success')
    return redirect(url_for('manage_teachers'))


@app.route('/admin/user/delete/<int:user_id>')
@admin_required
def delete_user(user_id):
    if current_user.id == user_id:
        flash('Você não pode se auto-excluir.', 'danger')
        return redirect(url_for('manage_teachers'))

    usuario = Usuario.query.get_or_404(user_id)

    # Apaga agendamentos, associações e por fim o usuário
    Booking.query.filter_by(usuario_id=user_id).delete()
    UsuarioEscola.query.filter_by(usuario_id=user_id).delete()
    db.session.delete(usuario)

    db.session.commit()
    flash('Usuário e seus dados foram removidos com sucesso.', 'success')
    return redirect(url_for('manage_teachers'))


@app.route('/admin/teacher/edit/<int:teacher_id>', methods=['POST'])
@admin_required
def edit_teacher(teacher_id):
    teacher = Teacher.query.get_or_404(teacher_id)
    new_registration = request.form.get('registration')

    existing_teacher = Teacher.query.filter(
        Teacher.id != teacher_id, Teacher.registration == new_registration).first()
    if existing_teacher:
        flash(
            f'A matrícula "{new_registration}" já está em uso por outro usuário.', 'danger')
        return redirect(url_for('manage_teachers'))

    teacher.name = request.form.get('name')
    teacher.registration = new_registration
    teacher.is_admin = 'is_admin' in request.form
    db.session.commit()
    flash('Usuário atualizado com sucesso!', 'success')
    return redirect(url_for('manage_teachers'))


@app.route('/admin/teacher/delete/<int:teacher_id>')
@admin_required
def delete_teacher(teacher_id):
    if current_user.id == teacher_id:
        flash('Você não pode se auto-excluir.', 'danger')
        return redirect(url_for('manage_teachers'))

    teacher = Teacher.query.get_or_404(teacher_id)
    Booking.query.filter_by(teacher_id=teacher_id).delete()
    db.session.delete(teacher)
    db.session.commit()
    flash('Usuário e seus agendamentos foram removidos com sucesso.', 'success')
    return redirect(url_for('manage_teachers'))


@app.route('/admin/weekly-view')
@app.route('/admin/weekly-view/<string:date_str>')
@admin_required
def weekly_view(date_str=None):
    escola_id = session.get('escola_id')
    base_date = datetime.strptime(
        date_str, '%Y-%m-%d').date() if date_str else date.today()
    start_of_week = base_date - timedelta(days=base_date.weekday())
    end_of_week = start_of_week + timedelta(days=4)
    prev_week_date = (start_of_week - timedelta(days=7)).strftime('%Y-%m-%d')
    next_week_date = (start_of_week + timedelta(days=7)).strftime('%Y-%m-%d')

    week_headers = []
    day_map = {0: "Segunda", 1: "Terça", 2: "Quarta", 3: "Quinta", 4: "Sexta"}
    for i in range(5):
        current_day_date = start_of_week + timedelta(days=i)
        week_headers.append(
            {'name': day_map[i], 'date': current_day_date.strftime('%d/%m')})

    # ADICIONA O FILTRO DE ESCOLA NA CONSULTA DE AGENDAMENTOS
    all_week_bookings = Booking.query.filter(
        Booking.escola_id == escola_id,
        Booking.date.between(start_of_week, end_of_week)
    ).all()

    weekly_summaries = []

    colors = ['bg-success', 'bg-primary', 'bg-warning',
              'bg-info', 'bg-secondary', 'bg-dark']

    # ADICIONA O FILTRO DE ESCOLA NA CONSULTA DE RECURSOS
    resources_with_schedules = Resource.query.join(ScheduleTemplate).filter(
        Resource.escola_id == escola_id
    ).order_by(Resource.sort_order, Resource.name).distinct()

    for index, resource in enumerate(resources_with_schedules):
        color_class = colors[index % len(colors)]

        for template in sorted(resource.schedule_templates, key=lambda t: t.shift):
            weekly_bookings_data = {}
            resource_bookings = [
                b for b in all_week_bookings if b.resource_id == resource.id and b.shift == template.shift]

            for booking in resource_bookings:
                day_name = day_map.get(booking.date.weekday())
                if day_name:
                    if day_name not in weekly_bookings_data:
                        weekly_bookings_data[day_name] = {}
                    weekly_bookings_data[day_name][booking.slot_name] = booking

            weekly_summaries.append({
                'title': f'{resource.name} - {template.shift.capitalize()}',
                'icon': resource.icon, 'week_headers': week_headers, 'schedule_template': template,
                'weekly_bookings': weekly_bookings_data, 'color_class': color_class
            })

    return render_template('admin_weekly_view.html', weekly_summaries=weekly_summaries,
                           start_date_formatted=start_of_week.strftime('%d/%m/%Y'), end_date_formatted=end_of_week.strftime('%d/%m/%Y'),
                           prev_week_link=prev_week_date, next_week_link=next_week_date)


@app.route('/admin/reports', methods=['GET', 'POST'])
@admin_required
def reports():
    escola_id = session.get('escola_id')
    # ADICIONA O FILTRO DE ESCOLA NA CONSULTA DE RECURSOS
    resources = Resource.query.filter_by(
        escola_id=escola_id).order_by(Resource.name).all()
    report_data, selected_resource_id, start_date_str, end_date_str = None, None, '', ''

    chart_labels, chart_data = [], []

    if request.method == 'POST':
        try:
            selected_resource_id = int(request.form.get('resource_id'))
            start_date_str = request.form.get('start_date')
            end_date_str = request.form.get('end_date')
            start_date = datetime.strptime(start_date_str, '%d/%m/%Y').date()
            end_date = datetime.strptime(end_date_str, '%d/%m/%Y').date()

            # ADICIONA O FILTRO DE ESCOLA NA CONSULTA PRINCIPAL DO RELATÓRIO
            report_query = db.session.query(Booking.teacher_name, func.count(Booking.id)).filter(
                Booking.escola_id == escola_id,
                Booking.resource_id == selected_resource_id,
                Booking.date.between(start_date, end_date),
                Booking.status == 'booked').group_by(Booking.teacher_name).order_by(func.count(Booking.id).desc())

            report_data = report_query.all()

            if report_data:
                labels, data = zip(*report_data)
                chart_labels = json.dumps(list(labels))
                chart_data = json.dumps(list(data))

        except (ValueError, TypeError):
            flash(
                'Filtros inválidos. Verifique o recurso e as datas (dd/mm/aaaa).', 'danger')

    return render_template('admin_reports.html', resources=resources, report_data=report_data,
                           selected_resource_id=selected_resource_id, start_date=start_date_str, end_date=end_date_str,
                           chart_labels=chart_labels, chart_data=chart_data)


@app.route('/my-bookings')
@login_required
def my_bookings():
    """Exibe os agendamentos futuros do usuário logado."""
    today = date.today()

    # Dicionário para traduzir os dias da semana
    weekdays_pt = {
        0: "Segunda-feira", 1: "Terça-feira", 2: "Quarta-feira",
        3: "Quinta-feira", 4: "Sexta-feira", 5: "Sábado", 6: "Domingo"
    }

    # Busca os agendamentos futuros do professor, juntando com os dados do recurso
    bookings_query = db.session.query(Booking, Resource)\
        .join(Resource, Booking.resource_id == Resource.id)\
        .filter(Booking.usuario_id == current_user.id)\
        .filter(Booking.escola_id == session.get('escola_id'))\
        .order_by(Booking.date, Booking.shift)\
        .all()

    return render_template('my_bookings.html', bookings=bookings_query, weekdays_pt=weekdays_pt)


@app.route('/my-bookings/delete/<int:booking_id>', methods=['POST'])
@login_required
def delete_my_booking(booking_id):
    """Remove um agendamento a partir da página 'Meus Agendamentos'."""
    escola_id = session.get('escola_id')

    # Busca o agendamento E garante que ele pertence à escola do usuário
    booking = Booking.query.filter_by(
        id=booking_id, escola_id=escola_id).first_or_404()

    # --- CORREÇÃO AQUI ---
    # Garante que o usuário só pode apagar seus próprios agendamentos, usando o campo correto
    if booking.usuario_id == current_user.id or current_user.is_admin:
        db.session.delete(booking)
        db.session.commit()
        flash('Agendamento removido com sucesso.', 'success')
    else:
        flash('Você não tem permissão para remover este agendamento.', 'danger')

    return redirect(url_for('my_bookings'))

# --- COMANDOS CLI ---


@app.cli.command("seed-db")
def seed_db_command():
    """Cria os dados iniciais para o ambiente multi-tenant."""

    # 1. Cria o usuário Super Admin
    # Use um e-mail real seu para o super admin
    super_admin_email = 'jardelberti@gmail.com'
    if not Usuario.query.filter_by(email=super_admin_email).first():
        print('Criando usuário Super Admin...')
        super_admin = Usuario(
            nome='Administrador Geral',
            email=super_admin_email,
            is_superadmin=True
        )
        # IMPORTANTE: Defina uma senha forte aqui!
        super_admin.set_password('admnistrador@agenda123')
        db.session.add(super_admin)
    else:
        super_admin = Usuario.query.filter_by(email=super_admin_email).first()
        print('Usuário Super Admin já existe.')

    # 2. Cria a primeira escola
    escola_padrao_nome = 'Minha Primeira Escola'
    escola = Escola.query.filter_by(nome=escola_padrao_nome).first()
    if not escola:
        print(f'Criando escola padrão: {escola_padrao_nome}...')
        escola = Escola(nome=escola_padrao_nome, status='ativo')
        db.session.add(escola)
    else:
        print('Escola padrão já existe.')

    # Força o commit para garantir que super_admin e escola tenham IDs
    db.session.commit()

    # 3. Associa o Super Admin à primeira escola
    associacao = UsuarioEscola.query.filter_by(
        usuario_id=super_admin.id,
        escola_id=escola.id
    ).first()

    if not associacao:
        print('Associando Super Admin à escola padrão...')
        nova_associacao = UsuarioEscola(
            usuario_id=super_admin.id,
            escola_id=escola.id,
            papel='admin',  # O super admin também é admin da primeira escola
            matricula='SUPERADMIN'
        )
        db.session.add(nova_associacao)
    else:
        print('Associação do Super Admin com a escola padrão já existe.')

    db.session.commit()
    print('Banco de dados inicializado com sucesso!')


@app.route('/admin/backup-restore')
@admin_required
def backup_restore_page():
    """Renderiza a página de backup e restauração."""
    return render_template('admin_backup_restore.html')


@app.route('/admin/backup')
@admin_required
def backup_database():
    """Cria um backup do banco de dados e o oferece para download."""
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    try:
        # Lógica para PostgreSQL
        if db_uri.startswith('postgresql'):
            filename = f'backup_postgres_{timestamp}.sql'
            filepath = os.path.join(BACKUP_FOLDER, filename)

            # Extrai os detalhes da conexão da URI
            parsed_uri = urlparse(db_uri)
            db_name = parsed_uri.path.lstrip('/')
            user = parsed_uri.username
            password = parsed_uri.password
            host = parsed_uri.hostname
            port = parsed_uri.port

            # Define a variável de ambiente PGPASSWORD para segurança
            env = os.environ.copy()
            env['PGPASSWORD'] = password

            # Comando para o pg_dump
            command = [
                'pg_dump',
                '--host', host,
                '--port', str(port),
                '--username', user,
                '--dbname', db_name,
                '--no-password',
                '--format=c',  # Formato customizado, mais robusto
                '--blobs',
                '--no-owner',
                '--file', filepath
            ]

            subprocess.run(command, check=True, env=env)
            flash('Backup do PostgreSQL gerado com sucesso!', 'success')

        # Lógica para SQLite
        elif db_uri.startswith('sqlite'):
            filename = f'backup_sqlite_{timestamp}.db'
            filepath = os.path.join(BACKUP_FOLDER, filename)

            # O caminho do DB SQLite está após 'sqlite:///'
            db_path = db_uri.split('///')[1]
            shutil.copy2(db_path, filepath)
            flash('Backup do SQLite gerado com sucesso!', 'success')

        else:
            flash('Tipo de banco de dados não suportado para backup.', 'danger')
            return redirect(url_for('backup_restore_page'))

        return send_from_directory(BACKUP_FOLDER, filename, as_attachment=True)

    except Exception as e:
        flash(f'Erro ao gerar o backup: {str(e)}', 'danger')
        return redirect(url_for('backup_restore_page'))


@app.route('/admin/restore', methods=['POST'])
@admin_required
def restore_database():
    """Salva o arquivo e agenda a restauração em segundo plano."""
    if 'backup_file' not in request.files:
        flash('Nenhum arquivo selecionado.', 'danger')
        return redirect(url_for('backup_restore_page'))

    file = request.files['backup_file']
    if file.filename == '':
        flash('Nenhum arquivo selecionado.', 'danger')
        return redirect(url_for('backup_restore_page'))

    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(BACKUP_FOLDER, filename)
        file.save(filepath)

        db_uri_str = app.config['SQLALCHEMY_DATABASE_URI']

        # Chama a tarefa em segundo plano, passando o caminho do arquivo
        restore_task_bg.delay(filepath, db_uri_str)

        flash('Restauração iniciada em segundo plano! O processo pode levar alguns minutos para ser concluído.', 'success')

    return redirect(url_for('backup_restore_page'))


@app.route('/admin/user/send-reset-link/<int:user_id>')
@admin_required
def send_reset_link(user_id):
    user = Usuario.query.get_or_404(user_id)
    if send_password_reset_email(user):
        flash(
            f'Um link de redefinição de senha foi enviado para {user.email}.', 'success')
    else:
        flash(
            f'Ocorreu um erro ao tentar enviar o e-mail para {user.email}.', 'danger')

    return redirect(url_for('manage_teachers'))


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        # Tenta decodificar o token. Se expirar ou for inválido, gera uma exceção.
        email = serializer.loads(
            token, salt='password-reset-salt', max_age=3600)
    except Exception as e:
        flash('O link de redefinição de senha é inválido ou expirou.', 'danger')
        return redirect(url_for('login'))

    user = Usuario.query.filter_by(email=email).first_or_404()

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if new_password != confirm_password:
            flash('As senhas não coincidem.', 'danger')
            return render_template('reset_password.html', token=token)

        user.set_password(new_password)
        db.session.commit()

        flash(
            'Sua senha foi atualizada com sucesso! Você já pode fazer o login.', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html', token=token)


def send_password_reset_email(user):
    """Gera o token e envia o e-mail de redefinição de senha."""
    try:
        token = serializer.dumps(user.email, salt='password-reset-salt')
        reset_url = url_for('reset_password', token=token, _external=True)

        # URL completa para a logo
        logo_url = url_for(
            'static', filename='logo_agenda.png', _external=True)

        # Renderiza o template HTML do e-mail
        html_body = render_template('email/reset_password_email.html',
                                    user=user,
                                    reset_url=reset_url,
                                    logo_url=logo_url)

        # Cria a mensagem com o corpo em HTML
        msg = Message('Redefinição de Senha - Agenda Escolar',
                      recipients=[user.email],
                      html=html_body)

        mail.send(msg)
        return True  # Retorna sucesso
    except Exception as e:
        # Em um app real, seria bom logar este erro
        print(f"Erro ao enviar e-mail: {e}")
        return False  # Retorna falha


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = Usuario.query.filter_by(email=email).first()

        # Por segurança, não informamos se o e-mail foi encontrado ou não
        # Apenas enviamos o e-mail se o usuário existir
        if user:
            # Aqui vamos reutilizar a mesma lógica de envio de e-mail do admin
            send_password_reset_email(user)

        flash('Se um usuário com este e-mail existir em nosso sistema, um link de redefinição de senha foi enviado.', 'success')
        return redirect(url_for('login'))

    return render_template('forgot_password.html')


if __name__ == '__main__':
    app.run()
