import os
from datetime import datetime, timedelta, date
from flask import Flask, render_template, request, redirect, url_for, flash
from functools import wraps
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from sqlalchemy import func
from models import db, Teacher, Resource, ScheduleTemplate, Booking

# --- CONFIGURAÇÃO DA APLICAÇÃO ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'uma-chave-secreta-muito-dificil-de-adivinhar'

# --- CONFIGURAÇÃO DO BANCO DE DADOS (FLEXÍVEL) ---
if os.environ.get('DOCKER_ENV'):
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////data/agenda.db'
else:
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'agenda.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- INICIALIZAÇÃO DAS EXTENSÕES ---
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Você precisa fazer login para acessar esta página."
login_manager.login_message_category = "warning"

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

# --- ROTAS PRINCIPAIS (PROTEGIDAS PARA TODOS OS LOGADOS) ---

@app.route('/home')
@login_required
def home():
    resources = Resource.query.order_by(Resource.sort_order, Resource.name).all()
    return render_template('index.html', resources=resources)

@app.route('/resource/<int:resource_id>')
@login_required
def select_shift(resource_id):
    resource = Resource.query.get_or_404(resource_id)
    has_matutino = ScheduleTemplate.query.filter_by(shift='matutino', resource_id=resource_id).first() is not None
    has_vespertino = ScheduleTemplate.query.filter_by(shift='vespertino', resource_id=resource_id).first() is not None
    return render_template('select_shift.html', resource=resource, has_matutino=has_matutino, has_vespertino=has_vespertino)

@app.route('/agenda/<int:resource_id>/<string:shift>')
@app.route('/agenda/<int:resource_id>/<string:shift>/<string:date_str>')
@login_required
def agenda_view(resource_id, shift, date_str=None):
    current_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
    resource = Resource.query.get_or_404(resource_id)
    schedule_template = ScheduleTemplate.query.filter_by(shift=shift, resource_id=resource_id).first()
    slots = schedule_template.slots if schedule_template else []
    
    bookings = Booking.query.filter_by(resource_id=resource_id, date=current_date, shift=shift).all()
    booked_slots = {booking.slot_name: booking for booking in bookings}
    
    teachers = Teacher.query.order_by(Teacher.name).all()
    
    return render_template('agenda.html', resource=resource, shift=shift, current_date=current_date,
                           next_day_str=(current_date + timedelta(days=1)).strftime('%Y-%m-%d'),
                           prev_day_str=(current_date - timedelta(days=1)).strftime('%Y-%m-%d'),
                           slots=slots, booked_slots=booked_slots, teachers=teachers)

@app.route('/agenda/book', methods=['POST'])
@login_required
def book_slot():
    resource_id, date_str = request.form.get('resource_id'), request.form.get('date')
    slot_name, shift = request.form.get('slot_name'), request.form.get('shift')
    
    if Booking.query.filter_by(resource_id=resource_id, date=datetime.strptime(date_str, '%Y-%m-%d').date(), slot_name=slot_name, shift=shift).first():
        flash('Este horário foi agendado por outra pessoa.', 'warning')
        return redirect(url_for('agenda_view', resource_id=resource_id, shift=shift, date_str=date_str))

    book_for_teacher = current_user
    if current_user.is_admin:
        selected_teacher_id = request.form.get('teacher_id')
        if selected_teacher_id:
            selected_teacher = Teacher.query.get(int(selected_teacher_id))
            if selected_teacher:
                book_for_teacher = selected_teacher
            else:
                flash('Usuário selecionado para o agendamento é inválido.', 'danger')
                return redirect(url_for('agenda_view', resource_id=resource_id, shift=shift, date_str=date_str))

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
    return redirect(url_for('agenda_view', resource_id=resource_id, shift=shift, date_str=date_str))

@app.route('/agenda/close', methods=['POST'])
@admin_required
def close_slot():
    resource_id, date_str = request.form.get('resource_id'), request.form.get('date')
    slot_name, shift = request.form.get('slot_name'), request.form.get('shift')
    booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()

    if Booking.query.filter_by(resource_id=resource_id, date=booking_date, slot_name=slot_name, shift=shift).first():
        flash('Este horário foi agendado ou fechado por outra pessoa.', 'warning')
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
        flash('Horário fechado com sucesso!', 'success')
    
    return redirect(url_for('agenda_view', resource_id=resource_id, shift=shift, date_str=date_str))

