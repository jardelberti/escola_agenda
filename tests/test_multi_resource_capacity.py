from tests.auth_helpers import authenticated_id
import time
"""
Testes automatizados para recursos com múltiplas unidades (Capacidade > 1).
"""
import unittest
from datetime import date
from app import app
from models import db, Teacher, Resource, ScheduleTemplate, Booking

class MultiResourceCapacityTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Garante a existência de professores de teste
        self.teacher1 = Teacher.query.filter_by(registration='1001').first()
        if not self.teacher1:
            self.teacher1 = Teacher(name='Prof Alpha', registration='1001', is_admin=False)
            db.session.add(self.teacher1)

        self.teacher2 = Teacher.query.filter_by(registration='1002').first()
        if not self.teacher2:
            self.teacher2 = Teacher(name='Prof Beta', registration='1002', is_admin=False)
            db.session.add(self.teacher2)

        self.teacher3 = Teacher.query.filter_by(registration='1003').first()
        if not self.teacher3:
            self.teacher3 = Teacher(name='Prof Gamma', registration='1003', is_admin=False)
            db.session.add(self.teacher3)

        self.admin = Teacher.query.filter_by(registration='7363').first()
        if not self.admin:
            self.admin = Teacher(name='Admin Master', registration='7363', is_admin=True)
            db.session.add(self.admin)
        db.session.commit()

        # Cria ou obtém recurso com quantidade = 2 (Projetores)
        self.resource = Resource.query.filter_by(name='Projetores Teste').first()
        if not self.resource:
            self.resource = Resource(
                name='Projetores Teste',
                description='2 Projetores disponíveis',
                icon='bi-projector-fill',
                is_active=True,
                quantity=2
            )
            db.session.add(self.resource)
            db.session.commit()

            template = ScheduleTemplate(
                resource_id=self.resource.id,
                shift='matutino',
                slots=[
                    {'name': '1º Horário', 'type': 'aula'},
                    {'name': '2º Horário', 'type': 'aula'}
                ]
            )
            db.session.add(template)
            db.session.commit()

        self.test_date = date(2028, 11, 15)
        self.test_shift = 'matutino'
        self.test_slot = '1º Horário'

        # Limpa bookings de testes
        Booking.query.filter_by(resource_id=self.resource.id, date=self.test_date).delete()
        db.session.commit()

    def tearDown(self):
        Booking.query.filter_by(resource_id=self.resource.id, date=self.test_date).delete()
        db.session.commit()
        self.app_context.pop()

    def login_as(self, client, teacher):
        from flask import g
        if hasattr(g, '_login_user'):
            del g._login_user
        with client.session_transaction() as sess:
            sess['_user_id'] = authenticated_id(teacher)
            sess['admin_verified_at'] = time.time()
            sess['_fresh'] = True

    def test_two_different_teachers_can_book_same_slot(self):
        """Valida que dois professores diferentes conseguem agendar o mesmo horário quando quantity=2."""
        client1 = self.app.test_client()
        self.login_as(client1, self.teacher1)

        res1 = client1.post('/agenda/book', data={
            'resource_id': str(self.resource.id),
            'date': self.test_date.strftime('%Y-%m-%d'),
            'slot_name': self.test_slot,
            'shift': self.test_shift,
        }, follow_redirects=True)
        self.assertEqual(res1.status_code, 200)
        self.assertIn('agendado com sucesso', res1.get_data(as_text=True))

        client2 = self.app.test_client()
        self.login_as(client2, self.teacher2)

        res2 = client2.post('/agenda/book', data={
            'resource_id': str(self.resource.id),
            'date': self.test_date.strftime('%Y-%m-%d'),
            'slot_name': self.test_slot,
            'shift': self.test_shift,
        }, follow_redirects=True)
        self.assertEqual(res2.status_code, 200)
        self.assertIn('agendado com sucesso', res2.get_data(as_text=True))

        # Verifica se ambos os registros existem no banco
        bookings = Booking.query.filter_by(
            resource_id=self.resource.id,
            date=self.test_date,
            shift=self.test_shift,
            slot_name=self.test_slot
        ).all()
        self.assertEqual(len(bookings), 2)
        teacher_ids = {b.teacher_id for b in bookings}
        self.assertEqual(teacher_ids, {self.teacher1.id, self.teacher2.id})

    def test_third_teacher_blocked_when_capacity_reached(self):
        """Valida que um terceiro professor é bloqueado quando a capacidade (2) for atingida."""
        # Cria 2 bookings
        db.session.add(Booking(resource_id=self.resource.id, teacher_id=self.teacher1.id, teacher_name=self.teacher1.name, date=self.test_date, shift=self.test_shift, slot_name=self.test_slot))
        db.session.add(Booking(resource_id=self.resource.id, teacher_id=self.teacher2.id, teacher_name=self.teacher2.name, date=self.test_date, shift=self.test_shift, slot_name=self.test_slot))
        db.session.commit()

        # Tentativa pelo Teacher 3
        client3 = self.app.test_client()
        self.login_as(client3, self.teacher3)

        res = client3.post('/agenda/book', data={
            'resource_id': str(self.resource.id),
            'date': self.test_date.strftime('%Y-%m-%d'),
            'slot_name': self.test_slot,
            'shift': self.test_shift,
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn('já foram agendados', res.get_data(as_text=True))
        
        # Garante que continua tendo apenas 2 agendamentos
        count = Booking.query.filter_by(resource_id=self.resource.id, date=self.test_date, slot_name=self.test_slot).count()
        self.assertEqual(count, 2)

    def test_same_teacher_cannot_book_twice_in_same_slot(self):
        """Valida que o mesmo professor não pode reservar 2 unidades no mesmo horário."""
        db.session.add(Booking(resource_id=self.resource.id, teacher_id=self.teacher1.id, teacher_name=self.teacher1.name, date=self.test_date, shift=self.test_shift, slot_name=self.test_slot))
        db.session.commit()

        # Segunda tentativa pelo mesmo Teacher 1
        client1 = self.app.test_client()
        self.login_as(client1, self.teacher1)

        res = client1.post('/agenda/book', data={
            'resource_id': str(self.resource.id),
            'date': self.test_date.strftime('%Y-%m-%d'),
            'slot_name': self.test_slot,
            'shift': self.test_shift,
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn('já possui um agendamento', res.get_data(as_text=True))

        count = Booking.query.filter_by(resource_id=self.resource.id, date=self.test_date, slot_name=self.test_slot).count()
        self.assertEqual(count, 1)

    def test_agenda_api_returns_correct_capacity_data(self):
        """Valida que a API JSON retorna capacity=2, available_count e lista de bookings."""
        db.session.add(Booking(resource_id=self.resource.id, teacher_id=self.teacher1.id, teacher_name=self.teacher1.name, date=self.test_date, shift=self.test_shift, slot_name=self.test_slot))
        db.session.commit()

        client2 = self.app.test_client()
        self.login_as(client2, self.teacher2)

        res = client2.get(f'/api/agenda/{self.resource.id}/{self.test_date.strftime("%Y-%m-%d")}')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        slots = data.get('matutino', [])
        slot1 = next(s for s in slots if s['name'] == self.test_slot)
        self.assertEqual(slot1['capacity'], 2)
        self.assertEqual(slot1['booked_count'], 1)
        self.assertEqual(slot1['available_count'], 1)
        self.assertFalse(slot1['already_booked_by_me'])
        self.assertEqual(len(slot1['bookings']), 1)
        self.assertEqual(slot1['bookings'][0]['teacher_name'], self.teacher1.name)

    def test_admin_can_close_slot_partially_and_blocks_overflow(self):
        """Valida que o admin fecha 1 unidade por vez e que ao lotar bloqueia."""
        # 1 reserva feita
        db.session.add(Booking(resource_id=self.resource.id, teacher_id=self.teacher1.id, teacher_name=self.teacher1.name, date=self.test_date, shift=self.test_shift, slot_name=self.test_slot))
        db.session.commit()

        # Admin fecha a segunda unidade
        admin_client = self.app.test_client()
        self.login_as(admin_client, self.admin)

        res_close = admin_client.post('/agenda/close', data={
            'resource_id': str(self.resource.id),
            'date': self.test_date.strftime('%Y-%m-%d'),
            'slot_name': self.test_slot,
            'shift': self.test_shift,
        }, follow_redirects=True)
        self.assertEqual(res_close.status_code, 200)
        self.assertIn('fechada com sucesso', res_close.get_data(as_text=True))

        # Agora a capacidade está cheia (1 booked + 1 closed = 2)
        # Teacher 2 tenta agendar e é bloqueado
        client2 = self.app.test_client()
        self.login_as(client2, self.teacher2)

        res_book = client2.post('/agenda/book', data={
            'resource_id': str(self.resource.id),
            'date': self.test_date.strftime('%Y-%m-%d'),
            'slot_name': self.test_slot,
            'shift': self.test_shift,
        }, follow_redirects=True)
        self.assertIn('já foram agendados', res_book.get_data(as_text=True))

    def test_deleting_booking_frees_spot(self):
        """Valida que ao excluir um agendamento a vaga é liberada novamente."""
        b1 = Booking(resource_id=self.resource.id, teacher_id=self.teacher1.id, teacher_name=self.teacher1.name, date=self.test_date, shift=self.test_shift, slot_name=self.test_slot)
        b2 = Booking(resource_id=self.resource.id, teacher_id=self.teacher2.id, teacher_name=self.teacher2.name, date=self.test_date, shift=self.test_shift, slot_name=self.test_slot)
        db.session.add_all([b1, b2])
        db.session.commit()

        # Teacher 1 exclui seu agendamento
        client1 = self.app.test_client()
        self.login_as(client1, self.teacher1)
        res_del = client1.post(f'/agenda/booking/delete/{b1.id}', data={
            'date': self.test_date.strftime('%Y-%m-%d'),
            'shift': self.test_shift
        }, follow_redirects=True)
        self.assertEqual(res_del.status_code, 200)

        # Teacher 3 agora consegue agendar a vaga liberada
        client3 = self.app.test_client()
        self.login_as(client3, self.teacher3)
        res_book = client3.post('/agenda/book', data={
            'resource_id': str(self.resource.id),
            'date': self.test_date.strftime('%Y-%m-%d'),
            'slot_name': self.test_slot,
            'shift': self.test_shift,
        }, follow_redirects=True)
        self.assertEqual(res_book.status_code, 200)
        self.assertIn('agendado com sucesso', res_book.get_data(as_text=True))

if __name__ == '__main__':
    unittest.main()
