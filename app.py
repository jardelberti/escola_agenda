import os
import json
import subprocess
import shutil
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, date
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from functools import wraps
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from sqlalchemy import func
from models import db, Teacher, Resource, ScheduleTemplate, Booking
from flask_migrate import Migrate
from celery import Celery 
from logging import getLogger

# --- CONFIGURAÇÃO DA APLICAÇÃO ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'uma-chave-secreta-muito-dificil-de-adivinhar'

# --- CONFIGURAÇÃO DO BANCO DE DADOS (FLEXÍVEL PARA AWS E LOCAL) ---
# Cria o diretório de dados se ele não existir
DATA_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

database_uri = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(DATA_DIR, 'agenda.db'))
if database_uri.startswith("postgres://"):
    database_uri = database_uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- NOVA CONFIGURAÇÃO DA PASTA DE BACKUP ---
BACKUP_FOLDER = os.path.join(DATA_DIR, 'backups')
os.makedirs(BACKUP_FOLDER, exist_ok=True) # Garante que a pasta exista

app.config['CELERY_BROKER_URL'] = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
app.config['CELERY_RESULT_BACKEND'] = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')

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

# --- INICIALIZAÇÃO DAS EXTENSÕES ---
db.init_app(app)
migrate = Migrate(app, db)
login_manager = LoginManager()
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
        db_name, user, password, host, port = parsed_uri.path.lstrip('/'), parsed_uri.username, parsed_uri.password, parsed_uri.hostname, parsed_uri.port
        
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
    return Teacher.query.get(int(user_id))

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

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        registration = request.form.get('registration')
        teacher = Teacher.query.filter_by(registration=registration).first()

        if teacher:
            login_user(teacher)
            flash(f'Bem-vindo(a), {teacher.name}!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Matrícula inválida.', 'danger')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você foi desconectado com sucesso.', 'info')
    return redirect(url_for('login'))

# --- ROTAS PRINCIPAIS ---

@app.route('/home')
@login_required
def home():
    resources = Resource.query.order_by(Resource.sort_order, Resource.name).all()
    return render_template('index.html', resources=resources)

@app.route('/resource/<int:resource_id>')
@login_required
def select_shift(resource_id):
    """Esta rota agora carrega a nova página de agenda dinâmica."""
    resource = Resource.query.get_or_404(resource_id)
    teachers = Teacher.query.order_by(Teacher.name).all()
    
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
        
    # O JavaScript dará prioridade ao parâmetro 'date' da URL,
    # então esta lógica só se aplica no primeiro acesso.
    return render_template('agenda.html', resource=resource, teachers=teachers, current_date=initial_date)

@app.route('/api/agenda/<int:resource_id>/<string:date_str>')
@login_required
def get_agenda_data(resource_id, date_str):
    """(VERSÃO CORRIGIDA E ROBUSTA) Retorna os dados da agenda em formato JSON."""
    try:
        current_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Formato de data inválido'}), 400

    templates = ScheduleTemplate.query.filter_by(resource_id=resource_id).all()
    bookings = Booking.query.filter_by(resource_id=resource_id, date=current_date).all()
    
    booked_slots = { (b.shift, b.slot_name): b for b in bookings }
    
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
                'is_mine': booking.teacher_id == current_user.id if booking else False,
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

    resource_id = request.form.get('resource_id')
    date_str = request.form.get('date')
    shift = request.form.get('shift') # Captura o turno do formulário
    slot_name = request.form.get('slot_name')

    try:
        booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        if Booking.query.filter_by(resource_id=resource_id, date=booking_date, slot_name=slot_name, shift=shift).first():
            flash('Este horário já foi agendado ou fechado.', 'warning')
        else:
            new_booking = Booking(
                resource_id=int(resource_id),
                date=booking_date,
                slot_name=slot_name,
                shift=shift,
                teacher_id=current_user.id,
                teacher_name="Fechado",
                status='closed'
            )
            db.session.add(new_booking)
            db.session.commit()
            flash('Horário marcado como fechado com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ocorreu um erro ao tentar fechar o horário: {e}', 'danger')

    # Redireciona com 'date' e o 'shift'
    return redirect(url_for('select_shift', resource_id=resource_id, date=date_str, shift=shift))

