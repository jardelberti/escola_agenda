"""Role landing and footer selection must use current Blueprint endpoints."""
import unittest
from html.parser import HTMLParser
from uuid import uuid4
from app import app
from models import db, Teacher, Resource
from tests.auth_helpers import authenticated_id


class FooterLinks(HTMLParser):
    def __init__(self):
        super().__init__(); self.in_footer = False; self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'footer': self.in_footer = True
        if tag == 'a' and self.in_footer: self.links.append(dict(attrs))

    def handle_endtag(self, tag):
        if tag == 'footer': self.in_footer = False


class LandingNavigationTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = app.test_client()
        with app.app_context():
            suffix = uuid4().hex[:10]
            admin = Teacher(name='Admin fictício', registration='nav-admin-' + suffix, is_admin=True)
            teacher = Teacher(name='Professor fictício', registration='nav-prof-' + suffix)
            resource = Resource(name='Recurso navegação ' + suffix)
            db.session.add_all([admin, teacher, resource]); db.session.commit()
            self.ids = [admin.id, teacher.id]
            self.resource_id = resource.id
            self.admin_login = authenticated_id(admin)
            self.teacher_login = teacher.get_id()

    def tearDown(self):
        with app.app_context():
            db.session.execute(db.delete(Resource).where(Resource.id == self.resource_id))
            db.session.execute(db.delete(Teacher).where(Teacher.id.in_(self.ids)))
            db.session.commit()

    def login(self, admin):
        with self.client.session_transaction() as session:
            session.clear(); session['_user_id'] = self.admin_login if admin else self.teacher_login
            session['_fresh'] = True

    def test_landing_for_authenticated_profiles(self):
        for admin, destination in [(True, '/admin/'), (False, '/home')]:
            self.login(admin)
            for path in ['/', '/login']:
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers['Location'], destination)

    def test_footer_selection_for_both_profiles(self):
        for admin in [True, False]:
            self.login(admin)
            paths = [('/home', '/home'), (f'/resource/{self.resource_id}', '/home')]
            paths.append(('/admin/security', '/admin/') if admin else ('/my-bookings', '/my-bookings'))
            for path, destination in paths:
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                footer = FooterLinks(); footer.feed(response.get_data(as_text=True))
                selected = [a for a in footer.links if a.get('aria-current') == 'page']
                self.assertEqual(len(selected), 1)
                self.assertEqual(selected[0]['href'], destination)
                self.assertIn('bg-blue-50', selected[0]['class'])
                self.assertIn('text-blue-700', selected[0]['class'])
