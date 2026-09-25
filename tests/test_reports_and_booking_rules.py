"""
Testes automatizados para exportação de relatórios e regras de agendamento no passado.
"""
import unittest
from datetime import date, timedelta
from app import app
from models import db, Teacher, Resource, Booking

class ReportsAndBookingRulesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Admin e professor comum para testes
        self.admin = Teacher.query.filter_by(registration='7363').first()
        if not self.admin:
            self.admin = Teacher(name='Jardel Admin', registration='7363', is_admin=True)
            db.session.add(self.admin)
            db.session.commit()

        self.teacher = Teacher.query.filter_by(registration='9999').first()
        if not self.teacher:
            self.teacher = Teacher(name='Professor Normal', registration='9999', is_admin=False)
            db.session.add(self.teacher)
            db.session.commit()

        self.resource = Resource.query.first()
        if not self.resource:
            self.resource = Resource(name='Laboratório Teste', is_active=True, sort_order=0)
            db.session.add(self.resource)
            db.session.commit()

        self.yesterday = date.today() - timedelta(days=1)
        self.test_shift = 'matutino'
        self.test_slot = 'Aula Passada Teste'

        # Limpa dados de teste anteriores
        Booking.query.filter_by(
            resource_id=self.resource.id,
            date=self.yesterday,
            shift=self.test_shift,
            slot_name=self.test_slot
        ).delete()
        db.session.commit()

    def tearDown(self):
        Booking.query.filter_by(
            resource_id=self.resource.id,
            date=self.yesterday,
            shift=self.test_shift,
            slot_name=self.test_slot
        ).delete()
        Teacher.query.filter_by(registration='9999').delete()
        db.session.commit()
        self.app_context.pop()

    def test_retroactive_booking_blocked_for_teacher(self):
        """Valida que professores comuns NÃO conseguem agendar datas passadas."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.teacher.id)
            sess['_fresh'] = True

        res = self.client.post('/agenda/book', data={
            'resource_id': str(self.resource.id),
            'date': self.yesterday.strftime('%Y-%m-%d'),
            'slot_name': self.test_slot,
            'shift': self.test_shift,
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn('datas passadas', res.get_data(as_text=True))

        # Garante que nenhum agendamento foi salvo
        booking = Booking.query.filter_by(
            resource_id=self.resource.id,
            date=self.yesterday,
            shift=self.test_shift,
            slot_name=self.test_slot
        ).first()
        self.assertIsNone(booking)

    def test_retroactive_booking_allowed_for_admin(self):
        """Valida que administradores têm permissão para agendamentos retroativos."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin.id)
            sess['_fresh'] = True

        res = self.client.post('/agenda/book', data={
            'resource_id': str(self.resource.id),
            'date': self.yesterday.strftime('%Y-%m-%d'),
            'slot_name': self.test_slot,
            'shift': self.test_shift,
            'teacher_id': str(self.admin.id)
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn('agendado com sucesso', res.get_data(as_text=True))

        # Garante que o agendamento foi salvo
        booking = Booking.query.filter_by(
            resource_id=self.resource.id,
            date=self.yesterday,
            shift=self.test_shift,
            slot_name=self.test_slot
        ).first()
        self.assertIsNotNone(booking)

    def test_export_report_csv(self):
        """Valida a rota /admin/reports/export gerando arquivo CSV para download."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin.id)
            sess['_fresh'] = True

        # Cria um agendamento para garantir dados no relatório
        booking = Booking(
            resource_id=self.resource.id,
            teacher_id=self.admin.id,
            teacher_name=self.admin.name,
            date=self.yesterday,
            shift=self.test_shift,
            slot_name=self.test_slot,
            status='booked'
        )
        db.session.add(booking)
        db.session.commit()

        start_str = (self.yesterday - timedelta(days=2)).strftime('%d/%m/%Y')
        end_str = (self.yesterday + timedelta(days=2)).strftime('%d/%m/%Y')

        res = self.client.get(f'/admin/reports/export?resource_id={self.resource.id}&start_date={start_str}&end_date={end_str}')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content_type, 'text/csv; charset=utf-8')
        self.assertIn('attachment;', res.headers.get('Content-Disposition', ''))
        
        # O arquivo deve conter separador ; e os dados do professor
        csv_text = res.get_data().decode('utf-8-sig')
        self.assertIn('RELATÓRIO DE UTILIZAÇÃO DE RECURSOS', csv_text)
        self.assertIn('Professor;Quantidade de Usos', csv_text)
        self.assertIn(self.admin.name, csv_text)

if __name__ == '__main__':
    unittest.main()
