from tests.auth_helpers import authenticated_id
import time
"""
Testes automatizados para WhatsApp de professores e endpoints de integração (n8n / WhatsApp bot).
"""
import os
import unittest
from datetime import date, timedelta
from app import app
from models import db, Teacher, Resource, Booking
from utils import sanitize_phone, format_phone
from routes.integrations import DEFAULT_API_KEY


class IntegrationsAndWhatsAppTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Usuários de teste
        self.admin = Teacher.query.filter_by(registration='admin_test_integration').first()
        if not self.admin:
            self.admin = Teacher(name='Admin Teste', registration='admin_test_integration', is_admin=True, whatsapp='5547999990001')
            db.session.add(self.admin)
        else:
            self.admin.whatsapp = '5547999990001'

        self.prof = Teacher.query.filter_by(registration='prof_test_integration').first()
        if not self.prof:
            self.prof = Teacher(name='Prof Teste', registration='prof_test_integration', is_admin=False, whatsapp='5547988887777')
            db.session.add(self.prof)
        else:
            self.prof.whatsapp = '5547988887777'

        # Recurso de teste
        self.resource = Resource.query.filter_by(name='Laboratório Teste').first()
        if not self.resource:
            self.resource = Resource(name='Laboratório Teste', is_active=True, quantity=1, icon='bi-laptop')
            db.session.add(self.resource)

        db.session.commit()


    def tearDown(self):
        # Limpar agendamentos de teste
        Booking.query.filter_by(resource_id=self.resource.id).delete()
        db.session.commit()
        self.app_context.pop()

    def test_phone_sanitization_and_formatting(self):
        """Valida que números de telefone em vários formatos são normalizados com DDI 55."""
        self.assertEqual(sanitize_phone('(47) 99123-4567'), '5547991234567')
        self.assertEqual(sanitize_phone('47991234567'), '5547991234567')
        self.assertEqual(sanitize_phone('+55 (47) 99123-4567'), '5547991234567')
        self.assertEqual(sanitize_phone('5547991234567'), '5547991234567')
        self.assertEqual(sanitize_phone('(47) 3322-1100'), '554733221100')
        self.assertIsNone(sanitize_phone(''))
        self.assertIsNone(sanitize_phone(None))

        # Formatação para UI
        self.assertEqual(format_phone('5547991234567'), '(47) 99123-4567')
        self.assertEqual(format_phone('554733221100'), '(47) 3322-1100')
        self.assertEqual(format_phone(''), '')

    def test_admin_create_and_edit_teacher_whatsapp(self):
        """Valida que o admin consegue cadastrar e editar o WhatsApp de um professor."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = authenticated_id(self.admin)
            sess['admin_verified_at'] = time.time()

        # Cadastro de novo professor com WhatsApp
        res = self.client.post('/admin/teachers', data={
            'name': 'Professor Novo WhatsApp',
            'registration': 'prof_novo_whats_123',
            'whatsapp': '(47) 98765-4321'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        created = Teacher.query.filter_by(registration='prof_novo_whats_123').first()
        self.assertIsNotNone(created)
        self.assertEqual(created.whatsapp, '5547987654321')

        # Edição do WhatsApp
        res_edit = self.client.post(f'/admin/teacher/edit/{created.id}', data={
            'name': 'Professor Novo WhatsApp Alterado',
            'registration': 'prof_novo_whats_123',
            'whatsapp': '(48) 91111-2222'
        }, follow_redirects=True)
        self.assertEqual(res_edit.status_code, 200)

        db.session.refresh(created)
        self.assertEqual(created.whatsapp, '5548911112222')
        self.assertEqual(created.name, 'Professor Novo WhatsApp Alterado')

        # Limpeza
        db.session.delete(created)
        db.session.commit()

    def test_teacher_update_own_whatsapp(self):
        """Valida que o professor pode atualizar seu próprio número em 'Meus Agendamentos'."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = authenticated_id(self.prof)
            sess['admin_verified_at'] = time.time()

        res = self.client.post('/my-profile/whatsapp', data={
            'whatsapp': '(11) 99876-5432'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        db.session.refresh(self.prof)
        self.assertEqual(self.prof.whatsapp, '5511998765432')

    def test_integration_daily_summary_unauthorized(self):
        """Valida que acesso sem token válido retorna 401 Unauthorized."""
        res = self.client.get('/api/integrations/daily-summary')
        self.assertEqual(res.status_code, 401)
        data = res.get_json()
        self.assertEqual(data.get('status'), 'error')

        res_bad_token = self.client.get('/api/integrations/daily-summary?token=chave_invalida')
        self.assertEqual(res_bad_token.status_code, 401)

    def test_integration_daily_summary_success_with_bookings(self):
        """Valida o retorno do resumo diário estruturado para WhatsApp com agendamentos."""
        today = date.today()

        # Cria agendamento para hoje
        booking = Booking(
            resource_id=self.resource.id,
            teacher_id=self.prof.id,
            teacher_name=self.prof.name,
            date=today,
            shift='matutino',
            slot_name='1ª Aula',
            status='booked'
        )
        db.session.add(booking)
        db.session.commit()

        # Requisição via query param ?token=
        res = self.client.get(f'/api/integrations/daily-summary?token={DEFAULT_API_KEY}&date={today.strftime("%Y-%m-%d")}')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        self.assertEqual(data.get('status'), 'success')
        self.assertEqual(data.get('date'), today.strftime('%Y-%m-%d'))
        self.assertGreaterEqual(data.get('total_bookings'), 1)

        # Mensagem geral para o grupo
        summary_text = data.get('summary_text', '')
        self.assertIn('Agenda Escolar', summary_text)
        self.assertIn(self.resource.name, summary_text)
        self.assertIn(self.prof.name, summary_text)

        # Mensagem individual por professor
        teachers_summaries = data.get('teachers_summaries', [])
        self.assertGreaterEqual(len(teachers_summaries), 1)
        prof_entry = next((t for t in teachers_summaries if t['teacher_id'] == self.prof.id), None)
        self.assertIsNotNone(prof_entry)
        self.assertEqual(prof_entry['whatsapp'], '5547988887777')
        self.assertIn('Olá Prof(a).', prof_entry['message'])
        self.assertIn(self.resource.name, prof_entry['message'])

    def test_integration_daily_summary_empty_day(self):
        """Valida o resumo quando não há agendamentos no dia."""
        future_date = date.today() + timedelta(days=200)
        res = self.client.get(
            f'/api/integrations/daily-summary?date={future_date.strftime("%Y-%m-%d")}',
            headers={'X-API-Key': DEFAULT_API_KEY}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('total_bookings'), 0)
        self.assertEqual(len(data.get('teachers_summaries')), 0)
        self.assertIn('Nenhum recurso agendado', data.get('summary_text'))

    def test_integration_teachers_list(self):
        """Valida o endpoint /api/integrations/teachers."""
        res = self.client.get('/api/integrations/teachers', headers={'Authorization': f'Bearer {DEFAULT_API_KEY}'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('status'), 'success')
        self.assertGreaterEqual(data.get('count'), 2)
