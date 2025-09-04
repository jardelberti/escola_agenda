import os
from datetime import datetime, timedelta, date
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from sqlalchemy import func
from models import db, User, Resource, ScheduleTemplate, Booking

# --- CONFIGURAÇÃO DA APLICAÇÃO ---
app = Flask(__name__)

# Configurações essenciais
app.config['SECRET_KEY'] = 'uma-chave-secreta-muito-dificil-de-adivinhar'
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'agenda.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- INICIALIZAÇÃO DAS EXTENSÕES ---
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Por favor, faça login para acessar esta página."
login_manager.login_message_category = "warning"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- ROTAS (PÁGINAS) DA APLICAÇÃO ---

@app.route('/')
def index():
    resources = Resource.query.order_by(Resource.name).all()
    return render_template('index.html', resources=resources)

# --- ROTAS DE ADMINISTRAÇÃO ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Usuário ou senha inválidos.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você foi desconectado.', 'success')
    return redirect(url_for('login'))

@app.route('/admin')
@login_required
def admin_dashboard():
    resources = Resource.query.order_by(Resource.name).all()
    return render_template('admin_dashboard.html', resources=resources)

@app.route('/admin/resource/add', methods=['POST'])
@login_required
def add_resource():
    name = request.form.get('name')
    if name:
        new_resource = Resource(
            name=name,
            description=request.form.get('description'),
            icon=request.form.get('icon') or 'bi-box'
        )
        db.session.add(new_resource)
        db.session.commit()
        flash('Recurso adicionado com sucesso!', 'success')
    else:
        flash('O nome do recurso é obrigatório.', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/resource/edit/<int:resource_id>', methods=['POST'])
@login_required
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
@login_required
def delete_resource(resource_id):
    Booking.query.filter_by(resource_id=resource_id).delete()
    resource = Resource.query.get_or_404(resource_id)
    db.session.delete(resource)
    db.session.commit()
    flash('Recurso e todos os seus agendamentos foram removidos com sucesso!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        if not current_user.check_password(request.form.get('current_password')):
            flash('A senha atual está incorreta.', 'danger')
        elif request.form.get('new_password') != request.form.get('confirm_password'):
            flash('A nova senha e a confirmação não coincidem.', 'danger')
        elif not request.form.get('new_password'):
            flash('A nova senha não pode estar em branco.', 'danger')
        else:
            current_user.set_password(request.form.get('new_password'))
            db.session.commit()
            flash('Sua senha foi alterada com sucesso!', 'success')
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('change_password'))
    return render_template('admin_change_password.html')

@app.route('/admin/schedules', methods=['GET', 'POST'])
@login_required
def manage_schedules():
    if request.method == 'POST':
        shift = request.form.get('shift')
        slot_names = request.form.getlist('slot_name')
        slot_types = request.form.getlist('slot_type')
        slots_data = [{"name": name, "type": type} for name, type in zip(slot_names, slot_types) if name]
        schedule = ScheduleTemplate.query.filter_by(shift=shift).first()
        if schedule:
            schedule.slots = slots_data
        else:
            schedule = ScheduleTemplate(shift=shift, slots=slots_data)
            db.session.add(schedule)
        db.session.commit()
        flash(f'Horários do turno {shift} salvos com sucesso!', 'success')
        return redirect(url_for('manage_schedules'))
    matutino_schedule = ScheduleTemplate.query.filter_by(shift='matutino').first()
    vespertino_schedule = ScheduleTemplate.query.filter_by(shift='vespertino').first()
    return render_template('admin_schedules.html', 
                           matutino_schedule=matutino_schedule, 
                           vespertino_schedule=vespertino_schedule)

@app.route('/admin/reports', methods=['GET', 'POST'])
@login_required
def reports():
    resources = Resource.query.order_by(Resource.name).all()
    report_data = None
    selected_resource_id = None
    start_date_str = ''
    end_date_str = ''

    if request.method == 'POST':
        try:
            selected_resource_id = int(request.form.get('resource_id'))
            start_date_str = request.form.get('start_date')
            end_date_str = request.form.get('end_date')
            start_date = datetime.strptime(start_date_str, '%d/%m/%Y').date()
            end_date = datetime.strptime(end_date_str, '%d/%m/%Y').date()
            
            report_query = db.session.query(
                Booking.teacher_name,
                func.count(Booking.id)
            ).filter(
                Booking.resource_id == selected_resource_id,
                Booking.date.between(start_date, end_date),
                Booking.status == 'booked'
            ).group_by(
                Booking.teacher_name
            ).order_by(
                func.count(Booking.id).desc()
            )
            report_data = report_query.all()
        except (ValueError, TypeError):
            flash('Filtros inválidos. Verifique o recurso e as datas (dd/mm/aaaa).', 'danger')
            return redirect(url_for('reports'))

    return render_template('admin_reports.html',
                           resources=resources, report_data=report_data,
                           selected_resource_id=selected_resource_id,
                           start_date=start_date_str, end_date=end_date_str)

# --- ROTAS DE AGENDAMENTO ---

@app.route('/resource/<int:resource_id>')
def select_shift(resource_id):
    resource = Resource.query.get_or_404(resource_id)
    has_matutino = ScheduleTemplate.query.filter_by(shift='matutino').first() is not None
    has_vespertino = ScheduleTemplate.query.filter_by(shift='vespertino').first() is not None
    return render_template('select_shift.html', resource=resource, has_matutino=has_matutino, has_vespertino=has_vespertino)

@app.route('/agenda/<int:resource_id>/<string:shift>')
@app.route('/agenda/<int:resource_id>/<string:shift>/<string:date_str>')
def agenda_view(resource_id, shift, date_str=None):
    current_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
    resource = Resource.query.get_or_404(resource_id)
    schedule_template = ScheduleTemplate.query.filter_by(shift=shift).first()
    slots = schedule_template.slots if schedule_template else []
    bookings = Booking.query.filter_by(resource_id=resource_id, date=current_date).all()
    booked_slots = {booking.slot_name: booking for booking in bookings}
    
    return render_template('agenda.html',
                           resource=resource, shift=shift, current_date=current_date,
                           next_day_str=(current_date + timedelta(days=1)).strftime('%Y-%m-%d'),
                           prev_day_str=(current_date - timedelta(days=1)).strftime('%Y-%m-%d'),
                           slots=slots, booked_slots=booked_slots)

@app.route('/agenda/book', methods=['POST'])
def book_slot():
    resource_id = request.form.get('resource_id')
    date_str = request.form.get('date')
    slot_name = request.form.get('slot_name')
    teacher_name = request.form.get('teacher_name')
    shift = request.form.get('shift')

    if not all([resource_id, date_str, slot_name, teacher_name, shift]):
        flash('Informações incompletas para realizar o agendamento.', 'danger')
        return redirect(url_for('index'))

    booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    existing_booking = Booking.query.filter_by(resource_id=resource_id, date=booking_date, slot_name=slot_name).first()
    
    if existing_booking:
        flash('Este horário foi agendado por outra pessoa. Por favor, escolha outro.', 'warning')
    else:
        new_booking = Booking(resource_id=int(resource_id), date=booking_date, slot_name=slot_name, teacher_name=teacher_name, status='booked')
        db.session.add(new_booking)
        db.session.commit()
        flash('Horário agendado com sucesso!', 'success')
    return redirect(url_for('agenda_view', resource_id=resource_id, shift=shift, date_str=date_str))

@app.route('/agenda/booking/delete/<int:booking_id>')
@login_required
def delete_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    resource_id = booking.resource_id
    date_str = booking.date.strftime('%Y-%m-%d')
    shift = request.args.get('shift')
    db.session.delete(booking)
    db.session.commit()
    flash('Agendamento removido com sucesso.', 'success')
    return redirect(url_for('agenda_view', resource_id=resource_id, shift=shift, date_str=date_str))

# --- COMANDOS CLI ---
@app.cli.command("init-db")
def init_db_command():
    """Cria as tabelas do banco de dados e o usuário admin inicial."""
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin')
        admin.set_password('asd456')
        db.session.add(admin)
        db.session.commit()
        print('Usuário admin criado com sucesso.')
    print('Banco de dados inicializado.')

if __name__ == '__main__':
    app.run()

