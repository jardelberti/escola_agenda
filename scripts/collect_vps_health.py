"""Host-side read-only probes. Writes only sanitized snapshots into app_data."""
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def command(args, timeout=15):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=True).stdout


def probe(args, expected, timeout=15):
    try:
        return 'ok' if expected(command(args, timeout)) else 'error'
    except (subprocess.SubprocessError, OSError, ValueError):
        return 'error'


def collect():
    services = {
        'app': probe(['curl', '-fsS', '--max-time', '5', 'http://127.0.0.1:5000/health'], lambda s: json.loads(s).get('database') == 'connected'),
        'db': probe(['docker', 'exec', 'agenda_db', 'pg_isready', '-U', 'agenda_user', '-d', 'agenda_db'], lambda s: 'accepting connections' in s),
        'redis': probe(['docker', 'exec', 'agenda_redis', 'redis-cli', 'ping'], lambda s: s.strip() == 'PONG'),
        'worker': probe(['docker', 'compose', 'exec', '-T', 'worker', 'celery', '-A', 'app.celery', 'inspect', 'ping', '--json', '--timeout=5'],
                        lambda s: bool(d := json.loads(s)) and all(isinstance(v, dict) and v.get('ok') == 'pong' for v in d.values()), 20),
    }
    local = {'state': 'unknown', 'at': None}
    files = [p for p in (ROOT / 'backups').glob('*.dump') if p.is_file() and p.stat().st_size > 0]
    if files:
        newest = max(p.stat().st_mtime for p in files)
        local = {'state': 'ok', 'at': datetime.fromtimestamp(newest, timezone.utc).isoformat()}
    r2 = {'state': 'unknown', 'at': None}
    try:
        files = json.loads(command(['rclone', 'lsjson', 'r2:agenda-escola-backups', '--files-only', '--include', 'backup_agenda_*.sql.gz'], 30))
        dates = [x['ModTime'] for x in files if x.get('Size', 0) > 0 and x.get('ModTime')]
        if dates:
            r2 = {'state': 'ok', 'at': max(dates)}
    except (subprocess.SubprocessError, OSError, ValueError, KeyError):
        r2['state'] = 'error'
    payload = json.dumps({'services': services, 'local': local, 'r2': r2})
    writer = 'import json,sys; from operations import save_snapshot; save_snapshot("/app/data", "vps", json.load(sys.stdin)); print("Monitoramento VPS atualizado.")'
    subprocess.run(['docker', 'compose', 'exec', '-T', 'app', 'python', '-c', writer], cwd=ROOT, input=payload, text=True, check=True, timeout=15)


if __name__ == '__main__':
    collect()
