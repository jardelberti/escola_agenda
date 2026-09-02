"""
Testes automatizados de integridade e concorrência de agendamentos.
"""
import unittest
from datetime import date
from sqlalchemy.exc import IntegrityError
from app import app
from models import db, Teacher, Resource, Booking

class BookingIntegrityTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Garante a existência de um professor e um recurso para o teste
        self.teacher = Teacher.query.filter_by(registration='7363').first()
        if not self.teacher:
            self.teacher = Teacher(name='Professor Teste', registration='7363', is_admin=True)
            db.session.add(self.teacher)
            db.session.commit()

        self.resource = Resource.query.first()
        if not self.resource:
            self.resource = Resource(name='Recurso Teste', is_active=True, sort_order=0)
            db.session.add(self.resource)
            db.session.commit()

        self.test_date = date(2028, 12, 1)
        self.test_shift = 'matutino'
        self.test_slot = 'Aula 1'

        # Limpa qualquer agendamento prévio de teste
        Booking.query.filter_by(
            resource_id=self.resource.id,
            date=self.test_date,
            shift=self.test_shift,
            slot_name=self.test_slot
        ).delete()
        db.session.commit()

    def tearDown(self):
        # Limpa registros criados durante os testes
        Booking.query.filter_by(
            resource_id=self.resource.id,
            date=self.test_date,
            shift=self.test_shift,
            slot_name=self.test_slot
        ).delete()
        db.session.commit()
        self.app_context.pop()

    def test_database_rejects_duplicate_booking(self):
        """Valida que o banco de dados rejeita duplicidades via UniqueConstraint."""
        b1 = Booking(
            resource_id=self.resource.id,
            teacher_id=self.teacher.id,
            teacher_name=self.teacher.name,
            date=self.test_date,
            shift=self.test_shift,
            slot_name=self.test_slot,
            status='booked'
        )
        db.session.add(b1)
        db.session.commit()

        # Segunda tentativa de agendamento no mesmo slot deve disparar IntegrityError
        b2 = Booking(
            resource_id=self.resource.id,
            teacher_id=self.teacher.id,
            teacher_name=self.teacher.name,
            date=self.test_date,
            shift=self.test_shift,
            slot_name=self.test_slot,
            status='booked'
        )
        db.session.add(b2)
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_book_slot_handles_duplicate_gracefully(self):
        """Valida que a rota /agenda/book trata duplicidade sem erro 500."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.teacher.id)
            sess['_fresh'] = True

        # Primeiro agendamento via rota
        res1 = self.client.post('/agenda/book', data={
            'resource_id': str(self.resource.id),
            'date': self.test_date.strftime('%Y-%m-%d'),
            'slot_name': self.test_slot,
            'shift': self.test_shift,
        }, follow_redirects=True)
        self.assertEqual(res1.status_code, 200)

        # Segundo agendamento no mesmo slot (simulando concorrência)
        res2 = self.client.post('/agenda/book', data={
            'resource_id': str(self.resource.id),
            'date': self.test_date.strftime('%Y-%m-%d'),
            'slot_name': self.test_slot,
            'shift': self.test_shift,
        }, follow_redirects=True)
        self.assertEqual(res2.status_code, 200)

        # Verifica se apenas 1 registro existe no banco
        count = Booking.query.filter_by(
            resource_id=self.resource.id,
            date=self.test_date,
            shift=self.test_shift,
            slot_name=self.test_slot
        ).count()
        self.assertEqual(count, 1)

if __name__ == '__main__':
    unittest.main()
