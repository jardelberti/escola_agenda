"""
Rotas administrativas da Agenda Escolar (recursos, professores, horários, relatórios, backup e restore).
"""
import os
import io
import csv
import json
import shutil
import subprocess
from urllib.parse import urlparse
from datetime import datetime, timedelta, date
from logging import getLogger
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, Response, current_app
from flask_login import current_user
from sqlalchemy import func
from werkzeug.utils import secure_filename
from models import db, Teacher, Resource, ScheduleTemplate, Booking
from extensions import celery
from utils import admin_required, clean_old_backups

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

DATA_DIR = os.path.join(os.path.abspath(os.path.dirname(os.path.dirname(__file__))), 'data')
BACKUP_FOLDER = os.path.join(DATA_DIR, 'backups')
ALLOWED_BACKUP_EXTENSIONS = {'.sql', '.dump', '.tar', '.db'}

@celery.task
def restore_task_bg(filepath, db_uri_str):
    """Executa o pg_restore em segundo plano."""
    log = getLogger(__name__)
    log.info(f"Iniciando restauração do arquivo: {filepath}")
    try:
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
        subprocess.run(command, check=True, env=env, stdin=subprocess.DEVNULL)
        log.info(f"Restauração do arquivo {filepath} concluída com sucesso!")

    except Exception as e:
        log.error(f"Falha na restauração do backup: {str(e)}")
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)
            log.info(f"Arquivo de backup temporário {filepath} removido.")

@admin_bp.route('/')
@admin_required
def admin_dashboard():
    resources = Resource.query.order_by(Resource.sort_order, Resource.name).all()
    return render_template('admin_dashboard.html', resources=resources)

@admin_bp.route('/resource/toggle/<int:resource_id>', methods=['POST', 'GET'])
@admin_required
def toggle_resource(resource_id):
    resource = Resource.query.get_or_404(resource_id)
    resource.is_active = not resource.is_active
    db.session.commit()
    status_str = "reativado" if resource.is_active else "pausado"
    flash(f'Recurso "{resource.name}" foi {status_str} com sucesso!', 'success')
    return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/resources/reorder', methods=['POST'])
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
    return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/resource/add', methods=['POST'])
@admin_required
def add_resource():
    name = request.form.get('name')
    if name:
        is_active = request.form.get('is_active', 'true').lower() in ['true', '1', 'on']
        new_resource = Resource(
            name=name,
            description=request.form.get('description'),
            icon=request.form.get('icon') or 'bi-box',
            is_active=is_active
        )
        db.session.add(new_resource)
        db.session.commit()
        flash('Recurso adicionado com sucesso!', 'success')
    else:
        flash('O nome do recurso é obrigatório.', 'danger')
    return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/resource/edit/<int:resource_id>', methods=['POST'])
@admin_required
def edit_resource(resource_id):
    resource = Resource.query.get_or_404(resource_id)
    name = request.form.get('name')
    if name:
        resource.name = name
        resource.description = request.form.get('description')
        resource.icon = request.form.get('icon') or 'bi-box'
        if 'is_active' in request.form:
            resource.is_active = request.form.get('is_active') in ['true', '1', 'on', True]
        db.session.commit()
        flash('Recurso atualizado com sucesso!', 'success')
    else:
        flash('O nome do recurso não pode ficar em branco.', 'danger')
    return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/resource/delete/<int:resource_id>', methods=['POST'])
@admin_required
def delete_resource(resource_id):
    Booking.query.filter_by(resource_id=resource_id).delete()
    ScheduleTemplate.query.filter_by(resource_id=resource_id).delete()
    resource = Resource.query.get_or_404(resource_id)
    db.session.delete(resource)
    db.session.commit()
    flash('Recurso e todos os seus dados foram removidos com sucesso!', 'success')
    return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/resource/copy/<int:original_id>', methods=['POST'])