@app.route('/agenda/book', methods=['POST'])
@login_required
def book_slot():
    resource_id = request.form.get('resource_id')
    date_str = request.form.get('date')
    slot_name = request.form.get('slot_name')
    shift = request.form.get('shift') # Captura o turno do formulário

    if Booking.query.filter_by(resource_id=resource_id, date=datetime.strptime(date_str, '%Y-%m-%d').date(), slot_name=slot_name, shift=shift).first():
        flash('Este horário foi agendado por outra pessoa.', 'warning')
        # Redireciona com 'date' e o 'shift'
        return redirect(url_for('select_shift', resource_id=resource_id, date=date_str, shift=shift))

    book_for_teacher = current_user
    if current_user.is_admin:
        selected_teacher_id = request.form.get('teacher_id')
        if selected_teacher_id:
            book_for_teacher = Teacher.query.get(int(selected_teacher_id))

    new_booking = Booking(
        resource_id=int(resource_id),
        date=datetime.strptime(date_str, '%Y-%m-%d').date(),
        slot_name=slot_name,
        shift=shift,
        teacher_id=book_for_teacher.id,
        teacher_name=book_for_teacher.name
    )
    db.session.add(new_booking)
    db.session.commit()
    flash('Horário agendado com sucesso!', 'success')
    # Redireciona com 'date' e o 'shift'
    return redirect(url_for('select_shift', resource_id=resource_id, date=date_str, shift=shift))

@app.route('/agenda/booking/delete/<int:booking_id>')
@login_required
def delete_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    resource_id = booking.resource_id
    date_str = request.args.get('date') 
    shift = request.args.get('shift') # Captura o turno da URL

    if current_user.is_admin or booking.teacher_id == current_user.id:
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
    resources = Resource.query.order_by(Resource.sort_order, Resource.name).all()
    return render_template('admin_dashboard.html', resources=resources)

@app.route('/admin/resources/reorder', methods=['POST'])
@admin_required
def reorder_resources():
    ordered_ids = request.form.get('order', '').split(',')
    if ordered_ids and ordered_ids[0] != '':
        for index, resource_id_str in enumerate(ordered_ids):
            resource = Resource.query.get(int(resource_id_str))
            if resource:
                resource.sort_order = index
        db.session.commit()
        flash('A ordem dos recursos foi salva com sucesso!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/resource/add', methods=['POST'])
