"""
Rotas de visualização e agendamento da Agenda Escolar.
"""
from datetime import datetime, timedelta, date
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from models import db, Teacher, Resource, ScheduleTemplate, Booking

agenda_bp = Blueprint('agenda', __name__)

@agenda_bp.route('/')
def root():
    if current_user.is_authenticated:
        return redirect(url_for('agenda.home'))
    return redirect(url_for('auth.login'))

@agenda_bp.route('/home')
@login_required
def home():
    resources = Resource.query.filter_by(is_active=True).order_by(Resource.sort_order, Resource.name).all()
    return render_template('index.html', resources=resources)

@agenda_bp.route('/resource/<int:resource_id>')
@login_required
def select_shift(resource_id):
    """Carrega a grade dinâmica de agendamento do recurso."""
    resource = Resource.query.get_or_404(resource_id)
    if not resource.is_active and not current_user.is_admin:
        flash(f'O recurso "{resource.name}" está temporariamente indisponível para novos agendamentos.', 'warning')
        return redirect(url_for('agenda.home'))

    teachers = Teacher.query.order_by(Teacher.name).all()
    
    # Lógica para data inicial: se fim de semana, avança para segunda-feira
    initial_date = date.today()
    weekday = initial_date.weekday()
    if weekday == 5:
        initial_date += timedelta(days=2)
    elif weekday == 6:
        initial_date += timedelta(days=1)
        
    return render_template('agenda.html', resource=resource, teachers=teachers, current_date=initial_date)

@agenda_bp.route('/agenda/<int:resource_id>/<string:shift>')
@login_required
def agenda_view(resource_id, shift):
    """Redirecionamento de compatibilidade da URL antiga."""
    return redirect(url_for('agenda.select_shift', resource_id=resource_id, shift=shift))

@agenda_bp.route('/api/agenda/<int:resource_id>/<string:date_str>')
@login_required
def get_agenda_data(resource_id, date_str):
    """Retorna os slots e agendamentos do recurso na data em formato JSON."""
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

@agenda_bp.route('/agenda/close', methods=['POST'])
@login_required
def close_slot():
    if not current_user.is_admin:
        return jsonify({'error': 'Acesso negado'}), 403

    resource_id = request.form.get('resource_id')
    date_str = request.form.get('date')
    shift = request.form.get('shift')
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
    except IntegrityError:
        db.session.rollback()
        flash('Este horário já foi agendado ou fechado.', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Ocorreu um erro ao tentar fechar o horário: {e}', 'danger')

    return redirect(url_for('agenda.select_shift', resource_id=resource_id, date=date_str, shift=shift))

@agenda_bp.route('/agenda/book', methods=['POST'])
@login_required
def book_slot():
    resource_id = request.form.get('resource_id')
    date_str = request.form.get('date')
    slot_name = request.form.get('slot_name')
    shift = request.form.get('shift')

    resource = Resource.query.get(int(resource_id)) if resource_id else None
    if not resource or (not resource.is_active and not current_user.is_admin):
        flash('Este recurso está temporariamente pausado para novos agendamentos.', 'warning')
        return redirect(url_for('agenda.home'))

    try:
        booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        flash('Data de agendamento inválida.', 'danger')
        return redirect(url_for('agenda.select_shift', resource_id=resource_id, date=date_str, shift=shift))

    if not current_user.is_admin and booking_date < date.today():
        flash('Não é permitido agendar horários em datas passadas.', 'warning')
        return redirect(url_for('agenda.select_shift', resource_id=resource_id, date=date_str, shift=shift))

    if Booking.query.filter_by(resource_id=resource_id, date=booking_date, slot_name=slot_name, shift=shift).first():
        flash('Este horário foi agendado por outra pessoa.', 'warning')
        return redirect(url_for('agenda.select_shift', resource_id=resource_id, date=date_str, shift=shift))

    book_for_teacher = current_user
    if current_user.is_admin:
        selected_teacher_id = request.form.get('teacher_id')
        if selected_teacher_id:
            book_for_teacher = Teacher.query.get(int(selected_teacher_id))

    new_booking = Booking(
        resource_id=int(resource_id),
        date=booking_date,
        slot_name=slot_name,
        shift=shift,
        teacher_id=book_for_teacher.id,
        teacher_name=book_for_teacher.name
    )
    try:
        db.session.add(new_booking)
        db.session.commit()
        flash('Horário agendado com sucesso!', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('Este horário acabou de ser agendado por outra pessoa.', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Ocorreu um erro ao realizar o agendamento: {e}', 'danger')

    return redirect(url_for('agenda.select_shift', resource_id=resource_id, date=date_str, shift=shift))

@agenda_bp.route('/agenda/booking/delete/<int:booking_id>', methods=['POST'])
@login_required
def delete_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    resource_id = booking.resource_id
    date_str = request.form.get('date') or request.args.get('date')
    shift = request.form.get('shift') or request.args.get('shift')

    if current_user.is_admin or booking.teacher_id == current_user.id:
        db.session.delete(booking)
        db.session.commit()
        flash('Agendamento removido com sucesso.', 'success')
    else:
        flash('Você não tem permissão para remover este agendamento.', 'danger')
    
    return redirect(url_for('agenda.select_shift', resource_id=resource_id, date=date_str, shift=shift))

@agenda_bp.route('/my-bookings')
@login_required
def my_bookings():
    """Exibe os agendamentos futuros do usuário logado."""
    today = date.today()
    weekdays_pt = {
        0: "Segunda-feira", 1: "Terça-feira", 2: "Quarta-feira", 
        3: "Quinta-feira", 4: "Sexta-feira", 5: "Sábado", 6: "Domingo"
    }

    bookings_query = db.session.query(Booking, Resource)\
        .join(Resource, Booking.resource_id == Resource.id)\
        .filter(Booking.teacher_id == current_user.id)\
        .filter(Booking.date >= today)\
        .order_by(Booking.date, Booking.shift)\
        .all()

    return render_template('my_bookings.html', bookings=bookings_query, weekdays_pt=weekdays_pt)

@agenda_bp.route('/my-bookings/delete/<int:booking_id>', methods=['POST'])
@login_required
def delete_my_booking(booking_id):
    """Remove um agendamento a partir da página 'Meus Agendamentos'."""
    booking = Booking.query.get_or_404(booking_id)

    if booking.teacher_id == current_user.id or current_user.is_admin:
        db.session.delete(booking)
        db.session.commit()
        flash('Agendamento removido com sucesso.', 'success')
    else:
        flash('Você não tem permissão para remover este agendamento.', 'danger')
    
    return redirect(url_for('agenda.my_bookings'))
