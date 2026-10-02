"""Monitoring must fail visibly and never mistake manual runs for the 7h job."""
import json
import unittest
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from unittest.mock import patch
from operations import clean_snapshot, dashboard_status, save_snapshot
from app import app


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = datetime(2026, 10, 5, 10, 20, tzinfo=timezone.utc)

    def write(self, automatic, latest=None):
        payload = dict(active=True, schedule_ok=True, automatic=automatic, latest=latest or automatic)
        save_snapshot(self.tmp.name, 'whatsapp', payload)
        path = self.tmp.name + '/operations/whatsapp.json'
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        data['received_at'] = self.now.isoformat()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)

    def run_data(self, at, mode='trigger', status='success'):
        return dict(started_at=at, mode=mode, status=status, accepted=1, admin_only=False)

    def test_missing_and_stale_snapshots_are_visible(self):
        self.assertTrue(all(c['state'] == 'warning' for c in dashboard_status(self.tmp.name, self.now)))
        self.write(self.run_data('2026-10-05T10:00:00Z'))
        self.assertEqual(dashboard_status(self.tmp.name, self.now)[0]['state'], 'ok')
        from datetime import timedelta
        self.assertIn('desatualizado', dashboard_status(self.tmp.name, self.now + timedelta(minutes=16))[0]['text'])

    def test_manual_success_cannot_mask_missing_morning_trigger(self):
        self.write(self.run_data('2026-10-02T13:22:00Z'), self.run_data('2026-10-05T10:15:00Z', 'manual'))
        self.assertEqual(dashboard_status(self.tmp.name, self.now)[0]['state'], 'warning')

    def test_off_schedule_trigger_does_not_confirm_morning(self):
        self.write(self.run_data('2026-10-05T13:22:00Z'))
        self.assertEqual(dashboard_status(self.tmp.name, self.now)[0]['state'], 'warning')

    def test_failed_latest_attempt_is_not_green(self):
        self.write(self.run_data('2026-10-05T10:00:00Z'), self.run_data('2026-10-05T10:15:00Z', 'manual', 'error'))
        self.assertEqual(dashboard_status(self.tmp.name, self.now)[0]['state'], 'error')

    def test_weekend_and_monday_before_deadline_expect_friday(self):
        self.now = datetime(2026, 10, 5, 10, 5, tzinfo=timezone.utc)
        self.write(self.run_data('2026-10-02T10:00:00Z'))
        card = dashboard_status(self.tmp.name, self.now)[0]
        self.assertEqual(card['state'], 'ok')
        self.assertIn('Esperado: 02/10', card['detail'])

    def test_whitelist_discards_sensitive_data_and_rejects_bad_counts(self):
        run = self.run_data('2026-10-05T10:00:00Z')
        run['phone'] = 'private-contact'
        payload = dict(active=True, schedule_ok=True, automatic=run, latest=run, token='private-token')
        self.assertNotIn('private', json.dumps(clean_snapshot('whatsapp', payload)))
        run['accepted'] = -1
        with self.assertRaises(ValueError):
            clean_snapshot('whatsapp', payload)

    def test_endpoint_requires_dedicated_key_and_bounds_payload(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        client = app.test_client()
        payload = dict(active=True, schedule_ok=True, latest=None, automatic=None)
        with patch.dict('os.environ', {'MONITOR_API_KEY': 'monitor-test-key', 'INTEGRATION_API_KEY': 'different-api-key'}):
            self.assertEqual(client.post('/api/integrations/monitor/whatsapp', json=payload).status_code, 401)
            self.assertEqual(client.post('/api/integrations/monitor/whatsapp', json=payload, headers={'X-API-Key': 'different-api-key'}).status_code, 401)
            with patch('routes.integrations.save_snapshot', side_effect=lambda folder, source, value: save_snapshot(self.tmp.name, source, value)):
                self.assertEqual(client.post('/api/integrations/monitor/whatsapp', json=payload, headers={'X-Monitor-Key': 'monitor-test-key'}).status_code, 200)
                self.assertEqual(client.post('/api/integrations/monitor/whatsapp', data='x' * 65537, headers={'X-Monitor-Key': 'monitor-test-key'}).status_code, 413)

    def test_recent_backup_and_service_failure_are_independent(self):
        payload = dict(services=dict(app='ok', db='ok', redis='ok', worker='error'),
                       local=dict(state='ok', at='2026-10-05T03:00:00Z'), r2=dict(state='error', at=None))
        save_snapshot(self.tmp.name, 'vps', payload)
        # Use current time to avoid treating collection timestamp as future.
        now = datetime.now(timezone.utc)
        payload['local']['at'] = now.isoformat()
        save_snapshot(self.tmp.name, 'vps', payload)
        # Snapshot received a few microseconds after now; evaluate after collection.
        cards = dashboard_status(self.tmp.name, datetime.now(timezone.utc))
        self.assertEqual([c['state'] for c in cards[1:]], ['ok', 'warning', 'error'])
