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
from models import db, Teacher, Resource, ScheduleTemplate, Booking, BookingAuditLog
from extensions import celery
from utils import admin_required, clean_old_backups, sanitize_phone, format_phone

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
    """Painel principal do administrador com resumo de KPIs, gráficos e atividades de hoje."""
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    thirty_days_ago = today - timedelta(days=30)
    fourteen_days_ago = today - timedelta(days=13)

    # 1. Indicadores Chave (KPIs)
    bookings_today_count = Booking.query.filter_by(date=today, status='booked').count()
    bookings_week_count = Booking.query.filter(
        Booking.date.between(start_of_week, end_of_week),
        Booking.status == 'booked'
    ).count()
    total_resources = Resource.query.count()
    active_resources = Resource.query.filter_by(is_active=True).count()
    total_teachers = Teacher.query.filter_by(is_active=True).count()
    total_cancelations = BookingAuditLog.query.count()

    # 2. Agendamentos de Hoje (Resumo operacional)
    today_bookings = db.session.query(Booking, Resource)\
        .join(Resource, Booking.resource_id == Resource.id)\
        .filter(Booking.date == today, Booking.status == 'booked')\
        .order_by(Booking.shift, Booking.slot_name, Resource.name)\
        .all()

    # 3. Gráfico 1: Utilização por Recurso (Últimos 30 dias)
    resource_usage_query = db.session.query(
        Resource.name, func.count(Booking.id)
    ).join(Booking, Resource.id == Booking.resource_id)\
     .filter(Booking.date >= thirty_days_ago, Booking.status == 'booked')\
     .group_by(Resource.name)\
     .order_by(func.count(Booking.id).desc())\
     .all()

    chart_resource_labels = [r[0] for r in resource_usage_query]
    chart_resource_data = [r[1] for r in resource_usage_query]

    if not chart_resource_labels:
        all_res = Resource.query.all()
        chart_resource_labels = [r.name for r in all_res]
        chart_resource_data = [0 for _ in all_res]

    # 4. Gráfico 2: Evolução dos Últimos 14 Dias (Linha do tempo)
    daily_counts_map = dict(
        db.session.query(Booking.date, func.count(Booking.id))\
        .filter(Booking.date.between(fourteen_days_ago, today), Booking.status == 'booked')\
        .group_by(Booking.date)\
        .all()
    )

    chart_timeline_labels = []
    chart_timeline_data = []
    for i in range(14):
        d = fourteen_days_ago + timedelta(days=i)
        chart_timeline_labels.append(d.strftime('%d/%m'))
        chart_timeline_data.append(daily_counts_map.get(d, 0))

    # 5. Gráfico 3: Matutino vs Vespertino (Últimos 30 dias)
    shift_counts = dict(
        db.session.query(Booking.shift, func.count(Booking.id))\
        .filter(Booking.date >= thirty_days_ago, Booking.status == 'booked')\
        .group_by(Booking.shift)\
        .all()
    )
    chart_shift_labels = ['☀️ Matutino', '🌅 Vespertino']
    chart_shift_data = [shift_counts.get('matutino', 0), shift_counts.get('vespertino', 0)]

    return render_template(
        'admin_dashboard.html',
        bookings_today_count=bookings_today_count,
        bookings_week_count=bookings_week_count,
        total_resources=total_resources,
        active_resources=active_resources,
        total_teachers=total_teachers,
        total_cancelations=total_cancelations,
        today_bookings=today_bookings,
        chart_resource_labels=chart_resource_labels,
        chart_resource_data=chart_resource_data,
        chart_timeline_labels=chart_timeline_labels,
        chart_timeline_data=chart_timeline_data,
        chart_shift_labels=chart_shift_labels,
        chart_shift_data=chart_shift_data
    )

@admin_bp.route('/resources')
@admin_required
def manage_resources():
    """Gerencia a lista de recursos escolares (cadastro, edição, reordenação)."""
    resources = Resource.query.order_by(Resource.sort_order, Resource.name).all()
    return render_template('admin_resources.html', resources=resources)