@admin_required
def add_resource():
    name = request.form.get('name')
    if name:
        new_resource = Resource(name=name, description=request.form.get('description'), icon=request.form.get('icon') or 'bi-box')
        db.session.add(new_resource)
        db.session.commit()
        flash('Recurso adicionado com sucesso!', 'success')
    else:
        flash('O nome do recurso é obrigatório.', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/resource/edit/<int:resource_id>', methods=['POST'])
@admin_required
def edit_resource(resource_id):
    resource = Resource.query.get_or_404(resource_id)
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
    Booking.query.filter_by(resource_id=resource_id).delete()
    ScheduleTemplate.query.filter_by(resource_id=resource_id).delete()
    resource = Resource.query.get_or_404(resource_id)
    db.session.delete(resource)
    db.session.commit()
    flash('Recurso e todos os seus dados foram removidos com sucesso!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/resource/copy/<int:original_id>', methods=['POST'])
@admin_required
def copy_resource(original_id):
    original_resource = Resource.query.get_or_404(original_id)
    new_name = request.form.get('new_name')
    new_icon = request.form.get('new_icon') or 'bi-box'

    if not new_name:
        flash('O novo nome do recurso é obrigatório.', 'danger')
        return redirect(url_for('admin_dashboard'))

    new_resource = Resource(
        name=new_name,
        description=original_resource.description,
        icon=new_icon,
        sort_order=original_resource.sort_order + 1
    )
    db.session.add(new_resource)
    db.session.commit()

    for template in original_resource.schedule_templates:
        new_template = ScheduleTemplate(
            resource_id=new_resource.id,
            shift=template.shift,
            slots=template.slots
        )
        db.session.add(new_template)

    db.session.commit()
    flash(f'Recurso "{original_resource.name}" copiado com sucesso para "{new_name}"!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/schedules/<int:resource_id>', methods=['GET', 'POST'])
@admin_required
def manage_schedules(resource_id):
    resource = Resource.query.get_or_404(resource_id)
    if request.method == 'POST':
        shift = request.form.get('shift')
        slot_names = request.form.getlist('slot_name')
        slot_types = request.form.getlist('slot_type')
        slots_data = [{"name": name, "type": type} for name, type in zip(slot_names, slot_types) if name]
        schedule = ScheduleTemplate.query.filter_by(shift=shift, resource_id=resource_id).first()
        if schedule:
            schedule.slots = slots_data
        else:
            schedule = ScheduleTemplate(shift=shift, slots=slots_data, resource_id=resource_id)
            db.session.add(schedule)
        db.session.commit()
        flash(f'Horários do turno {shift} para {resource.name} salvos com sucesso!', 'success')
        return redirect(url_for('manage_schedules', resource_id=resource_id))
    matutino_schedule = ScheduleTemplate.query.filter_by(shift='matutino', resource_id=resource_id).first()
    vespertino_schedule = ScheduleTemplate.query.filter_by(shift='vespertino', resource_id=resource_id).first()
    return render_template('admin_schedules.html', 
                           resource=resource,
                           matutino_schedule=matutino_schedule, 
                           vespertino_schedule=vespertino_schedule)

@app.route('/admin/teachers', methods=['GET', 'POST'])
@admin_required
def manage_teachers():
    if request.method == 'POST':
        name, registration = request.form.get('name'), request.form.get('registration')
        is_admin = 'is_admin' in request.form
        if not all([name, registration]):
            flash('Nome e matrícula são obrigatórios.', 'danger')
        elif Teacher.query.filter_by(registration=registration).first():
            flash('A matrícula informada já está cadastrada.', 'warning')
        else:
            db.session.add(Teacher(name=name, registration=registration, is_admin=is_admin))
            db.session.commit()
            flash('Usuário cadastrado com sucesso!', 'success')
        return redirect(url_for('manage_teachers'))
    teachers = Teacher.query.order_by(Teacher.name).all()
    return render_template('admin_teachers.html', teachers=teachers)

@app.route('/admin/teacher/edit/<int:teacher_id>', methods=['POST'])
@admin_required
def edit_teacher(teacher_id):
    teacher = Teacher.query.get_or_404(teacher_id)
    new_registration = request.form.get('registration')
    
    existing_teacher = Teacher.query.filter(Teacher.id != teacher_id, Teacher.registration == new_registration).first()
    if existing_teacher:
        flash(f'A matrícula "{new_registration}" já está em uso por outro usuário.', 'danger')
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
    base_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
    start_of_week = base_date - timedelta(days=base_date.weekday())
    end_of_week = start_of_week + timedelta(days=4)
    prev_week_date = (start_of_week - timedelta(days=7)).strftime('%Y-%m-%d')
    next_week_date = (start_of_week + timedelta(days=7)).strftime('%Y-%m-%d')
    
    week_headers = []
    day_map = {0: "Segunda", 1: "Terça", 2: "Quarta", 3: "Quinta", 4: "Sexta"}
    for i in range(5):
        current_day_date = start_of_week + timedelta(days=i)
        week_headers.append({'name': day_map[i], 'date': current_day_date.strftime('%d/%m')})
        
    all_week_bookings = Booking.query.filter(Booking.date.between(start_of_week, end_of_week)).all()
    weekly_summaries = []
    
    # --- ALTERAÇÃO AQUI ---
    # 1. Lista de cores reordenada e com amarelo ('bg-warning') adicionado.
    colors = ['bg-success', 'bg-primary', 'bg-warning', 'bg-info', 'bg-secondary', 'bg-dark']
    
    resources_with_schedules = Resource.query.join(ScheduleTemplate).order_by(Resource.sort_order, Resource.name).distinct()

    # 2. Lógica de atribuição de cor usa 'enumerate' para ser mais estável.
    for index, resource in enumerate(resources_with_schedules):
        color_class = colors[index % len(colors)]
        
        for template in sorted(resource.schedule_templates, key=lambda t: t.shift):
            weekly_bookings_data = {}
            resource_bookings = [b for b in all_week_bookings if b.resource_id == resource.id and b.shift == template.shift]
            
            for booking in resource_bookings:
                day_name = day_map.get(booking.date.weekday())
                if day_name:
                    if day_name not in weekly_bookings_data: weekly_bookings_data[day_name] = {}
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
    resources = Resource.query.order_by(Resource.name).all()
    report_data, selected_resource_id, start_date_str, end_date_str = None, None, '', ''
    
    # --- NOVAS VARIÁVEIS PARA O GRÁFICO ---
    chart_labels, chart_data = [], []

    if request.method == 'POST':
        try:
            selected_resource_id = int(request.form.get('resource_id'))
            start_date_str = request.form.get('start_date')
            end_date_str = request.form.get('end_date')
            start_date = datetime.strptime(start_date_str, '%d/%m/%Y').date()
            end_date = datetime.strptime(end_date_str, '%d/%m/%Y').date()
            
            report_query = db.session.query(Booking.teacher_name, func.count(Booking.id)).filter(
                Booking.resource_id == selected_resource_id,
                Booking.date.between(start_date, end_date),
                Booking.status == 'booked').group_by(Booking.teacher_name).order_by(func.count(Booking.id).desc())
            
            report_data = report_query.all()

            # --- LÓGICA PARA PREPARAR OS DADOS DO GRÁFICO ---
            if report_data:
                # Descompacta os dados da query em duas listas separadas
                labels, data = zip(*report_data)
                # Converte para JSON para ser usado de forma segura no JavaScript
                chart_labels = json.dumps(list(labels))
                chart_data = json.dumps(list(data))

        except (ValueError, TypeError):
            flash('Filtros inválidos. Verifique o recurso e as datas (dd/mm/aaaa).', 'danger')

    # Adiciona as novas variáveis no retorno para o template
    return render_template('admin_reports.html', resources=resources, report_data=report_data,
                           selected_resource_id=selected_resource_id, start_date=start_date_str, end_date=end_date_str,
                           chart_labels=chart_labels, chart_data=chart_data)
# --- ROTA PARA MEUS AGENDAMENTOS ---

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
        .filter(Booking.teacher_id == current_user.id)\
        .filter(Booking.date >= today)\
        .order_by(Booking.date, Booking.shift)\
        .all()

    return render_template('my_bookings.html', bookings=bookings_query, weekdays_pt=weekdays_pt)

@app.route('/my-bookings/delete/<int:booking_id>', methods=['POST'])
@login_required
def delete_my_booking(booking_id):
    """Remove um agendamento a partir da página 'Meus Agendamentos'."""
    booking = Booking.query.get_or_404(booking_id)

    # Garante que o usuário só pode apagar seus próprios agendamentos
    if booking.teacher_id == current_user.id or current_user.is_admin:
        db.session.delete(booking)
        db.session.commit()
        flash('Agendamento removido com sucesso.', 'success')
    else:
        flash('Você não tem permissão para remover este agendamento.', 'danger')
    
    return redirect(url_for('my_bookings'))

# --- COMANDOS CLI ---
@app.cli.command("seed-db")
def seed_db_command():
    """Cria o usuário administrador padrão se ele não existir."""
    if not Teacher.query.filter_by(registration='7363').first():
        admin_user = Teacher(
            name='Jardel',
            registration='7363',
            is_admin=True
        )
        db.session.add(admin_user)
        db.session.commit()
        print('Usuário administrador padrão (Jardel) criado com sucesso.')
    else:
        print('Usuário administrador padrão (Jardel) já existe.')

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
                '--format=c', # Formato customizado, mais robusto
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

if __name__ == '__main__':
    app.run()