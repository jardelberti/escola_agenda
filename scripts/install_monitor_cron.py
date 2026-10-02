"""Install only this monitor's cron line, preserving a private copy of prior cron."""
import os
import sys
import subprocess
from pathlib import Path

MARKER = '# agenda-health-monitor'
TARGETS = {
    'vps': '/usr/bin/flock -n /tmp/agenda-vps-monitor.lock /usr/bin/python3 /home/ubuntu/escola_agenda/scripts/collect_vps_health.py >> /home/ubuntu/agenda-monitor.log 2>&1',
    'homelab': '/usr/bin/flock -n /tmp/agenda-n8n-monitor.lock sh -c \'docker exec -i n8n node --disable-warning=ExperimentalWarning - < /home/jardel/agenda-monitor/collect_n8n_health.js\' >> /home/jardel/agenda-monitor/monitor.log 2>&1',
}

if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) == 2 else ''
    if target not in TARGETS:
        raise SystemExit('Use vps ou homelab.')
    previous = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    if previous.returncode and 'no crontab' not in previous.stderr.lower():
        raise SystemExit('Não foi possível consultar o crontab; nada alterado.')
    backup = Path.home() / '.agenda-monitor-cron-before-20261002'
    if not backup.exists():
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(previous.stdout)
    lines = [line for line in previous.stdout.splitlines() if not line.rstrip().endswith(MARKER)]
    lines.append('*/5 * * * * PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin ' + TARGETS[target] + ' ' + MARKER)
    subprocess.run(['crontab', '-'], input='\n'.join(lines) + '\n', text=True, check=True)
    print('Coleta a cada 5 minutos instalada; demais tarefas preservadas.')