@admin_required
def copy_resource(original_id):
    original_resource = Resource.query.get_or_404(original_id)
    new_name = request.form.get('new_name')
    new_icon = request.form.get('new_icon') or 'bi-box'

    if not new_name:
        flash('O novo nome do recurso é obrigatório.', 'danger')
        return redirect(url_for('admin.admin_dashboard'))

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
    return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/schedules/<int:resource_id>', methods=['GET', 'POST'])
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
        return redirect(url_for('admin.manage_schedules', resource_id=resource_id))
    matutino_schedule = ScheduleTemplate.query.filter_by(shift='matutino', resource_id=resource_id).first()
    vespertino_schedule = ScheduleTemplate.query.filter_by(shift='vespertino', resource_id=resource_id).first()
    return render_template('admin_schedules.html', 
                           resource=resource,
                           matutino_schedule=matutino_schedule, 
                           vespertino_schedule=vespertino_schedule)

@admin_bp.route('/teachers', methods=['GET', 'POST'])
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
        return redirect(url_for('admin.manage_teachers'))
    teachers = Teacher.query.order_by(Teacher.name).all()
    return render_template('admin_teachers.html', teachers=teachers)

@admin_bp.route('/teacher/edit/<int:teacher_id>', methods=['POST'])
@admin_required
def edit_teacher(teacher_id):
    teacher = Teacher.query.get_or_404(teacher_id)
    new_registration = request.form.get('registration')
    
    existing_teacher = Teacher.query.filter(Teacher.id != teacher_id, Teacher.registration == new_registration).first()
    if existing_teacher:
        flash(f'A matrícula "{new_registration}" já está em uso por outro usuário.', 'danger')
        return redirect(url_for('admin.manage_teachers'))

    teacher.name = request.form.get('name')
    teacher.registration = new_registration
    teacher.is_admin = 'is_admin' in request.form
    db.session.commit()
    flash('Usuário atualizado com sucesso!', 'success')
    return redirect(url_for('admin.manage_teachers'))

@admin_bp.route('/teacher/delete/<int:teacher_id>', methods=['POST'])
@admin_required
def delete_teacher(teacher_id):
    if current_user.id == teacher_id:
        flash('Você não pode se auto-excluir.', 'danger')
        return redirect(url_for('admin.manage_teachers'))
        
    teacher = Teacher.query.get_or_404(teacher_id)
    Booking.query.filter_by(teacher_id=teacher_id).delete()
    db.session.delete(teacher)
    db.session.commit()
    flash('Usuário e seus agendamentos foram removidos com sucesso.', 'success')
    return redirect(url_for('admin.manage_teachers'))

@admin_bp.route('/weekly-view')
@admin_bp.route('/weekly-view/<string:date_str>')
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
    
    colors = ['bg-success', 'bg-primary', 'bg-warning', 'bg-info', 'bg-secondary', 'bg-dark']
    resources_with_schedules = Resource.query.join(ScheduleTemplate).order_by(Resource.sort_order, Resource.name).distinct()

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

@admin_bp.route('/reports', methods=['GET', 'POST'])
@admin_required
def reports():
    resources = Resource.query.order_by(Resource.name).all()
    report_data, selected_resource_id, start_date_str, end_date_str = None, None, '', ''
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

            if report_data:
                labels, data = zip(*report_data)
                chart_labels = json.dumps(list(labels))
                chart_data = json.dumps(list(data))

        except (ValueError, TypeError):
            flash('Filtros inválidos. Verifique o recurso e as datas (dd/mm/aaaa).', 'danger')

    return render_template('admin_reports.html', resources=resources, report_data=report_data,
                           selected_resource_id=selected_resource_id, start_date=start_date_str, end_date=end_date_str,
                           chart_labels=chart_labels, chart_data=chart_data)

