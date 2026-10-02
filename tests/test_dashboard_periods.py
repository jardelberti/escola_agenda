"""Dashboard windows must match captions and exclude future/weekend timeline data."""
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo
from app import app
from models import db, Teacher, Resource, Booking
from routes.admin import recent_weekdays
from tests.auth_helpers import authenticated_id


class DashboardPeriodsTests(unittest.TestCase):
    def test_weekend_timeline_ends_on_friday(self):
        days = recent_weekdays(date(2026, 10, 4))
        self.assertEqual(len(days), 14)
        self.assertEqual(days[-1], date(2026, 10, 2))
        self.assertTrue(all(day.weekday() < 5 for day in days))
        self.assertEqual(days, sorted(set(days)))

    def test_windows_exclude_future_and_weekend_timeline_bookings(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        today = date(2026, 10, 2)
        with app.app_context():
            counts_before = [Booking.query.filter_by(date=day, status='booked').count() for day in recent_weekdays(today)]
            teacher = Teacher(name='Admin de teste', registration='dash-' + uuid4().hex[:12], is_admin=True)
            resource = Resource(name='Recurso de teste ' + uuid4().hex[:8])
            db.session.add_all([teacher, resource]); db.session.commit()
            teacher_id, resource_id = teacher.id, resource.id
            user_id = authenticated_id(teacher)
            for i, day in enumerate([today, today - timedelta(days=29), today - timedelta(days=30),
                                     today + timedelta(days=1), date(2026, 9, 26)]):
                db.session.add(Booking(resource_id=resource_id, teacher_id=teacher_id, teacher_name=teacher.name,
                                       date=day, shift='matutino', slot_name='teste-' + str(i), status='booked'))
            db.session.add(Booking(resource_id=resource_id, teacher_id=teacher_id, teacher_name=teacher.name,
                                   date=today, shift='matutino', slot_name='bloqueado', status='closed'))
            db.session.commit()
            resource_name = resource.name
        try:
            client = app.test_client()
            with client.session_transaction() as session:
                session['_user_id'] = user_id
                session['_fresh'] = True
            fixed_now = datetime(2026, 10, 2, 14, tzinfo=ZoneInfo('America/Sao_Paulo'))
            with patch('routes.admin.datetime') as clock, patch('routes.admin.render_template', return_value='OK') as render:
                clock.now.return_value = fixed_now
                self.assertEqual(client.get('/admin/').status_code, 200)
                context = render.call_args.kwargs
            usage = dict(context['resource_usage'])
            self.assertEqual(usage[resource_name], 3)
            self.assertEqual(context['analytics_period'], '03/09/2026 a 02/10/2026')
            self.assertEqual(len(context['chart_timeline_labels']), 14)
            resource_idx = context['chart_resource_labels'].index(resource_name)
            self.assertEqual(context['chart_resource_data'][resource_idx], 3)
            # Only today's fixture contributes; older dates, Saturday and future do not.
            counts_before[-1] += 1
            self.assertEqual(context['chart_timeline_data'], counts_before)
        finally:
            with app.app_context():
                db.session.execute(db.delete(Booking).where(Booking.resource_id == resource_id))
                db.session.execute(db.delete(Resource).where(Resource.id == resource_id))
                db.session.execute(db.delete(Teacher).where(Teacher.id == teacher_id))
                db.session.commit()
