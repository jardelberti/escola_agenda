"""
Rotas de integração da Agenda Escolar com sistemas externos (n8n, Evolution API, WhatsApp, etc.).
"""
import os
from datetime import datetime, date
from flask import Blueprint, request, jsonify
from models import db, Teacher, Resource, Booking
from utils import format_phone

integrations_bp = Blueprint('integrations', __name__, url_prefix='/api/integrations')

DEFAULT_API_KEY = 'escola-agenda-integracao-2026'

WEEKDAYS_PT = {
    0: "Segunda-feira",
    1: "Terça-feira",
    2: "Quarta-feira",
    3: "Quinta-feira",
    4: "Sexta-feira",
    5: "Sábado",
    6: "Domingo"
}

def verify_token():
    """Valida o token recebido via query param ou header X-API-Key / Authorization."""
    expected_token = os.environ.get('INTEGRATION_API_KEY', DEFAULT_API_KEY)
    
    # 1. Verifica query param
    token = request.args.get('token') or request.args.get('api_key')
    
    # 2. Se não estiver na URL, verifica header X-API-Key
    if not token:
        token = request.headers.get('X-API-Key')
        
    # 3. Verifica Authorization Bearer
    if not token:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:].strip()
            
    return bool(token and token == expected_token)


@integrations_bp.route('/daily-summary', methods=['GET'])
def daily_summary():
    """
    Retorna o resumo diário de agendamentos estruturado em JSON e pré-formatado
    para envio no WhatsApp (tanto resumo geral para grupos quanto individual por professor).
    """
    if not verify_token():
        return jsonify({
            'status': 'error',
            'message': 'Acesso não autorizado. Informe o token correto via query param (?token=...) ou header X-API-Key.'
        }), 401

    date_str = request.args.get('date')
    if date_str:
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'status': 'error', 'message': 'Data inválida. Use o formato AAAA-MM-DD.'}), 400
    else:
        target_date = date.today()

    weekday_name = WEEKDAYS_PT[target_date.weekday()]
    formatted_date = target_date.strftime('%d/%m/%Y')

    # Busca todos os agendamentos ativos na data
    bookings_query = db.session.query(Booking, Resource, Teacher)\
        .join(Resource, Booking.resource_id == Resource.id)\
        .join(Teacher, Booking.teacher_id == Teacher.id)\
        .filter(Booking.date == target_date, Booking.status == 'booked')\
        .order_by(Resource.sort_order, Resource.name, Booking.shift, Booking.slot_name)\
        .all()

    total_bookings = len(bookings_query)

    # 1. Agrupamento por recurso (para a mensagem geral do grupo)
    by_resource = {}
    for booking, resource, teacher in bookings_query:
        if resource.name not in by_resource:
            by_resource[resource.name] = {
                'icon': resource.icon or 'bi-box',
                'bookings': []
            }
        by_resource[resource.name]['bookings'].append({
            'shift': booking.shift,
            'slot_name': booking.slot_name,
            'teacher_name': teacher.name
        })

    # Constrói o texto geral formatado para WhatsApp (com emojis e negrito)
    summary_lines = [
        f"📅 *Agenda Escolar - {weekday_name} ({formatted_date})*",
        ""
    ]

    if total_bookings == 0:
        summary_lines.append("Nenhum recurso agendado para hoje até o momento.")
        summary_lines.append("")
        summary_lines.append("✨ Tenham um excelente dia letivo!")
    else:
        for res_name, data in by_resource.items():
            icon_emoji = "🖥️" if "informática" in res_name.lower() else "📽️" if "projetor" in res_name.lower() or "multimídia" in res_name.lower() else "📍"
            summary_lines.append(f"{icon_emoji} *{res_name}*")
            for b in data['bookings']:
                shift_label = "Matutino" if b['shift'] == 'matutino' else "Vespertino" if b['shift'] == 'vespertino' else b['shift'].capitalize()
                summary_lines.append(f"  • {b['slot_name']} ({shift_label}): Prof(a). {b['teacher_name']}")
            summary_lines.append("")

        summary_lines.append("✨ Desejamos a todos um ótimo dia de aulas e atividades!")

    summary_text = "\n".join(summary_lines).strip()

    # 2. Agrupamento individual por professor (para lembretes privados)
    by_teacher = {}
    for booking, resource, teacher in bookings_query:
        if teacher.id not in by_teacher:
            by_teacher[teacher.id] = {
                'teacher_id': teacher.id,
                'teacher_name': teacher.name,
                'whatsapp': teacher.whatsapp,
                'whatsapp_formatted': format_phone(teacher.whatsapp) if teacher.whatsapp else None,
                'bookings': []
            }
        by_teacher[teacher.id]['bookings'].append({
            'resource_name': resource.name,
            'shift': booking.shift,
            'slot_name': booking.slot_name
        })

    teachers_summaries = []
    for t_id, t_data in by_teacher.items():
        # Gera texto personalizado para cada professor
        prof_lines = [
            f"Olá Prof(a). {t_data['teacher_name']}! 👋",
            f"📌 *Seu lembrete de agendamentos para hoje ({formatted_date} - {weekday_name}):*",
            ""
        ]
        for b in t_data['bookings']:
            shift_label = "Matutino" if b['shift'] == 'matutino' else "Vespertino" if b['shift'] == 'vespertino' else b['shift'].capitalize()
            prof_lines.append(f"• *{b['resource_name']}*: {b['slot_name']} ({shift_label})")
        
        prof_lines.append("")
        prof_lines.append("Tenha uma excelente aula! 🎓")
        
        t_data['message'] = "\n".join(prof_lines).strip()
        t_data['bookings_count'] = len(t_data['bookings'])
        teachers_summaries.append(t_data)

    return jsonify({
        'status': 'success',
        'date': target_date.strftime('%Y-%m-%d'),
        'formatted_date': formatted_date,
        'weekday': weekday_name,
        'total_bookings': total_bookings,
        'summary_text': summary_text,
        'teachers_summaries': teachers_summaries
    }), 200


@integrations_bp.route('/teachers', methods=['GET'])
def list_teachers_for_integration():
    """Retorna a lista de professores com informações de contato WhatsApp cadastradas."""
    if not verify_token():
        return jsonify({'status': 'error', 'message': 'Não autorizado.'}), 401

    teachers = Teacher.query.order_by(Teacher.name).all()
    result = []
    for t in teachers:
        result.append({
            'id': t.id,
            'name': t.name,
            'registration': t.registration,
            'whatsapp': t.whatsapp,
            'whatsapp_formatted': format_phone(t.whatsapp) if t.whatsapp else None,
            'has_whatsapp': bool(t.whatsapp),
            'is_admin': t.is_admin
        })

    return jsonify({
        'status': 'success',
        'count': len(result),
        'teachers': result
    }), 200
