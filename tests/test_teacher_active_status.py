"""
Testes automatizados para ativação e desativação (soft-delete) de professores.
"""
import unittest
from datetime import date
from app import app
from models import db, Teacher, Resource, Booking


class TeacherActiveStatusTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Admin
        self.admin = Teacher.query.filter_by(registration='admin_test_active').first()
        if not self.admin:
            self.admin = Teacher(name='Admin Test Active', registration='admin_test_active', is_admin=True, is_active=True)
            db.session.add(self.admin)

        # Professor Ativo
        self.prof_active = Teacher.query.filter_by(registration='prof_test_active').first()
        if not self.prof_active:
            self.prof_active = Teacher(name='Prof Test Active', registration='prof_test_active', is_admin=False, is_active=True)
            db.session.add(self.prof_active)
        else:
            self.prof_active.is_active = True

        # Professor Inativo
        self.prof_inactive = Teacher.query.filter_by(registration='prof_test_inactive').first()
        if not self.prof_inactive:
            self.prof_inactive = Teacher(name='Prof Test Inactive', registration='prof_test_inactive', is_admin=False, is_active=False)
            db.session.add(self.prof_inactive)
        else:
            self.prof_inactive.is_active = False

        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self.app_context.pop()

    def test_inactive_teacher_login_blocked(self):
        """Valida que professor com is_active=False não consegue fazer login."""
        res = self.client.post('/login', data={'registration': 'prof_test_inactive'}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn('desativado', res.get_data(as_text=True).lower())

    def test_active_teacher_login_allowed(self):
        """Valida que professor com is_active=True faz login normalmente."""
        res = self.client.post('/login', data={'registration': 'prof_test_active'}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Prof Test Active', res.get_data(as_text=True))


    def test_admin_toggle_teacher_status(self):
        """Valida que o admin pode alternar o status de ativo/inativo do professor."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin.id)

        # Desativar professor ativo
        res = self.client.get(f'/admin/teacher/toggle/{self.prof_active.id}', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        db.session.refresh(self.prof_active)
        self.assertFalse(self.prof_active.is_active)
        self.assertIn('desativado', res.get_data(as_text=True).lower())

        # Reativar professor
        res_reactivate = self.client.get(f'/admin/teacher/toggle/{self.prof_active.id}', follow_redirects=True)
        self.assertEqual(res_reactivate.status_code, 200)
        db.session.refresh(self.prof_active)
        self.assertTrue(self.prof_active.is_active)
        self.assertIn('reativado', res_reactivate.get_data(as_text=True).lower())

    def test_admin_cannot_deactivate_self(self):
        """Valida que o admin não pode desativar seu próprio usuário."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin.id)

        res = self.client.get(f'/admin/teacher/toggle/{self.admin.id}', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        db.session.refresh(self.admin)
        self.assertTrue(self.admin.is_active)
        self.assertIn('Você não pode desativar seu próprio usuário', res.get_data(as_text=True))

    def test_edit_teacher_is_active_checkbox(self):
        """Valida que a edição do professor via modal altera o campo is_active."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin.id)

        # Edita desmarcando o checkbox is_active
        res = self.client.post(f'/admin/teacher/edit/{self.prof_active.id}', data={
            'name': 'Prof Test Active Renomeado',
            'registration': 'prof_test_active',
            # 'is_active' omitido -> desativa
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        db.session.refresh(self.prof_active)
        self.assertFalse(self.prof_active.is_active)
