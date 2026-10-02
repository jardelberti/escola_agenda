"""Report/export parity, comparison boundaries, identity and untrusted labels."""
import csv
import io
import unittest
from datetime import date
from uuid import uuid4
from app import app
from models import db, Teacher, Resource, Booking
from reporting import filters_from, aggregate, percent
from tests.auth_helpers import authenticated_id


class AnalyticalReportsTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client=app.test_client()
        with app.app_context():
            suffix=uuid4().hex[:8]
            admin=Teacher(name='Admin testes',registration='report-admin-'+suffix,is_admin=True)
            teachers=[Teacher(name='Professor repetido',registration='report-'+suffix+str(i)) for i in range(2)]
            resources=[Resource(name='=SUM(1,1)</script>',is_active=False),Resource(name='Outro recurso')]
            db.session.add_all([admin,*teachers,*resources]);db.session.commit()
            self.ids=[t.id for t in [admin,*teachers]];self.resource_ids=[r.id for r in resources]
            user_id=authenticated_id(admin)
            for day,person,count in [('2026-09-29',0,1),('2026-09-30',1,2),('2026-10-01',0,2),('2026-10-02',1,2),('2026-10-03',0,1)]:
                for n in range(count):
                    db.session.add(Booking(resource_id=resources[0].id,teacher_id=teachers[person].id,teacher_name=teachers[person].name,
                                           date=date.fromisoformat(day),shift='matutino',slot_name='slot'+str(n),status='booked'))
            db.session.add(Booking(resource_id=resources[0].id,teacher_id=teachers[0].id,teacher_name='Teste',date=date(2026,10,2),shift='vespertino',slot_name='closed',status='closed'))
            db.session.add(Booking(resource_id=resources[1].id,teacher_id=teachers[0].id,teacher_name='Teste',date=date(2026,10,2),shift='vespertino',slot_name='other',status='booked'))
            db.session.commit()
        with self.client.session_transaction() as session: session['_user_id']=user_id;session['_fresh']=True
        self.params=dict(preset='custom',start_date='2026-10-01',end_date='2026-10-02',compare='previous',resource_id=str(self.resource_ids[0]),group='teacher',weekdays='1')

    def tearDown(self):
        with app.app_context():
            db.session.execute(db.delete(Booking).where(Booking.resource_id.in_(self.resource_ids)))
            db.session.execute(db.delete(Resource).where(Resource.id.in_(self.resource_ids)))
            db.session.execute(db.delete(Teacher).where(Teacher.id.in_(self.ids)));db.session.commit()

    def report(self, **changes):
        with app.app_context():
            filters=filters_from({**self.params,**changes},date(2026,10,2))
            return filters,aggregate(filters)

    def test_equal_previous_period_and_identity_grouping(self):
        filters,report=self.report()
        self.assertEqual((filters['previous_start'],filters['previous_end']),(date(2026,9,29),date(2026,9,30)))
        self.assertEqual((report['current']['total'],report['previous']['total']),(4,3))
        self.assertEqual(len(report['table']),2)
        self.assertEqual(report['kpis'][0]['percent'],33.3)
        self.assertEqual(report['current']['mean'],2.0)

    def test_weekday_scope_and_overlapping_periods(self):
        _,weekdays=self.report(end_date='2026-10-03',compare='none')
        _,all_days=self.report(end_date='2026-10-03',weekdays='0',compare='custom',compare_start='2026-10-02',compare_end='2026-10-03')
        self.assertEqual(weekdays['current']['total'],4)
        self.assertEqual(all_days['current']['total'],5)
        self.assertEqual(all_days['previous']['total'],3)
        self.assertEqual(sum(all_days['charts']['evolution']['values']),5)

    def test_filters_preserve_paused_records_and_exclude_blocks(self):
        _,all_resources=self.report(resource_id='0',compare='none')
        _,vespertino=self.report(resource_id='0',shift='vespertino',compare='none')
        _,teacher=self.report(teacher_id=str(self.ids[1]),compare='none')
        self.assertEqual(all_resources['current']['total'],5)
        self.assertEqual(vespertino['current']['total'],1)
        self.assertEqual(teacher['current']['total'],2)

    def test_invalid_and_oversized_ranges_are_rejected(self):
        for changes in [dict(end_date='2026-09-30'),dict(start_date='2024-01-01'),dict(resource_id='9999999'),dict(start_date='0001-01-01'),dict(compare='custom',compare_start='bad')]:
            with self.assertRaises(ValueError): self.report(**changes)
        self.assertIsNone(percent(4,0));self.assertEqual(percent(0,0),0)

    def test_html_csv_parity_and_formula_protection(self):
        response=self.client.get('/admin/reports',query_string=self.params)
        self.assertEqual(response.status_code,200)
        self.assertIn('Detalhamento por professor',response.get_data(as_text=True))
        params={**self.params,'group':'resource'}
        exported=self.client.get('/admin/reports/export',query_string=params)
        self.assertEqual(exported.status_code,200)
        rows=list(csv.reader(io.StringIO(exported.get_data().decode('utf-8-sig')),delimiter=';'))
        header=next(i for i,r in enumerate(rows) if r and r[0]=='Recurso' and len(r)>2)
        self.assertTrue(rows[header+1][0].startswith("'=SUM"))
        self.assertEqual(rows[header+1][1:4],['4','3','1'])
        self.assertNotIn('=SUM(1,1)</script>',response.get_data(as_text=True))

    def test_export_is_admin_only(self):
        with self.client.session_transaction() as session:session.clear();session['_user_id']=str(self.ids[1]);session['_fresh']=True
        self.assertNotEqual(self.client.get('/admin/reports/export',query_string=self.params).status_code,200)
