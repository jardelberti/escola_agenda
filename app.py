import os
import json
import subprocess
import shutil
import io
import csv
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime, timedelta, date
import calendar
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, session, Response
from functools import wraps
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from sqlalchemy import func, distinct
from models import db, Usuario, Escola, UsuarioEscola, Resource, ScheduleTemplate, Booking, Plano, Assinatura, Disciplina
from flask_migrate import Migrate
from celery import Celery
from logging import getLogger
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Mail, Message
from dateutil.relativedelta import relativedelta
import stripe
from PIL import Image
from authlib.integrations.flask_client import OAuth

migrate = Migrate()
mail = Mail()
login_manager = LoginManager()
serializer = None  # Será inicializado depois
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

# --- INICIALIZAÇÃO E CONFIGURAÇÃO DA APLICAÇÃO ---
app = Flask(__name__)
if app.config['DEBUG']:
    app.config['SERVER_NAME'] = 'localhost:5000'
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
DATA_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'data')
os.makedirs(DATA_DIR, exist_ok=True)
UPLOAD_FOLDER = os.path.join(DATA_DIR, 'profile_pics')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['SECRET_KEY'] = 'uma-chave-secreta-muito-dificil-de-adivinhar'

oauth = OAuth(app)
oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)

oauth.register(
    name='microsoft',
    client_id=os.environ.get("MICROSOFT_CLIENT_ID"),
    client_secret=os.environ.get("MICROSOFT_CLIENT_SECRET"),
    access_token_url='https://login.microsoftonline.com/common/oauth2/v2.0/token',
    access_token_params=None,
    authorize_url='https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
    authorize_params=None,
    api_base_url='https://graph.microsoft.com/v1.0/',
    client_kwargs={'scope': 'User.Read'}
)


@app.before_request
def make_session_permanent():
    session.permanent = True
    # Define a duração da sessão, por exemplo, 15 minutos de inatividade
    app.permanent_session_lifetime = timedelta(minutes=15)


# Configura o Serializer com a secret key
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# --- CONFIGURAÇÃO DO BANCO DE DADOS ---

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


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower(
           ) in app.config['ALLOWED_EXTENSIONS']


@app.context_processor
def inject_escola_info():
    """ Injeta informações da escola atual em todos os templates. """
    if current_user.is_authenticated and 'escola_id' in session and session['escola_id']:
        escola = Escola.query.get(session['escola_id'])
        return dict(escola_atual=escola)
    return dict(escola_atual=None)


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


def superadmin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_superadmin:
            flash('Acesso restrito ao Super Administrador.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# --- ROTAS DE AUTENTICAÇÃO ---


@app.route('/')
def landing_page():
    # Se o utilizador já estiver logado, vai para a home normal
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    # Busca os planos para exibir na seção de preços da landing page
    planos = Plano.query.order_by(Plano.preco).all()

    # Lógica para calcular o desconto e encontrar o ID do plano gratuito
    plano_mensal_base = next((p for p in planos if p.nome == 'Mensal'), None)
    plano_gratuito_id = next(
        (p.id for p in planos if p.nome == 'Teste Gratuito'), None)

    if plano_mensal_base:
        custo_anual_base = plano_mensal_base.preco * 12
        for plano in planos:
            if plano.nome == 'Anual':
                plano.economia = custo_anual_base - plano.preco
            else:
                plano.economia = 0

    return render_template('landing_page.html', planos=planos, plano_gratuito_id=plano_gratuito_id)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        # --- Coleta de dados do formulário ---
        nome_admin = request.form.get('name')
        email_admin = request.form.get('email')
        senha_admin = request.form.get('password')
        confirm_senha = request.form.get(
            'confirm_password')  # Pega a confirmação
        nome_escola = request.form.get('school_name')
        plano_id = request.form.get('plan_id')
        cep = request.form.get('cep')
        endereco = request.form.get('endereco')
        numero = request.form.get('numero')
        bairro = request.form.get('bairro')
        cidade = request.form.get('cidade')
        estado = request.form.get('estado')

        # --- Validação ---
        if not all([nome_admin, email_admin, senha_admin, confirm_senha, nome_escola, plano_id]):
            flash('Todos os campos são obrigatórios.', 'danger')
            return redirect(url_for('register'))

        # --- VALIDAÇÃO DE SENHA ---
        if senha_admin != confirm_senha:
            flash('As senhas não coincidem. Por favor, tente novamente.', 'danger')
            return redirect(url_for('register'))

        if Usuario.query.filter_by(email=email_admin).first():
            flash('Este e-mail já está em uso.', 'danger')
            return redirect(url_for('register'))

        plano = Plano.query.get(plano_id)
        if not plano:
            flash('Plano selecionado é inválido.', 'danger')
            return redirect(url_for('register'))

        try:
            nova_escola = Escola(
                nome=nome_escola,
                cep=cep,
                endereco=endereco,
                numero=numero,
                bairro=bairro,
                cidade=cidade,
                estado=estado
            )
            novo_admin = Usuario(
                nome=nome_admin, email=email_admin, email_confirmado=False)
            novo_admin.set_password(senha_admin)

            db.session.add(nova_escola)
            db.session.add(novo_admin)
            db.session.flush()

            associacao = UsuarioEscola(
                usuario_id=novo_admin.id, escola_id=nova_escola.id, papel='admin')
            db.session.add(associacao)

            data_inicio = date.today()
            data_fim = data_inicio + relativedelta(months=plano.duracao_meses)
            nova_assinatura = Assinatura(escola_id=nova_escola.id, plano_id=plano.id,
                                         data_inicio=data_inicio, data_fim=data_fim, status='ativa')
            db.session.add(nova_assinatura)

            send_confirmation_email(novo_admin)

            db.session.commit()

            return redirect(url_for('check_your_email'))

        except Exception as e:
            db.session.rollback()
            flash(
                f'Ocorreu um erro inesperado durante o cadastro: {e}', 'danger')
            return redirect(url_for('register'))

    # Lógica GET
    planos = Plano.query.order_by(Plano.preco).all()
    plano_selecionado_id = request.args.get('plan_id', type=int)

    plano_mensal_base = next((p for p in planos if p.nome == 'Mensal'), None)
    if plano_mensal_base:
        custo_anual_base = plano_mensal_base.preco * 12
        for plano in planos:
            if plano.nome == 'Anual':
                plano.economia = custo_anual_base - plano.preco
            else:
                plano.economia = 0

    return render_template('register.html', planos=planos, plano_selecionado_id=plano_selecionado_id)


@app.route('/check-email')
def check_your_email():
    """Exibe a página de aviso para o usuário checar o e-mail."""
    return render_template('check_your_email.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = Usuario.query.filter_by(email=email).first()

        if user and user.check_password(password):

            if not user.email_confirmado and not user.is_superadmin:
                flash(
                    'Sua conta ainda não foi confirmada. Por favor, verifique seu e-mail.', 'warning')
                return redirect(url_for('login'))

            # ***** INÍCIO DA ALTERAÇÃO *****
            # Pega o valor do checkbox 'remember'. Será 'on' se marcado, ou None se não.
            remember_me = True if request.form.get('remember') else False
            # Passa o valor para a função login_user
            login_user(user, remember=remember_me)
            # ***** FIM DA ALTERAÇÃO *****

            primeira_associacao = user.escolas.first()
            if primeira_associacao:
                session['escola_id'] = primeira_associacao.escola_id
            else:
                session['escola_id'] = None

            flash(f'Bem-vindo(a), {user.nome}!', 'success')
            return redirect(url_for('home'))
        else:
            flash('E-mail ou senha inválidos.', 'danger')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    # Limpa qualquer dado de perfil social da sessão
    if 'oauth_profile' in session:
        session.pop('oauth_profile')
    logout_user()
    flash('Você foi desconectado com sucesso.', 'info')
    return redirect(url_for('login'))

# --- ROTAS PRINCIPAIS ---


@app.route('/home')
@login_required
def home():
    """
    Redireciona o usuário para sua página inicial ("home") apropriada
    com base em seu papel. Esta rota é o destino principal após o login.
    """
    if current_user.is_superadmin:
        return redirect(url_for('superadmin_dashboard'))
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))

    # Se não for nenhum dos acima, é um professor. A "home" dele são as agendas.
    return redirect(url_for('listar_agendas'))