@admin_bp.route('/reports/export')
@admin_required
def export_report():
    """Exporta os dados do relatório de utilização em formato CSV compatível com Excel."""
    try:
        resource_id = int(request.args.get('resource_id'))
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        resource = Resource.query.get_or_404(resource_id)
        start_date = datetime.strptime(start_date_str, '%d/%m/%Y').date()
        end_date = datetime.strptime(end_date_str, '%d/%m/%Y').date()

        report_query = db.session.query(
            Booking.teacher_name, func.count(Booking.id)
        ).filter(
            Booking.resource_id == resource_id,
            Booking.date.between(start_date, end_date),
            Booking.status == 'booked'
        ).group_by(Booking.teacher_name).order_by(func.count(Booking.id).desc())

        report_data = report_query.all()
        total_uses = sum(count for _, count in report_data)

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')

        writer.writerow(['RELATÓRIO DE UTILIZAÇÃO DE RECURSOS'])
        writer.writerow(['Recurso', resource.name])
        writer.writerow(['Período', f'{start_date_str} a {end_date_str}'])
        writer.writerow(['Gerado em', datetime.now().strftime('%d/%m/%Y %H:%M')])
        writer.writerow([])

        writer.writerow(['Professor', 'Quantidade de Usos'])
        for teacher, count in report_data:
            writer.writerow([teacher, count])

        writer.writerow([])
        writer.writerow(['Total Geral de Usos', total_uses])

        clean_name = secure_filename(resource.name.lower().replace(' ', '_')) or 'recurso'
        filename = f"relatorio_{clean_name}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv"
        csv_bytes = output.getvalue().encode('utf-8-sig')

        return Response(
            csv_bytes,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': 'text/csv; charset=utf-8'
            }
        )

    except Exception as e:
        flash(f'Erro ao exportar relatório: {str(e)}', 'danger')
        return redirect(url_for('admin.reports'))

@admin_bp.route('/backup-restore')
@admin_required
def backup_restore_page():
    """Renderiza a página de backup e restauração."""
    return render_template('admin_backup_restore.html')

@admin_bp.route('/backup')
@admin_required
def backup_database():
    """Cria um backup do banco de dados e o oferece para download."""
    db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    os.makedirs(BACKUP_FOLDER, exist_ok=True)
    
    try:
        if db_uri.startswith('postgresql'):
            filename = f'backup_postgres_{timestamp}.sql'
            filepath = os.path.join(BACKUP_FOLDER, filename)
            
            parsed_uri = urlparse(db_uri)
            db_name = parsed_uri.path.lstrip('/')
            user = parsed_uri.username
            password = parsed_uri.password
            host = parsed_uri.hostname
            port = parsed_uri.port

            env = os.environ.copy()
            env['PGPASSWORD'] = password

            command = [
                'pg_dump',
                '--host', host,
                '--port', str(port),
                '--username', user,
                '--dbname', db_name,
                '--no-password',
                '--format=c',
                '--blobs',
                '--no-owner',
                '--file', filepath
            ]
            
            subprocess.run(command, check=True, env=env)
            flash('Backup do PostgreSQL gerado com sucesso!', 'success')
            
        elif db_uri.startswith('sqlite'):
            filename = f'backup_sqlite_{timestamp}.db'
            filepath = os.path.join(BACKUP_FOLDER, filename)
            
            db_path = db_uri.split('///')[1]
            shutil.copy2(db_path, filepath)
            flash('Backup do SQLite gerado com sucesso!', 'success')
            
        else:
            flash('Tipo de banco de dados não suportado para backup.', 'danger')
            return redirect(url_for('admin.backup_restore_page'))
            
        clean_old_backups(BACKUP_FOLDER)
        return send_from_directory(BACKUP_FOLDER, filename, as_attachment=True)

    except Exception as e:
        flash(f'Erro ao gerar o backup: {str(e)}', 'danger')
        return redirect(url_for('admin.backup_restore_page'))

@admin_bp.route('/restore', methods=['POST'])
@admin_required
def restore_database():
    """Salva o arquivo e agenda a restauração em segundo plano após validações."""
    if 'backup_file' not in request.files:
        flash('Nenhum arquivo selecionado.', 'danger')
        return redirect(url_for('admin.backup_restore_page'))

    file = request.files['backup_file']
    if file.filename == '':
        flash('Nenhum arquivo selecionado.', 'danger')
        return redirect(url_for('admin.backup_restore_page'))

    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_BACKUP_EXTENSIONS:
        flash(f'Extensão de arquivo não permitida ({ext}). Tipos aceitos: {", ".join(sorted(ALLOWED_BACKUP_EXTENSIONS))}', 'danger')
        return redirect(url_for('admin.backup_restore_page'))

    os.makedirs(BACKUP_FOLDER, exist_ok=True)
    filepath = os.path.join(BACKUP_FOLDER, filename)
    file.save(filepath)
    
    db_uri_str = current_app.config['SQLALCHEMY_DATABASE_URI']
    restore_task_bg.delay(filepath, db_uri_str)
    
    flash('Restauração iniciada em segundo plano! O processo pode levar alguns minutos para ser concluído.', 'success')
    return redirect(url_for('admin.backup_restore_page'))