@admin_bp.route('/resource/toggle/<int:resource_id>', methods=['POST', 'GET'])
@admin_required
def toggle_resource(resource_id):
    resource = Resource.query.get_or_404(resource_id)
    resource.is_active = not resource.is_active
    db.session.commit()
    status_str = "reativado" if resource.is_active else "pausado"
    flash(f'Recurso "{resource.name}" foi {status_str} com sucesso!', 'success')
    return redirect(url_for('admin.manage_resources'))

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
    return redirect(url_for('admin.manage_resources'))

@admin_bp.route('/resource/add', methods=['POST'])
@admin_required
def add_resource():
    name = request.form.get('name')
    if name:
        is_active = request.form.get('is_active', 'true').lower() in ['true', '1', 'on']
        quantity = request.form.get('quantity', 1)
        try:
            quantity = max(1, int(quantity))
        except (ValueError, TypeError):
            quantity = 1

        max_weekly_str = request.form.get('max_weekly_bookings', '')
        max_weekly_bookings = None
        if max_weekly_str and max_weekly_str.strip().isdigit():
            max_weekly_bookings = max(1, int(max_weekly_str.strip()))

        new_resource = Resource(
            name=name,
            description=request.form.get('description'),
            icon=request.form.get('icon') or 'bi-box',
            is_active=is_active,
            quantity=quantity,
            max_weekly_bookings=max_weekly_bookings
        )
        db.session.add(new_resource)
        db.session.commit()
        flash('Recurso adicionado com sucesso!', 'success')
    else:
        flash('O nome do recurso é obrigatório.', 'danger')
    return redirect(url_for('admin.manage_resources'))

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
        if 'quantity' in request.form:
            try:
                resource.quantity = max(1, int(request.form.get('quantity', 1)))
            except (ValueError, TypeError):
                pass
        
        max_weekly_str = request.form.get('max_weekly_bookings')
        if max_weekly_str is not None:
            if max_weekly_str.strip().isdigit():
                resource.max_weekly_bookings = max(1, int(max_weekly_str.strip()))
            else:
                resource.max_weekly_bookings = None

        db.session.commit()
        flash('Recurso atualizado com sucesso!', 'success')
    else:
        flash('O nome do recurso não pode ficar em branco.', 'danger')
    return redirect(url_for('admin.manage_resources'))

@admin_bp.route('/resource/delete/<int:resource_id>', methods=['POST'])
@admin_required
def delete_resource(resource_id):
    Booking.query.filter_by(resource_id=resource_id).delete()
    ScheduleTemplate.query.filter_by(resource_id=resource_id).delete()
    resource = Resource.query.get_or_404(resource_id)
    db.session.delete(resource)
    db.session.commit()
    flash('Recurso e todos os seus dados foram removidos com sucesso!', 'success')
    return redirect(url_for('admin.manage_resources'))