@app.route('/agenda/booking/delete/<int:booking_id>')
@login_required
def delete_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    resource_id, date_str, shift = booking.resource_id, booking.date.strftime('%Y-%m-%d'), request.args.get('shift')

    if current_user.is_admin or booking.teacher_id == current_user.id:
        db.session.delete(booking)
        db.session.commit()
        flash('Agendamento removido com sucesso.', 'success')
    else:
        flash('Você não tem permissão para remover este agendamento.', 'danger')
        
    return redirect(url_for('agenda_view', resource_id=resource_id, shift=shift, date_str=date_str))

# --- ROTAS DE ADMINISTRAÇÃO ---

@app.route('/admin')
@admin_required
def admin_dashboard():
    resources = Resource.query.order_by(Resource.sort_order, Resource.name).all()
    return render_template('admin_dashboard.html', resources=resources)

@app.route('/admin/weekly-view')
@admin_required
def weekly_view():
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=4)
    week_days = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"]
    day_map = {0: "Segunda", 1: "Terça", 2: "Quarta", 3: "Quinta", 4: "Sexta"}

    all_week_bookings = Booking.query.filter(Booking.date.between(start_of_week, end_of_week)).all()
    weekly_summaries = []
    
    # Lista de cores do Bootstrap para alternar
    colors = ['bg-primary', 'bg-success', 'bg-info', 'bg-secondary', 'bg-dark']
    
    resources_with_schedules = Resource.query.join(ScheduleTemplate).order_by(Resource.sort_order, Resource.name).distinct()

    for resource in resources_with_schedules:
        # Define uma cor consistente para cada recurso baseado no seu ID
        color_class = colors[resource.id % len(colors)]
        
        for template in sorted(resource.schedule_templates, key=lambda t: t.shift):
            weekly_bookings_data = {}
            resource_bookings = [b for b in all_week_bookings if b.resource_id == resource.id and b.shift == template.shift]
            
            for booking in resource_bookings:
                day_name = day_map.get(booking.date.weekday())
                if day_name:
                    if day_name not in weekly_bookings_data:
                        weekly_bookings_data[day_name] = {}
                    weekly_bookings_data[day_name][booking.slot_name] = booking

            weekly_summaries.append({
                'title': f'{resource.name} - {template.shift.capitalize()}',
                'week_days': week_days,
                'schedule_template': template,
                'weekly_bookings': weekly_bookings_data,
                'color_class': color_class  # Adiciona a cor ao dicionário
            })
    
    return render_template('admin_weekly_view.html', weekly_summaries=weekly_summaries)

@app.route('/admin/resources/reorder', methods=['POST'])
@admin_required
def reorder_resources():
    ordered_ids = request.form.get('order', '').split(',')
    if ordered_ids:
        for index, resource_id_str in enumerate(ordered_ids):
            resource = Resource.query.get(int(resource_id_str))
            if resource:
                resource.sort_order = index
        db.session.commit()
        flash('A ordem dos recursos foi salva com sucesso!', 'success')
    return redirect(url_for('admin_dashboard'))

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

@app.route('/admin/reports', methods=['GET', 'POST'])
@admin_required
def reports():
    resources = Resource.query.order_by(Resource.name).all()
    report_data, selected_resource_id, start_date_str, end_date_str = None, None, '', ''
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
        except (ValueError, TypeError):
            flash('Filtros inválidos. Verifique o recurso e as datas (dd/mm/aaaa).', 'danger')
    return render_template('admin_reports.html', resources=resources, report_data=report_data,
                           selected_resource_id=selected_resource_id, start_date=start_date_str, end_date=end_date_str)

# --- COMANDOS CLI ---
@app.cli.command("init-db")
def init_db_command():
    with app.app_context():
        db.create_all()
        if not Teacher.query.filter_by(registration='7363').first():
            admin_user = Teacher(
                name='Jardel',
                registration='7363',
                is_admin=True
            )
            db.session.add(admin_user)
            db.session.commit()
            print('Usuário administrador padrão (Jardel) criado com sucesso.')
    print('Banco de dados inicializado.')

if __name__ == '__main__':
    app.run()

