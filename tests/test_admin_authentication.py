"""Security regressions. Run with DATABASE_URL pointing to an isolated test database."""
import time
import unittest
from datetime import datetime, timezone
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from flask_login.utils import encode_cookie
from sqlalchemy import create_engine, inspect, text
from app import app
from auth_schema import upgrade_admin_auth, secure_restored_admin_accounts
from models import db, Teacher, AdminAccessToken, AuthAttempt
from security import digest, issue_access_token
from tests.auth_helpers import TEST_PASSWORD

NEW_PASSWORD = 'Outra frase longa exclusiva de testes!'


class AdminAuthenticationTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = app.test_client()
        suffix = uuid4().hex[:10]
        self.registration = 'auth-admin-' + suffix
        self.prof_registration = 'auth-prof-' + suffix
        self.tokens = []
        with app.app_context():
            admin = Teacher(name='Administrador de teste', registration=self.registration, is_admin=True)
            admin.set_password(TEST_PASSWORD)
            prof = Teacher(name='Professor de teste', registration=self.prof_registration, is_admin=False)
            pending = Teacher(name='Administrador pendente', registration='pending-' + suffix, is_admin=True)
            db.session.add_all([admin, prof, pending])
            db.session.commit()
            self.admin_id, self.prof_id, self.pending_id = admin.id, prof.id, pending.id
            self.pending_registration = pending.registration
            self.version = admin.auth_version
            db.session.execute(db.delete(AuthAttempt).where(AuthAttempt.key == digest('setup-source:192.0.2.123')))
            db.session.commit()

    def tearDown(self):
        with app.app_context():
            ids = [self.admin_id, self.prof_id, self.pending_id]
            db.session.execute(db.delete(AdminAccessToken).where(AdminAccessToken.teacher_id.in_(ids)))
            db.session.execute(db.delete(Teacher).where(Teacher.id.in_(ids)))
            labels = ['admin:' + self.registration, 'admin:' + self.pending_registration,
                      'setup-source:192.0.2.123'] + ['setup:' + digest(t) for t in self.tokens]
            db.session.execute(db.delete(AuthAttempt).where(AuthAttempt.key.in_([digest(k) for k in labels])))
            db.session.commit()

    def login(self, client=None, password=TEST_PASSWORD, remember=False, registration=None):
        return (client or self.client).post('/login', data={
            'registration': registration or self.registration, 'password': password,
            'admin_step': '1', 'remember': '1' if remember else '0',
        })

    def token(self, teacher_id=None):
        with app.app_context():
            token = issue_access_token(db.session.get(Teacher, teacher_id or self.admin_id))
        self.tokens.append(token)
        return token

    def setup(self, token, password=NEW_PASSWORD, **kwargs):
        return self.client.post('/admin/definir-senha', data={
            'access_token': token, 'password': password, 'password_confirm': password,
        }, environ_overrides={'REMOTE_ADDR': '192.0.2.123'}, **kwargs)

    def expire_confirmation(self, client=None):
        with (client or self.client).session_transaction() as session:
            session['admin_verified_at'] = time.time() - 301

    def test_registration_only_and_legacy_admin_session_cannot_enter(self):
        response = self.client.post('/login', data={'registration': self.registration})
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="password"', response.text)
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        with self.client.session_transaction() as session:
            session['_user_id'] = str(self.admin_id)
            session['_fresh'] = True
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        self.assertEqual(self.client.get('/home').status_code, 302)

    def test_password_login_and_secure_seven_day_remember_cookie(self):
        response = self.login(remember=True)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/admin/'))
        cookie = self.client.get_cookie('remember_token')
        self.assertIsNotNone(cookie)
        self.assertTrue(cookie.secure)
        self.assertTrue(cookie.http_only)
        self.assertEqual(cookie.same_site, 'Lax')
        remaining = (cookie.expires - datetime.now(timezone.utc)).total_seconds()
        self.assertAlmostEqual(remaining, 7 * 86400, delta=5)
        self.client.delete_cookie('session')
        self.assertEqual(self.client.get('/admin/').status_code, 200)
        with self.client.session_transaction() as session:
            self.assertFalse(session['_fresh'])
            self.assertNotIn('admin_verified_at', session)

    def test_no_remember_option_keeps_browser_session_only(self):
        self.login()
        self.assertIsNone(self.client.get_cookie('remember_token'))
        self.assertIsNone(self.client.get_cookie('session').expires)
        self.client.delete_cookie('session')
        self.assertEqual(self.client.get('/admin/').status_code, 302)

    def test_server_rejects_expired_remember_token(self):
        with app.app_context():
            cookie = encode_cookie(f'{self.admin_id}:{self.version}:{int(time.time()) - 1}')
        self.client.set_cookie('remember_token', cookie)
        self.assertEqual(self.client.get('/admin/').status_code, 302)

    def test_normal_logout_removes_remember_cookie(self):
        self.login(remember=True)
        self.client.get('/logout')
        self.assertIsNone(self.client.get_cookie('remember_token'))
        self.assertEqual(self.client.get('/admin/').status_code, 302)

    def test_teachers_keep_registration_login_and_cannot_use_admin_security(self):
        response = self.client.post('/login', data={'registration': self.prof_registration})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get('/home').status_code, 200)
        self.assertEqual(self.client.get('/admin/security').status_code, 302)
        with app.app_context():
            db.session.get(Teacher, self.prof_id).is_active = False
            db.session.commit()
        self.assertEqual(self.client.get('/home').status_code, 302)

    def test_attempt_limit_shared_between_clients_and_expires(self):
        other = app.test_client()
        for index in range(5):
            self.assertEqual(self.login(client=other if index % 2 else self.client, password='incorrect').status_code, 200)
        response = self.login(password=TEST_PASSWORD)
        self.assertIn('Muitas tentativas', response.text)
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        with app.app_context():
            db.session.get(AuthAttempt, digest('admin:' + self.registration)).window_start -= 901
            db.session.commit()
        self.assertEqual(self.login().status_code, 302)

    def test_setup_requires_private_single_use_token_and_revokes_old_sessions(self):
        self.login(remember=True)
        old_cookie = self.client.get_cookie('remember_token').value
        self.assertEqual(self.setup('invalid-token').status_code, 400)
        token = self.token()
        with app.app_context():
            stored = db.session.get(AdminAccessToken, digest(token))
            self.assertNotEqual(stored.token_hash, token)
        response = self.setup(token)
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.client.get_cookie('remember_token'))
        self.assertEqual(self.setup(token).status_code, 400)
        copied_cookie_client = app.test_client()
        copied_cookie_client.set_cookie('remember_token', old_cookie)
        self.assertEqual(copied_cookie_client.get('/admin/').status_code, 302)
        self.assertEqual(self.login(password=NEW_PASSWORD).status_code, 302)
        with app.app_context():
            admin = db.session.get(Teacher, self.admin_id)
            self.assertTrue(admin.password_hash.startswith('scrypt:'))
            self.assertNotIn(NEW_PASSWORD, admin.password_hash)
            self.assertNotEqual(admin.auth_version, self.version)

    def test_expired_replaced_and_inactive_account_tokens_are_rejected(self):
        old = self.token()
        current = self.token()
        self.assertEqual(self.setup(old).status_code, 400)
        with app.app_context():
            db.session.get(AdminAccessToken, digest(current)).expires_at = int(time.time()) - 1
            db.session.commit()
        self.assertEqual(self.setup(current).status_code, 400)
        current = self.token()
        with app.app_context():
            db.session.get(Teacher, self.admin_id).is_active = False
            db.session.commit()
        self.assertEqual(self.setup(current).status_code, 400)

    def test_pending_admin_cannot_choose_password_from_registration(self):
        self.assertEqual(self.login(registration=self.pending_registration).status_code, 200)
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        token = self.token(self.pending_id)
        self.assertEqual(self.setup(token).status_code, 302)
        self.assertEqual(self.login(registration=self.pending_registration, password=NEW_PASSWORD).status_code, 302)

    def test_password_policy_and_csrf_reject_bad_setup_without_consuming_token(self):
        token = self.token()
        self.assertEqual(self.setup(token, password='short').status_code, 400)
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            self.assertEqual(self.setup(token).status_code, 400)
            with app.app_context():
                self.assertIsNotNone(db.session.get(AdminAccessToken, digest(token)))
        finally:
            app.config['WTF_CSRF_ENABLED'] = False

    def test_logout_all_and_change_password_revoke_other_devices(self):
        other = app.test_client()
        self.login(remember=True)
        self.login(client=other, remember=True)
        response = self.client.post('/admin/security', data={'action': 'logout_all', 'admin_password': TEST_PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(other.get('/admin/').status_code, 302)
        self.assertIsNone(self.client.get_cookie('remember_token'))
        self.login()
        self.login(client=other)
        token = self.token()
        response = self.client.post('/admin/security', data={
            'action': 'change_password', 'admin_password': TEST_PASSWORD,
            'password': NEW_PASSWORD, 'password_confirm': NEW_PASSWORD,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(other.get('/admin/').status_code, 302)
        self.assertEqual(self.setup(token).status_code, 400)
        self.assertEqual(self.login(password=TEST_PASSWORD).status_code, 200)
        self.assertEqual(self.login(password=NEW_PASSWORD).status_code, 302)

    def test_sensitive_restore_is_blocked_before_file_save_or_task_dispatch(self):
        self.login()
        self.expire_confirmation()
        with TemporaryDirectory() as folder, patch('routes.admin.BACKUP_FOLDER', folder), patch('routes.admin.restore_task_bg.delay') as dispatch:
            response = self.client.post('/admin/restore', data={'backup_file': (BytesIO(b'test'), 'sample.dump')})
            self.assertEqual(response.status_code, 302)
            dispatch.assert_not_called()
            self.client.post('/admin/restore', data={
                'backup_file': (BytesIO(b'test'), 'sample.dump'), 'admin_password': TEST_PASSWORD,
            })
            dispatch.assert_called_once()

    def test_promotion_requires_confirmation_and_rejects_old_teacher_session(self):
        prof_client = app.test_client()
        prof_client.post('/login', data={'registration': self.prof_registration})
        self.login()
        self.expire_confirmation()
        data = {'name': 'Professor promovido', 'registration': self.prof_registration, 'is_active': 'on', 'is_admin': 'on'}
        self.client.post(f'/admin/teacher/edit/{self.prof_id}', data=data)
        with app.app_context():
            self.assertFalse(db.session.get(Teacher, self.prof_id).is_admin)
        data['admin_password'] = TEST_PASSWORD
        self.client.post(f'/admin/teacher/edit/{self.prof_id}', data=data)
        with app.app_context():
            self.assertTrue(db.session.get(Teacher, self.prof_id).is_admin)
            self.assertIsNone(db.session.get(Teacher, self.prof_id).password_hash)
        self.assertEqual(prof_client.get('/admin/').status_code, 302)

    def test_recovery_link_and_password_change_require_confirmation(self):
        self.login()
        self.expire_confirmation()
        response = self.client.post(f'/admin/teacher/access-link/{self.pending_id}')
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertEqual(AdminAccessToken.query.filter_by(teacher_id=self.pending_id).count(), 0)
        response = self.client.post(f'/admin/teacher/access-link/{self.pending_id}', data={'admin_password': TEST_PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.client.post('/admin/security', data={'action': 'logout_all', 'admin_password': 'wrong'})
        self.assertEqual(self.client.get('/admin/').status_code, 200)

    def test_auth_pages_do_not_load_third_party_scripts_or_cache_secrets(self):
        response = self.client.get('/admin/definir-senha')
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
        self.assertIn("script-src 'self'", response.headers['Content-Security-Policy'])
        self.assertNotIn('cdn.', response.text)
        self.assertNotIn('fonts.googleapis', response.text)


class AdminSchemaMigrationTests(unittest.TestCase):
    def test_post_restore_recreates_security_fields_and_revokes_historical_access(self):
        engine = create_engine('sqlite://')
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE teacher (id INTEGER PRIMARY KEY, is_admin BOOLEAN)'))
            connection.execute(text('INSERT INTO teacher VALUES (1, true)'))
            secure_restored_admin_accounts(connection)
            version = connection.execute(text('SELECT auth_version FROM teacher WHERE id=1')).scalar_one()
            self.assertEqual(len(version), 64)
            self.assertIsNone(connection.execute(text('SELECT password_hash FROM teacher WHERE id=1')).scalar_one())
            connection.execute(text("INSERT INTO admin_access_token VALUES ('historical-token',1,9999999999)"))
            secure_restored_admin_accounts(connection)
            self.assertNotEqual(version, connection.execute(text('SELECT auth_version FROM teacher WHERE id=1')).scalar_one())
            self.assertEqual(connection.execute(text('SELECT count(*) FROM admin_access_token')).scalar_one(), 0)
            self.assertFalse(inspect(connection).get_foreign_keys('admin_access_token'))
        engine.dispose()

    def test_additive_upgrade_preserves_existing_teacher_and_is_idempotent(self):
        engine = create_engine('sqlite://')
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE teacher (id INTEGER PRIMARY KEY, name VARCHAR(150))'))
            connection.execute(text("INSERT INTO teacher (id,name) VALUES (1,'Registro preservado')"))
            upgrade_admin_auth(connection)
            upgrade_admin_auth(connection)
            self.assertEqual(connection.execute(text('SELECT name FROM teacher WHERE id=1')).scalar_one(), 'Registro preservado')
            self.assertIsNone(connection.execute(text('SELECT password_hash FROM teacher WHERE id=1')).scalar_one())
            self.assertTrue({'password_hash', 'auth_version'} <= {c['name'] for c in inspect(connection).get_columns('teacher')})
            self.assertTrue({'admin_access_token', 'auth_attempt'} <= set(inspect(connection).get_table_names()))
        engine.dispose()