@admin_bp.route('/resource/copy/<int:original_id>', methods=['POST'])
@admin_required
def copy_resource(original_id):
    original_resource = Resource.query.get_or_404(original_id)
    new_name = request.form.get('new_name')
    new_icon = request.form.get('new_icon') or 'bi-box'

    if not new_name:
        flash('O novo nome do recurso é obrigatório.', 'danger')
        return redirect(url_for('admin.manage_resources'))

    new_resource = Resource(
        name=new_name,
        description=original_resource.description,
        icon=new_icon,
        sort_order=original_resource.sort_order + 1,
        quantity=original_resource.quantity,
        max_weekly_bookings=original_resource.max_weekly_bookings
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
    return redirect(url_for('admin.manage_resources'))

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
        whatsapp = sanitize_phone(request.form.get('whatsapp'))
        is_admin = 'is_admin' in request.form
        if not all([name, registration]):
            flash('Nome e matrícula são obrigatórios.', 'danger')
        elif Teacher.query.filter_by(registration=registration).first():
            flash('A matrícula informada já está cadastrada.', 'warning')
        else:
            db.session.add(Teacher(name=name, registration=registration, whatsapp=whatsapp, is_admin=is_admin))
            db.session.commit()
            flash('Usuário cadastrado com sucesso!', 'success')
        return redirect(url_for('admin.manage_teachers'))
    teachers = Teacher.query.order_by(Teacher.is_active.desc(), Teacher.name).all()
    return render_template('admin_teachers.html', teachers=teachers, format_phone=format_phone)

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
    teacher.whatsapp = sanitize_phone(request.form.get('whatsapp'))
    teacher.is_admin = 'is_admin' in request.form
    if current_user.id != teacher_id:
        teacher.is_active = 'is_active' in request.form
    db.session.commit()
    flash('Usuário atualizado com sucesso!', 'success')
    return redirect(url_for('admin.manage_teachers'))

@admin_bp.route('/teacher/toggle/<int:teacher_id>', methods=['GET', 'POST'])
@admin_required
def toggle_teacher(teacher_id):
    """Ativa ou desativa o acesso de um professor sem apagar histórico de agendamentos."""
    if current_user.id == teacher_id:
        flash('Você não pode desativar seu próprio usuário administrador.', 'danger')
        return redirect(url_for('admin.manage_teachers'))
        
    teacher = Teacher.query.get_or_404(teacher_id)
    teacher.is_active = not teacher.is_active
    db.session.commit()
    status_str = "reativado" if teacher.is_active else "desativado"
    category = "success" if teacher.is_active else "warning"
    flash(f'Usuário "{teacher.name}" foi {status_str} com sucesso!', category)
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
                    if day_name not in weekly_bookings_data:
                        weekly_bookings_data[day_name] = {}
                    if booking.slot_name not in weekly_bookings_data[day_name]:
                        weekly_bookings_data[day_name][booking.slot_name] = []
                    weekly_bookings_data[day_name][booking.slot_name].append(booking)
                    
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

@admin_bp.route('/audit-logs')
@admin_required
def manage_audit_logs():
    """Exibe o histórico de cancelamentos de agendamentos para auditoria."""
    query = BookingAuditLog.query.order_by(BookingAuditLog.created_at.desc())
    search_q = request.args.get('q', '').strip()
    if search_q:
        search_filter = f"%{search_q}%"
        query = query.filter(
            db.or_(
                BookingAuditLog.teacher_name.ilike(search_filter),
                BookingAuditLog.performed_by_name.ilike(search_filter),
                BookingAuditLog.resource_name.ilike(search_filter),
                BookingAuditLog.classroom_or_notes.ilike(search_filter)
            )
        )
    logs = query.limit(200).all()
    return render_template('admin_audit_logs.html', logs=logs, search_q=search_q)

@admin_bp.route('/recurring-booking', methods=['GET', 'POST'])
@admin_required
def recurring_booking():
    """Permite ao administrador agendar horários fixos para o bimestre todo em lote."""
    resources = Resource.query.filter_by(is_active=True).order_by(Resource.name).all()
    teachers = Teacher.query.filter_by(is_active=True).order_by(Teacher.name).all()

    if request.method == 'POST':
        resource_id = request.form.get('resource_id')
        teacher_id = request.form.get('teacher_id')
        shift = request.form.get('shift')
        slot_names = request.form.getlist('slot_names')
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        weekdays_selected = [int(w) for w in request.form.getlist('weekdays')]
        classroom_or_notes = (request.form.get('classroom_or_notes') or '').strip() or None

        if not all([resource_id, teacher_id, shift, slot_names, start_date_str, end_date_str, weekdays_selected]):
            flash('Por favor, preencha todos os campos obrigatórios do agendamento recorrente.', 'danger')
            return redirect(url_for('admin.recurring_booking'))

        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Formato de data inválido.', 'danger')
            return redirect(url_for('admin.recurring_booking'))

        if start_date > end_date:
            flash('A data inicial deve ser anterior ou igual à data final.', 'danger')
            return redirect(url_for('admin.recurring_booking'))

        resource = Resource.query.get_or_404(int(resource_id))
        teacher = Teacher.query.get_or_404(int(teacher_id))
        capacity = resource.quantity or 1

        created_count = 0
        skipped_count = 0

        current_d = start_date
        while current_d <= end_date:
            if current_d.weekday() in weekdays_selected:
                for s_name in slot_names:
                    # Verifica conflito e capacidade
                    existing_bookings = Booking.query.filter_by(
                        resource_id=resource.id,
                        date=current_d,
                        shift=shift,
                        slot_name=s_name
                    ).all()

                    already_by_teacher = any(b.teacher_id == teacher.id and b.status == 'booked' for b in existing_bookings)
                    if len(existing_bookings) < capacity and not already_by_teacher:
                        new_b = Booking(
                            resource_id=resource.id,
                            teacher_id=teacher.id,
                            teacher_name=teacher.name,
                            date=current_d,
                            shift=shift,
                            slot_name=s_name,
                            status='booked',
                            classroom_or_notes=classroom_or_notes
                        )
                        db.session.add(new_b)
                        created_count += 1
                    else:
                        skipped_count += 1
            current_d += timedelta(days=1)

        db.session.commit()
        if created_count > 0:
            msg = f'Sucesso! {created_count} aulas foram agendadas em lote para {teacher.name}.'
            if skipped_count > 0:
                msg += f' ({skipped_count} horários ignorados por já estarem ocupados).'
            flash(msg, 'success')
        else:
            flash(f'Nenhuma aula foi agendada. Todos os {skipped_count} horários selecionados já estavam ocupados.', 'warning')

        return redirect(url_for('admin.recurring_booking'))

    return render_template('admin_recurring_booking.html', resources=resources, teachers=teachers)


@admin_bp.route('/live-notifications')
@admin_required
def live_notifications():
    """Endpoint de polling leve para notificações de reservas em tempo real no navegador do administrador."""
    last_id = request.args.get('last_id', type=int, default=0)
    initial = request.args.get('initial', type=int, default=0)

    max_id = db.session.query(func.max(Booking.id)).scalar() or 0

    def serialize_booking(b):
        is_today = (b.date == date.today())
        is_tomorrow = (b.date == date.today() + timedelta(days=1))
        
        if is_today:
            date_display = 'HOJE'
        elif is_tomorrow:
            date_display = 'AMANHÃ'
        else:
            date_display = b.date.strftime('%d/%m/%Y')

        shift_map = {'matutino': 'Matutino', 'vespertino': 'Vespertino'}
        shift_label = shift_map.get(b.shift.lower(), b.shift)

        return {
            'id': b.id,
            'teacher_name': b.teacher_name,
            'resource_name': b.resource.name if b.resource else 'Recurso',
            'resource_icon': b.resource.icon if (b.resource and b.resource.icon) else 'meeting_room',
            'date': b.date.strftime('%d/%m/%Y'),
            'date_display': date_display,
            'is_today': is_today,
            'is_tomorrow': is_tomorrow,
            'shift': shift_label,
            'slot_name': b.slot_name,
            'classroom_or_notes': b.classroom_or_notes or '',
            'created_at': b.created_at.strftime('%H:%M') if getattr(b, 'created_at', None) else ''
        }

    # Se for o carregamento inicial da página, obtém o max_id e as 5 últimas reservas sem soar alarme
    if initial == 1:
        recent = (
            Booking.query
            .filter(Booking.status == 'booked')
            .order_by(Booking.id.desc())
            .limit(5)
            .all()
        )
        return jsonify({
            'max_id': max_id,
            'new_bookings': [],
            'recent_history': [serialize_booking(b) for b in recent]
        })

    # Consulta novos agendamentos criados após last_id
    new_bookings = []
    if last_id > 0 and last_id < max_id:
        new_bookings = (
            Booking.query
            .filter(Booking.id > last_id, Booking.status == 'booked')
            .order_by(Booking.id.asc())
            .limit(10)
            .all()
        )

    return jsonify({
        'max_id': max(max_id, last_id),
        'new_bookings': [serialize_booking(b) for b in new_bookings]
    })