@app.route('/agendas')
@login_required
def listar_agendas():
    """
    Exibe a lista de recursos disponíveis (agendas) para a escola do usuário.
    Esta página é acessível por administradores e professores.
    """
    if current_user.is_superadmin:
        return redirect(url_for('superadmin_dashboard'))

    escola_id = session.get('escola_id')
    if not escola_id:
        flash("Você não está associado a nenhuma escola. Entre em contato com o administrador.", "warning")
        return redirect(url_for('logout'))

    resources = Resource.query.filter_by(escola_id=escola_id).order_by(
        Resource.sort_order, Resource.name).all()
    return render_template('index.html', resources=resources)


@app.route('/resource/<int:resource_id>')
@login_required
def select_shift(resource_id):
    """
    Carrega a página da agenda. A data mínima do calendário é calculada
    com base no papel do usuário (admin pode sempre, professor segue a regra).
    """
    escola_id = session.get('escola_id')
    resource = Resource.query.filter_by(
        id=resource_id, escola_id=escola_id).first_or_404()
    usuarios = Usuario.query.join(UsuarioEscola).filter(
        UsuarioEscola.escola_id == escola_id).order_by(Usuario.nome).all()

    today = date.today()
    primeira_data_permitida = today  # Padrão para admin

    # Aplica a regra de antecedência apenas se o usuário NÃO for admin
    if not current_user.is_admin:
        min_days_antecedencia = resource.min_agendamento_dias
        primeira_data_permitida = today + timedelta(days=min_days_antecedencia)

    date_str_url = request.args.get('date')
    data_selecionada = None
    if date_str_url:
        try:
            data_selecionada = datetime.strptime(
                date_str_url, '%Y-%m-%d').date()
        except ValueError:
            data_selecionada = None

    if data_selecionada and data_selecionada >= primeira_data_permitida:
        initial_date = data_selecionada
    else:
        initial_date = primeira_data_permitida

    weekday = initial_date.weekday()
    if weekday == 5:
        initial_date += timedelta(days=2)
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
    """Fecha um horário. Ação exclusiva de admin, sem restrição de data."""
    if not current_user.is_admin:
        return jsonify({'error': 'Acesso negado'}), 403

    escola_id = session.get('escola_id')
    resource_id = request.form.get('resource_id')
    date_str = request.form.get('date')
    shift = request.form.get('shift')
    slot_name = request.form.get('slot_name')

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
                usuario_id=current_user.id,
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
    """Agenda um horário. Aplica validação de data apenas para não-admins."""
    escola_id = session.get('escola_id')
    resource_id = request.form.get('resource_id')
    date_str = request.form.get('date')
    slot_name = request.form.get('slot_name')
    shift = request.form.get('shift')

    resource = Resource.query.filter_by(
        id=int(resource_id), escola_id=escola_id).first_or_404()
    booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()

    # Aplica a validação apenas se o usuário logado NÃO for um administrador
    if not current_user.is_admin:
        primeira_data_permitida = date.today() + timedelta(days=resource.min_agendamento_dias)
        if booking_date < primeira_data_permitida:
            flash(
                f'Este recurso só pode ser agendado com no mínimo {resource.min_agendamento_dias} dia(s) de antecedência.', 'danger')
            return redirect(url_for('select_shift', resource_id=resource_id))

    if Booking.query.filter_by(resource_id=resource_id, date=booking_date, slot_name=slot_name, shift=shift, escola_id=escola_id).first():
        flash('Este horário foi agendado por outra pessoa.', 'warning')
        return redirect(url_for('select_shift', resource_id=resource_id, date=date_str, shift=shift))

    book_for_teacher = current_user
    if current_user.is_admin:
        selected_teacher_id = request.form.get('teacher_id')
        if selected_teacher_id:
            book_for_teacher = Usuario.query.get(int(selected_teacher_id))

    new_booking = Booking(
        escola_id=escola_id,
        resource_id=int(resource_id),
        date=booking_date,
        slot_name=slot_name,
        shift=shift,
        usuario_id=book_for_teacher.id,
        teacher_name=book_for_teacher.nome_curto or book_for_teacher.nome
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


# Em app.py

@app.route('/admin')
@admin_required
def admin_dashboard():
    escola_id = session.get('escola_id')
    if not escola_id:
        flash("Sua sessão expirou ou não foi possível identificar a escola.", "warning")
        return redirect(url_for('login'))

    # --- CÁLCULO DOS KPIs (ESTATÍSTICAS) ---
    total_recursos = Resource.query.filter_by(escola_id=escola_id).count()
    total_usuarios = UsuarioEscola.query.filter_by(escola_id=escola_id).count()

    today = date.today()
    _, last_day_of_month = calendar.monthrange(today.year, today.month)
    start_of_month = today.replace(day=1)
    end_of_month = today.replace(day=last_day_of_month)

    total_agendamentos_mes = Booking.query.filter(
        Booking.escola_id == escola_id,
        Booking.date.between(start_of_month, end_of_month)
    ).count()

    # --- PREPARAÇÃO DOS DADOS PARA O GRÁFICO ---
    dados_grafico_query = db.session.query(
        Resource.name,
        func.count(Booking.id).label('total')
    ).join(Booking, Resource.id == Booking.resource_id).filter(
        Resource.escola_id == escola_id,
        Booking.date.between(start_of_month, end_of_month)
    ).group_by(Resource.name).order_by(
        func.count(Booking.id).desc()
    ).limit(5).all()

    chart_labels = json.dumps([item[0] for item in dados_grafico_query])
    chart_data = json.dumps([item[1] for item in dados_grafico_query])

    # A linha mais importante para a lista de gerenciamento:
    # Garante que a lista de recursos na parte de baixo do dashboard também seja filtrada.
    resources = Resource.query.filter_by(escola_id=escola_id).order_by(
        Resource.sort_order, Resource.name).all()

    return render_template('admin_dashboard.html',
                           resources=resources,
                           total_recursos=total_recursos,
                           total_usuarios=total_usuarios,
                           total_agendamentos_mes=total_agendamentos_mes,
                           chart_labels=chart_labels,
                           chart_data=chart_data)


@app.route('/admin/resource/add', methods=['POST'])
@admin_required
def add_resource():
    name = request.form.get('name')
    escola_id = session.get('escola_id')
    if not escola_id:
        flash('Erro: Não foi possível identificar a sua escola. Por favor, faça login novamente.', 'danger')
        return redirect(url_for('admin_dashboard'))
    if name:
        new_resource = Resource(
            name=name,
            description=request.form.get('description'),
            icon=request.form.get('icon') or 'bi-box',
            escola_id=escola_id,
            min_agendamento_dias=int(
                request.form.get('min_agendamento_dias', 0))
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
    resource = Resource.query.filter_by(
        id=resource_id, escola_id=escola_id).first_or_404()
    name = request.form.get('name')
    if name:
        resource.name = name
        resource.description = request.form.get('description')
        resource.icon = request.form.get('icon') or 'bi-box'
        resource.min_agendamento_dias = int(
            request.form.get('min_agendamento_dias', 0))
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
    escola_id = session.get('escola_id')
    if not escola_id:
        flash('Erro: Não foi possível identificar a sua escola.', 'danger')
        return redirect(url_for('admin_dashboard'))
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
        escola_id=escola_id,
        min_agendamento_dias=original_resource.min_agendamento_dias
    )
    db.session.add(new_resource)
    db.session.commit()
    for template in original_resource.schedule_templates:
        new_template = ScheduleTemplate(
            resource_id=new_resource.id, shift=template.shift, slots=template.slots)
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
@login_required
@admin_required
def manage_teachers():
    escola_id = session.get('escola_id')
    escola_atual = Escola.query.get_or_404(escola_id)

    if request.method == 'POST':
        # ... (a sua lógica de POST para adicionar/convidar um utilizador continua a mesma) ...
        nome = request.form.get('name')
        nome_curto = request.form.get('nome_curto')
        email = request.form.get('email')
        papel = 'admin' if 'is_admin' in request.form else 'professor'
        matricula = request.form.get('registration')

        if not all([nome, email]):
            flash('Nome e e-mail são obrigatórios.', 'danger')
            return redirect(url_for('manage_teachers'))

        disciplinas_selecionadas = request.form.getlist('disciplinas')
        disciplinas_do_usuario = []
        for item in disciplinas_selecionadas:
            if item.isdigit():
                disciplina = Disciplina.query.get(int(item))
                if disciplina and disciplina.escola_id == escola_id:
                    disciplinas_do_usuario.append(disciplina)
            elif item:
                nova_disciplina = Disciplina.query.filter_by(
                    nome=item, escola_id=escola_id).first()
                if not nova_disciplina:
                    nova_disciplina = Disciplina(
                        nome=item, escola_id=escola_id)
                    db.session.add(nova_disciplina)
                disciplinas_do_usuario.append(nova_disciplina)

        usuario_existente = Usuario.query.filter_by(email=email).first()

        if not usuario_existente:
            novo_usuario = Usuario(
                nome=nome, nome_curto=nome_curto, email=email)
            db.session.add(novo_usuario)
            db.session.flush()
            novo_usuario.disciplinas = disciplinas_do_usuario
            usuario_para_associar = novo_usuario
        else:
            usuario_para_associar = usuario_existente
            usuario_para_associar.nome = nome
            usuario_para_associar.nome_curto = nome_curto
            usuario_para_associar.disciplinas = disciplinas_do_usuario

        associacao_existente = UsuarioEscola.query.filter_by(
            usuario_id=usuario_para_associar.id, escola_id=escola_id).first()

        if not associacao_existente:
            nova_associacao = UsuarioEscola(
                usuario_id=usuario_para_associar.id, escola_id=escola_id, papel=papel, matricula=matricula)
            db.session.add(nova_associacao)

            if not usuario_para_associar.password_hash:
                send_invitation_email(usuario_para_associar, escola_atual)

            db.session.commit()
            flash(
                f'Utilizador "{usuario_para_associar.nome}" associado e/ou convidado com sucesso!', 'success')
        else:
            associacao_existente.papel = papel
            associacao_existente.matricula = matricula
            db.session.commit()
            flash('Dados do utilizador atualizados com sucesso nesta escola.', 'info')

        return redirect(url_for('manage_teachers'))

    # --- LÓGICA GET CORRIGIDA ---
    # Junta as tabelas e ordena pelo nome do utilizador
    membros = db.session.query(UsuarioEscola).join(Usuario).filter(
        UsuarioEscola.escola_id == escola_id).order_by(Usuario.nome).all()

    disciplinas_da_escola = Disciplina.query.filter_by(
        escola_id=escola_id).order_by(Disciplina.nome).all()
    return render_template('admin_teachers.html', membros=membros, disciplinas=disciplinas_da_escola)


@app.route('/admin/user/edit/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def edit_user(user_id):
    escola_id = session.get('escola_id')
    usuario = Usuario.query.get_or_404(user_id)

    new_email = request.form.get('email')
    existing_user = Usuario.query.filter(
        Usuario.id != user_id, Usuario.email == new_email).first()
    if existing_user:
        flash(
            f'O e-mail "{new_email}" já está em uso por outro utilizador.', 'danger')
        return redirect(url_for('manage_teachers'))

    usuario.nome = request.form.get('name')
    usuario.nome_curto = request.form.get('nome_curto')
    usuario.email = new_email

    associacao = UsuarioEscola.query.filter_by(
        usuario_id=user_id, escola_id=escola_id).first_or_404()
    associacao.papel = 'admin' if 'is_admin' in request.form else 'professor'
    associacao.matricula = request.form.get('registration')

    disciplinas_selecionadas = request.form.getlist('disciplinas')
    disciplinas_do_usuario = []
    for item in disciplinas_selecionadas:
        if item.isdigit():
            disciplina = Disciplina.query.get(int(item))
            if disciplina and disciplina.escola_id == escola_id:
                disciplinas_do_usuario.append(disciplina)
        elif item:
            nova_disciplina = Disciplina.query.filter_by(
                nome=item, escola_id=escola_id).first()
            if not nova_disciplina:
                nova_disciplina = Disciplina(nome=item, escola_id=escola_id)
                db.session.add(nova_disciplina)
            disciplinas_do_usuario.append(nova_disciplina)
    usuario.disciplinas = disciplinas_do_usuario

    db.session.commit()
    flash('Utilizador atualizado com sucesso!', 'success')
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
    escola_id = session.get('escola_id')
    today = date.today()

    # --- INÍCIO DA DEPURAÇÃO ---
    print("\n--- DEBUG: Rota /my-bookings ---")
    print(f"Data de hoje (today) no servidor: {today}")
    # --- FIM DA DEPURAÇÃO ---

    weekdays_pt = {
        0: "Segunda-feira", 1: "Terça-feira", 2: "Quarta-feira",
        3: "Quinta-feira", 4: "Sexta-feira", 5: "Sábado", 6: "Domingo"
    }

    bookings_query = db.session.query(Booking, Resource)\
        .join(Resource, Booking.resource_id == Resource.id)\
        .filter(Booking.usuario_id == current_user.id)\
        .filter(Booking.escola_id == escola_id)\
        .filter(Booking.date >= today)\
        .order_by(Booking.date, Booking.shift)\
        .all()

    # --- INÍCIO DA DEPURAÇÃO ---
    print(f"Agendamentos encontrados após o filtro: {len(bookings_query)}")
    for booking, resource in bookings_query:
        print(f" - Agendamento ID {booking.id} para a data {booking.date}")
    print("--- FIM DO DEBUG ---\n")
    # --- FIM DA DEPURAÇÃO ---

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
    super_admin_email = 'admin@agenda123.com'
    if not Usuario.query.filter_by(email=super_admin_email).first():
        print('Criando usuário Super Admin...')
        super_admin = Usuario(
            nome='Administrador Geral',
            email=super_admin_email,
            is_superadmin=True
        )
        # IMPORTANTE: Defina uma senha forte aqui!
        super_admin.set_password('admin@agenda123')
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


# Em app.py

@app.route('/superadmin/backup-restore')
@login_required
@superadmin_required
def backup_restore_page():
    """Renderiza a página de backup e restauração para o Super Admin."""
    return render_template('superadmin_backup_restore.html')


@app.route('/superadmin/backup')
@login_required
@superadmin_required
def backup_database():
    """Cria um backup do banco de dados completo e o oferece para download."""
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    try:
        if db_uri.startswith('postgresql'):
            filename = f'backup_postgres_{timestamp}.sql'
            filepath = os.path.join(BACKUP_FOLDER, filename)

            parsed_uri = urlparse(db_uri)
            db_name, user, password, host, port = parsed_uri.path.lstrip(
                '/'), parsed_uri.username, parsed_uri.password, parsed_uri.hostname, parsed_uri.port

            env = os.environ.copy()
            env['PGPASSWORD'] = password

            command = [
                'pg_dump', '--host', host, '--port', str(
                    port), '--username', user,
                '--dbname', db_name, '--no-password', '--format=c', '--blobs',
                '--no-owner', '--file', filepath
            ]

            subprocess.run(command, check=True, env=env)
            flash('Backup completo do PostgreSQL gerado com sucesso!', 'success')

        elif db_uri.startswith('sqlite'):
            filename = f'backup_sqlite_{timestamp}.db'
            filepath = os.path.join(BACKUP_FOLDER, filename)
            db_path = db_uri.split('///')[1]
            shutil.copy2(db_path, filepath)
            flash('Backup completo do SQLite gerado com sucesso!', 'success')

        else:
            flash('Tipo de banco de dados não suportado para backup.', 'danger')
            return redirect(url_for('backup_restore_page'))

        return send_from_directory(BACKUP_FOLDER, filename, as_attachment=True)

    except Exception as e:
        flash(f'Erro ao gerar o backup: {str(e)}', 'danger')
        return redirect(url_for('backup_restore_page'))


@app.route('/superadmin/restore', methods=['POST'])
@login_required
@superadmin_required
def restore_database():
    """Salva o arquivo e agenda a restauração completa em segundo plano."""
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
        restore_task_bg.delay(filepath, db_uri_str)

        flash('Restauração do banco de dados iniciada em segundo plano! O processo pode levar alguns minutos e irá desconectar todos os usuários.', 'success')

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


# Em app.py

@app.cli.command("seed-plans")
def seed_plans_command():
    """Cria os planos de assinatura padrão se eles não existirem."""

    # --- NOVO PLANO DE TESTE GRATUITO ---
    plano_teste = Plano.query.filter_by(nome='Teste Gratuito').first()
    if not plano_teste:
        # Preço 0, duração de 1 mês, sem ID do Stripe
        plano_teste = Plano(nome='Teste Gratuito', preco=0,
                            duracao_meses=1, stripe_price_id=None)
        db.session.add(plano_teste)
        print("Plano 'Teste Gratuito' criado.")
    else:
        # Garante que o preço e a duração estão corretos
        plano_teste.preco = 0
        plano_teste.duracao_meses = 1
        print("Plano 'Teste Gratuito' já existe.")

    # --- PLANOS PAGOS ---
    plano_mensal = Plano.query.filter_by(nome='Mensal').first()
    if not plano_mensal:
        plano_mensal = Plano(nome='Mensal', preco=2000, duracao_meses=1,
                             stripe_price_id='SEU_ID_DE_PRECO_MENSAL_AQUI')
        db.session.add(plano_mensal)
        print("Plano 'Mensal' criado.")
    else:
        print("Plano 'Mensal' já existe.")

    plano_anual = Plano.query.filter_by(nome='Anual').first()
    if not plano_anual:
        plano_anual = Plano(nome='Anual', preco=20000, duracao_meses=12,
                            stripe_price_id='SEU_ID_DE_PRECO_ANUAL_AQUI')
        db.session.add(plano_anual)
        print("Plano 'Anual' criado.")
    else:
        print("Plano 'Anual' já existe.")

    db.session.commit()
    print("Planos semeados com sucesso!")


@app.route('/admin/upgrade-plan')
@login_required
@admin_required
def upgrade_plan():
    # --- CORREÇÃO AQUI ---
    # Busca apenas os planos que têm um preço maior que zero (planos pagos)
    planos = Plano.query.filter(Plano.preco > 0).order_by(Plano.preco).all()

    # Lógica para calcular a economia (reaproveitada da rota register)
    plano_mensal_base = Plano.query.filter_by(nome='Mensal').first()
    if plano_mensal_base:
        custo_anual_base = plano_mensal_base.preco * 12
        for plano in planos:
            if plano.nome == 'Anual':
                plano.economia = custo_anual_base - plano.preco
            else:
                plano.economia = 0

    return render_template('upgrade_plan.html', planos=planos)


def send_confirmation_email(user):
    """Gera o token e envia o e-mail de confirmação."""
    try:
        token = serializer.dumps(user.email, salt='email-confirm-salt')
        confirm_url = url_for('confirm_email', token=token, _external=True)
        logo_url = url_for(
            'static', filename='logo_agenda.png', _external=True)

        html_body = render_template('email/confirmation_email.html',
                                    user=user,
                                    confirm_url=confirm_url,
                                    logo_url=logo_url)

        msg = Message('Confirme seu Cadastro - Agenda Escolar',
                      recipients=[user.email],
                      html=html_body)
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Erro ao enviar e-mail de confirmação: {e}")
        return False


@app.route('/confirm/<token>')
def confirm_email(token):
    try:
        # Token válido por 1 hora
        email = serializer.loads(
            token, salt='email-confirm-salt', max_age=3600)
    except Exception:
        flash('O link de confirmação é inválido ou expirou.', 'danger')
        return redirect(url_for('login'))

    user = Usuario.query.filter_by(email=email).first_or_404()

    if user.email_confirmado:
        flash('Esta conta já foi confirmada. Por favor, faça login.', 'info')
    else:
        user.email_confirmado = True
        db.session.commit()
        flash(
            'Sua conta foi confirmada com sucesso! Agora você pode fazer login.', 'success')

    return redirect(url_for('login'))


def send_invitation_email(user, escola):
    """Gera um token e envia o e-mail de convite para um novo usuário."""
    try:
        token = serializer.dumps(user.email, salt='user-invitation-salt')
        accept_url = url_for('accept_invitation', token=token, _external=True)
        # Lembre-se de usar o link público para testes
        logo_url = 'URL_PUBLICO_DA_SUA_LOGO'

        html_body = render_template('email/invitation_email.html',
                                    user=user,
                                    escola=escola,
                                    accept_url=accept_url,
                                    logo_url=logo_url)

        msg = Message(f'Você foi convidado para a Agenda Escolar da {escola.nome}',
                      recipients=[user.email],
                      html=html_body)
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Erro ao enviar e-mail de convite: {e}")
        return False


@app.route('/accept-invitation/<token>', methods=['GET', 'POST'])
def accept_invitation(token):
    try:
        # Token válido por 7 dias
        email = serializer.loads(
            token, salt='user-invitation-salt', max_age=604800)
    except Exception:
        flash('O link de convite é inválido ou expirou.', 'danger')
        return redirect(url_for('login'))

    user = Usuario.query.filter_by(email=email).first_or_404()

    if user.password_hash:
        flash('Este convite já foi aceito. Por favor, faça login.', 'info')
        return redirect(url_for('login'))

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if new_password != confirm_password:
            flash('As senhas não coincidem.', 'danger')
            return render_template('accept_invitation.html', token=token, user=user)

        user.set_password(new_password)
        user.email_confirmado = True  # O convite também confirma o e-mail
        db.session.commit()

        flash('Sua conta foi ativada com sucesso! Você já pode fazer o login.', 'success')
        return redirect(url_for('login'))

    return render_template('accept_invitation.html', token=token, user=user)


@app.route('/admin/subscription')
@admin_required
def subscription_page():
    escola_id = session.get('escola_id')

    # Busca a assinatura mais recente da escola
    assinatura = Assinatura.query.filter_by(
        escola_id=escola_id).order_by(Assinatura.data_fim.desc()).first()

    dias_restantes = None
    if assinatura:
        # Calcula a diferença de dias entre a data final e hoje
        dias_restantes = (assinatura.data_fim - date.today()).days

    return render_template('admin_subscription.html', assinatura=assinatura, dias_restantes=dias_restantes)


@app.route('/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    escola_id = session.get('escola_id')
    escola = Escola.query.get_or_404(escola_id)

    # Busca a assinatura atual para saber qual plano renovar
    assinatura = Assinatura.query.filter_by(
        escola_id=escola_id).order_by(Assinatura.data_fim.desc()).first()
    if not assinatura:
        flash("Nenhuma assinatura encontrada para renovar.", "danger")
        return redirect(url_for('subscription_page'))

    try:
        # Você precisará criar um ID de preço no painel do Stripe (ver abaixo)
        price_id = request.form.get('price_id')

        checkout_session = stripe.checkout.Session.create(
            line_items=[
                {
                    'price': price_id,
                    'quantity': 1,
                },
            ],
            mode='subscription',
            success_url=url_for('payment_success', _external=True) +
            '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('payment_cancel', _external=True),
            # Passa metadados para sabermos qual escola e assinatura atualizar depois
            subscription_data={
                "metadata": {
                    "escola_id": escola.id,
                    "assinatura_id": assinatura.id
                }
            }
        )
    except Exception as e:
        flash(f"Erro ao comunicar com o sistema de pagamento: {e}", "danger")
        return redirect(url_for('subscription_page'))

    return redirect(checkout_session.url, code=303)


@app.route('/payment-success')
@login_required
def payment_success():
    flash("Pagamento realizado com sucesso! Sua assinatura foi atualizada.", "success")
    # No futuro, aqui verificaremos a sessão e atualizaremos o banco de dados via webhook
    return redirect(url_for('subscription_page'))


@app.route('/payment-cancel')
@login_required
def payment_cancel():
    flash("O pagamento foi cancelado. Você pode tentar novamente a qualquer momento.", "warning")
    return redirect(url_for('subscription_page'))


@app.route('/stripe-webhook', methods=['POST'])
def stripe_webhook():
    endpoint_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    event = None

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as e:
        return 'Invalid payload', 400
    except stripe.SignatureVerificationError as e:
        return 'Invalid signature', 400

    if event['type'] == 'checkout.session.completed':
        checkout_session = event['data']['object']

        if checkout_session.mode == 'subscription':
            subscription_id = checkout_session.get('subscription')
            try:
                subscription_object = stripe.Subscription.retrieve(
                    subscription_id)
                metadata = subscription_object.metadata
                escola_id = metadata.get('escola_id')
                assinatura_id = metadata.get('assinatura_id')

                if escola_id and assinatura_id:
                    assinatura = Assinatura.query.get(assinatura_id)

                    # --- CORREÇÃO FINAL AQUI ---
                    # Acessando os dados como um dicionário para mais segurança
                    price_id_pago = subscription_object['items']['data'][0]['price']['id']
                    plano_pago = Plano.query.filter_by(
                        stripe_price_id=price_id_pago).first()

                    if assinatura and plano_pago:
                        data_base = max(date.today(), assinatura.data_fim)
                        nova_data_fim = data_base + \
                            relativedelta(months=plano_pago.duracao_meses)

                        assinatura.plano_id = plano_pago.id
                        assinatura.data_fim = nova_data_fim
                        assinatura.status = 'ativa'
                        db.session.commit()

            except Exception as e:
                print(f"ERRO ao processar a assinatura no webhook: {e}")

    return jsonify(success=True)


@app.route('/superadmin')
@login_required
@superadmin_required
def superadmin_dashboard():
    # --- 1. BUSCA DE CONFIGURAÇÕES DO AMBIENTE ---
    config_info = {
        'stripe_public_key': os.environ.get('STRIPE_PUBLIC_KEY', 'Não configurada'),
        'mail_server': os.environ.get('MAIL_SERVER', 'Não configurado'),
        'mail_sender': os.environ.get('MAIL_DEFAULT_SENDER', 'Não configurado')
    }

    # --- 2. CÁLCULO DOS KPIs GLOBAIS ---
    total_escolas = Escola.query.count()
    total_usuarios = db.session.query(func.count(
        distinct(UsuarioEscola.usuario_id))).scalar()

    today = date.today()
    _, last_day_of_month = calendar.monthrange(today.year, today.month)
    start_of_month = today.replace(day=1)
    end_of_month = today.replace(day=last_day_of_month)
    total_agendamentos_mes = Booking.query.filter(
        Booking.date.between(start_of_month, end_of_month)).count()

    # --- 3. DADOS PARA O GRÁFICO DE PLANOS ---
    dados_grafico_planos = db.session.query(
        Plano.nome,
        func.count(Assinatura.id)
    ).join(Assinatura).group_by(Plano.nome).all()

    chart_planos_labels = json.dumps(
        [item[0] for item in dados_grafico_planos])
    chart_planos_data = json.dumps([item[1] for item in dados_grafico_planos])

    # --- 4. DADOS DETALHADOS PARA A TABELA DE ESCOLAS ---
    escolas = db.session.query(Escola).options(
        db.joinedload(Escola.assinaturas).subqueryload(Assinatura.plano)
    ).order_by(Escola.nome).all()

    dados_escolas = []
    for escola in escolas:
        assinatura_recente = max(
            escola.assinaturas, key=lambda a: a.data_fim, default=None)

        vencimento_info = {'classe': 'text-slate-500', 'texto': 'N/A'}
        if assinatura_recente:
            dias_restantes = (assinatura_recente.data_fim - today).days
            vencimento_info['texto'] = assinatura_recente.data_fim.strftime(
                '%d/%m/%Y')
            if dias_restantes < 0:
                vencimento_info['classe'] = 'vencido'
            elif dias_restantes <= 15:
                vencimento_info['classe'] = 'alerta'

        dados_escolas.append({
            'escola': escola,
            'assinatura': assinatura_recente,
            'contagem_usuarios': UsuarioEscola.query.filter_by(escola_id=escola.id).count(),
            'contagem_recursos': Resource.query.filter_by(escola_id=escola.id).count(),
            'vencimento_info': vencimento_info
        })

    return render_template('superadmin_dashboard.html',
                           config_info=config_info,
                           total_escolas=total_escolas,
                           total_usuarios=total_usuarios,
                           total_agendamentos_mes=total_agendamentos_mes,
                           chart_planos_labels=chart_planos_labels,
                           chart_planos_data=chart_planos_data,
                           dados_escolas=dados_escolas)


@app.route('/superadmin/school/edit/<int:escola_id>', methods=['POST'])
@login_required
@superadmin_required
def edit_school(escola_id):
    # Busca a escola no banco de dados
    escola = Escola.query.get_or_404(escola_id)

    # Pega os novos dados do formulário
    novo_nome = request.form.get('name')
    novo_status = request.form.get('status')

    if novo_nome and novo_status:
        escola.nome = novo_nome
        escola.status = novo_status
        db.session.commit()
        flash(
            f'Os dados da escola "{escola.nome}" foram atualizados com sucesso!', 'success')
    else:
        flash('Ocorreu um erro ao tentar atualizar os dados.', 'danger')

    return redirect(url_for('superadmin_dashboard'))


@app.route('/superadmin/plans', methods=['GET', 'POST'])
@login_required
@superadmin_required
def manage_plans():
    if request.method == 'POST':
        # --- Lógica para ADICIONAR um novo plano ---
        nome = request.form.get('nome')
        preco_str = request.form.get('preco')
        duracao = request.form.get('duracao_meses')
        stripe_id = request.form.get('stripe_price_id')

        # Validação
        if not all([nome, preco_str, duracao, stripe_id]):
            flash('Todos os campos são obrigatórios.', 'danger')
        else:
            try:
                # Converte o preço de R$ (ex: 99,90) para centavos (9990)
                preco_em_centavos = int(
                    float(preco_str.replace(',', '.')) * 100)

                novo_plano = Plano(
                    nome=nome,
                    preco=preco_em_centavos,
                    duracao_meses=int(duracao),
                    stripe_price_id=stripe_id
                )
                db.session.add(novo_plano)
                db.session.commit()
                flash('Novo plano adicionado com sucesso!', 'success')
            except ValueError:
                flash(
                    'O valor do preço é inválido. Use um formato como 99,90.', 'danger')
            except Exception as e:
                db.session.rollback()
                flash(f'Ocorreu um erro: {e}', 'danger')

        return redirect(url_for('manage_plans'))

    # --- Lógica para EXIBIR a página (GET) ---
    planos = Plano.query.order_by(Plano.preco).all()
    return render_template('superadmin_plans.html', planos=planos)


@app.route('/superadmin/plans/edit/<int:plan_id>', methods=['POST'])
@login_required
@superadmin_required
def edit_plan(plan_id):
    plano = Plano.query.get_or_404(plan_id)

    nome = request.form.get('nome')
    preco_str = request.form.get('preco')
    duracao = request.form.get('duracao_meses')
    stripe_id = request.form.get('stripe_price_id')

    if not all([nome, preco_str, duracao, stripe_id]):
        flash('Todos os campos são obrigatórios.', 'danger')
    else:
        try:
            plano.nome = nome
            plano.preco = int(float(preco_str.replace(',', '.')) * 100)
            plano.duracao_meses = int(duracao)
            plano.stripe_price_id = stripe_id
            db.session.commit()
            flash('Plano atualizado com sucesso!', 'success')
        except ValueError:
            flash('O valor do preço é inválido. Use um formato como 99,90.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro ao atualizar o plano: {e}', 'danger')

    return redirect(url_for('manage_plans'))


@app.route('/superadmin/plans/delete/<int:plan_id>')
@login_required
@superadmin_required
def delete_plan(plan_id):
    plano = Plano.query.get_or_404(plan_id)

    # Lógica de segurança: Verifica se alguma assinatura está usando este plano
    assinaturas_ativas = Assinatura.query.filter_by(plano_id=plan_id).first()
    if assinaturas_ativas:
        flash(
            f'Não é possível excluir o plano "{plano.nome}", pois ele está em uso por uma ou mais escolas.', 'danger')
        return redirect(url_for('manage_plans'))

    try:
        db.session.delete(plano)
        db.session.commit()
        flash(f'Plano "{plano.nome}" excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ocorreu um erro ao excluir o plano: {e}', 'danger')

    return redirect(url_for('manage_plans'))


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        # ... (lógica de upload, mudança de senha) ...

        if 'update_profile' in request.form:
            current_user.nome = request.form.get('nome')
            current_user.nome_curto = request.form.get('nome_curto')

            escola_id = session.get('escola_id')
            if escola_id and not current_user.is_superadmin:
                disciplinas_selecionadas = request.form.getlist('disciplinas')
                disciplinas_do_usuario = []
                for item in disciplinas_selecionadas:
                    if item.isdigit():
                        disciplina = Disciplina.query.get(int(item))
                        if disciplina and disciplina.escola_id == escola_id:
                            disciplinas_do_usuario.append(disciplina)
                    else:
                        nova_disciplina = Disciplina.query.filter_by(
                            nome=item, escola_id=escola_id).first()
                        if not nova_disciplina:
                            nova_disciplina = Disciplina(
                                nome=item, escola_id=escola_id)
                            db.session.add(nova_disciplina)
                        disciplinas_do_usuario.append(nova_disciplina)
                current_user.disciplinas = disciplinas_do_usuario

            db.session.commit()

            novo_nome_exibicao = current_user.nome_curto or current_user.nome
            Booking.query.filter_by(usuario_id=current_user.id).update(
                {'teacher_name': novo_nome_exibicao})
            db.session.commit()

            flash('O seu perfil foi atualizado com sucesso!', 'success')
            return redirect(url_for('profile'))

    escola_id = session.get('escola_id')
    disciplinas_da_escola = []
    if escola_id:
        disciplinas_da_escola = Disciplina.query.filter_by(
            escola_id=escola_id).order_by(Disciplina.nome).all()

    return render_template('profile.html', disciplinas=disciplinas_da_escola)


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """Serve os arquivos que foram enviados."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/login/google/callback')
def google_callback():
    try:
        token = oauth.google.authorize_access_token()
        user_info = token.get('userinfo')
        email = user_info['email']
    except Exception as e:
        flash(
            f"Ocorreu um erro ao tentar fazer login com o Google: {e}", "danger")
        return redirect(url_for('login'))

    user = Usuario.query.filter_by(email=email).first()

    if user:
        # Se o utilizador existe, faz o login
        login_user(user)
        # Atualiza a foto de perfil se não for uma foto personalizada
        if not user.foto_perfil or 'googleusercontent.com' in user.foto_perfil:
            user.foto_perfil = user_info.get('picture')
            db.session.commit()

        primeira_associacao = user.escolas.first()
        if primeira_associacao:
            session['escola_id'] = primeira_associacao.escola_id

        flash(f'Bem-vindo(a) de volta, {user.nome}!', 'success')
        return redirect(url_for('home'))
    else:
        # Se o utilizador não existe, mostra um erro claro
        flash('Login com Google falhou. O e-mail não está cadastrado no sistema. Se você é administrador, crie uma conta. Se é professor, peça um convite ao seu administrador.', 'danger')
        return redirect(url_for('login'))


@app.route('/login/google')
def login_google():
    # Redireciona o usuário para a página de autorização do Google
    redirect_uri = url_for('google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_settings():
    escola_id = session.get('escola_id')
    escola = Escola.query.get_or_404(escola_id)

    if request.method == 'POST':
        # Atualiza os dados da escola
        escola.nome = request.form.get('nome_escola')
        escola.nome_diretor = request.form.get('nome_diretor')
        escola.email_contato = request.form.get('email_contato')
        escola.telefone_fixo = request.form.get('telefone_fixo')
        escola.telefone_celular = request.form.get('telefone_celular')
        # --- ATUALIZAÇÃO DOS CAMPOS DE ENDEREÇO ---
        escola.cep = request.form.get('cep')
        escola.endereco = request.form.get('endereco')
        escola.numero = request.form.get('numero')
        escola.bairro = request.form.get('bairro')
        escola.cidade = request.form.get('cidade')
        escola.estado = request.form.get('estado')

        # Lógica para o upload da logo
        if 'logo_escola' in request.files:
            file = request.files['logo_escola']
            if file.filename != '':
                try:
                    filename = secure_filename(
                        f"escola_{escola_id}_{file.filename}")
                    filepath = os.path.join(
                        app.config['UPLOAD_FOLDER'], filename)

                    output_size = (200, 200)
                    img = Image.open(file)
                    img.thumbnail(output_size)
                    img.save(filepath)

                    escola.logo_url = filename
                except Exception as e:
                    flash(f'Ocorreu um erro ao enviar a logo: {e}', 'danger')

        db.session.commit()
        flash('Configurações da escola salvas com sucesso!', 'success')
        return redirect(url_for('admin_settings'))

    return render_template('admin_settings.html', escola=escola)


@app.route('/login/microsoft')
def login_microsoft():
    redirect_uri = url_for('microsoft_callback', _external=True)
    return oauth.microsoft.authorize_redirect(redirect_uri)


@app.route('/login/microsoft/callback')
def microsoft_callback():
    try:
        token = oauth.microsoft.authorize_access_token()
        resp = oauth.microsoft.get('me')
        resp.raise_for_status()
        user_info = resp.json()
        email = user_info.get('mail') or user_info.get('userPrincipalName')
        nome = user_info.get('displayName')

        if not email:
            flash("Não foi possível obter o seu e-mail da Microsoft.", "danger")
            return redirect(url_for('login'))
    except Exception as e:
        flash(
            f"Ocorreu um erro ao tentar fazer login com a Microsoft: {e}", "danger")
        return redirect(url_for('login'))

    user = Usuario.query.filter_by(email=email).first()

    if user:
        # Se o utilizador existe, faz o login
        login_user(user)
        primeira_associacao = user.escolas.first()
        if primeira_associacao:
            session['escola_id'] = primeira_associacao.escola_id

        flash(f'Bem-vindo(a) de volta, {user.nome}!', 'success')
        return redirect(url_for('home'))
    else:
        # Se o utilizador não existe, mostra um erro claro
        flash('Login com Microsoft falhou. O e-mail não está cadastrado no sistema. Se você é administrador, crie uma conta. Se é professor, peça um convite ao seu administrador.', 'danger')
        return redirect(url_for('login'))


@app.route('/admin/export', methods=['GET'])
@login_required
@admin_required
def admin_export_page():
    """Exibe a página de exportação de dados para o admin da escola."""
    escola_id = session.get('escola_id')
    # Busca os recursos da escola para popular o filtro
    resources = Resource.query.filter_by(
        escola_id=escola_id).order_by(Resource.name).all()
    return render_template('admin_export.html', resources=resources)


@app.route('/admin/export/bookings', methods=['POST'])
@login_required
@admin_required
def export_bookings_csv():
    """Gera e retorna um arquivo CSV com os agendamentos filtrados."""
    escola_id = session.get('escola_id')

    try:
        resource_id_str = request.form.get('resource_id')
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')

        start_date = datetime.strptime(start_date_str, '%d/%m/%Y').date()
        end_date = datetime.strptime(end_date_str, '%d/%m/%Y').date()

        # A consulta base busca todos os agendamentos no período
        query = db.session.query(Booking, Usuario, Resource).join(Usuario).join(Resource).filter(
            Booking.escola_id == escola_id,
            Booking.date.between(start_date, end_date)
        )

        # Se um recurso específico foi selecionado, adiciona o filtro
        if resource_id_str and resource_id_str.isdigit():
            resource_id = int(resource_id_str)
            query = query.filter(Booking.resource_id == resource_id)

        report_data = query.order_by(
            Booking.date, Booking.shift, Booking.slot_name).all()

        # Geração do CSV em memória
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(['Data', 'Recurso', 'Turno', 'Horário',
                        'Professor', 'Nome Curto', 'Status'])

        for booking, usuario, resource in report_data:
            writer.writerow([
                booking.date.strftime('%d/%m/%Y'),
                resource.name,
                booking.shift.capitalize(),
                booking.slot_name,
                booking.teacher_name,
                usuario.nome_curto or '',
                booking.status.capitalize()
            ])

        output.seek(0)

        filename = f"relatorio_agendamentos_{start_date_str.replace('/', '-')}_{end_date_str.replace('/', '-')}.csv"

        return Response(
            output,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment;filename={filename}"}
        )

    except (ValueError, TypeError):
        flash(
            'Filtros inválidos para exportação. Verifique o recurso e as datas.', 'danger')
        return redirect(url_for('admin_export_page'))


if __name__ == '__main__':
    app.run()
