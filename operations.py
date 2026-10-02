"""Private, bounded operational snapshots; no contacts or execution payloads."""
import json
import os
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo('America/Sao_Paulo')


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone')
    return parsed.astimezone(timezone.utc)


def clean_snapshot(source, payload):
    if not isinstance(payload, dict):
        raise ValueError('payload')
    result = {'received_at': datetime.now(timezone.utc).isoformat()}
    if source == 'whatsapp':
        if type(payload.get('active')) is not bool or type(payload.get('schedule_ok')) is not bool:
            raise ValueError('configuration')
        result.update(active=payload['active'], schedule_ok=payload['schedule_ok'])
        for field in ('latest', 'automatic'):
            run = payload.get(field)
            if run is None:
                result[field] = None
                continue
            if not isinstance(run, dict) or run.get('status') not in {'success', 'error', 'running', 'waiting', 'canceled', 'crashed', 'new', 'unknown'}:
                raise ValueError('execution')
            if run.get('mode') not in {'trigger', 'manual', 'retry', 'other'}:
                raise ValueError('mode')
            count = run.get('accepted')
            if count is not None and (type(count) is not int or not 0 <= count <= 10000):
                raise ValueError('count')
            result[field] = {'started_at': timestamp(run['started_at']).isoformat(),
                             'status': run['status'], 'mode': run['mode'], 'accepted': count,
                             'admin_only': run.get('admin_only') is True}
    elif source == 'vps':
        services = payload.get('services', {})
        result['services'] = {}
        for name in ('app', 'db', 'redis', 'worker'):
            state = services.get(name)
            if state not in {'ok', 'error', 'unknown'}:
                raise ValueError('service')
            result['services'][name] = state
        for name in ('local', 'r2'):
            backup = payload.get(name, {})
            state = backup.get('state')
            if state not in {'ok', 'error', 'unknown'}:
                raise ValueError('backup')
            result[name] = {'state': state, 'at': timestamp(backup['at']).isoformat() if backup.get('at') else None}
    else:
        raise ValueError('source')
    return result


def save_snapshot(folder, source, payload):
    data = clean_snapshot(source, payload)
    directory = Path(folder) / 'operations'
    directory.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream)
        os.replace(path, directory / (source + '.json'))
    finally:
        if os.path.exists(path):
            os.unlink(path)


def read_snapshot(folder, source, now):
    try:
        path = Path(folder) / 'operations' / (source + '.json')
        if path.stat().st_size > 65536:
            return None
        data = json.loads(path.read_text(encoding='utf-8'))
        data['stale'] = not 0 <= (now - timestamp(data['received_at'])).total_seconds() <= 900
        return data
    except (OSError, ValueError, TypeError, KeyError):
        return None


def format_time(value):
    return timestamp(value).astimezone(TZ).strftime('%d/%m às %H:%M') if value else 'Sem registro'


def dashboard_status(folder, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local_now = now.astimezone(TZ)
    due = local_now.replace(hour=7, minute=0, second=0, microsecond=0)
    if local_now < due + timedelta(minutes=10):
        due -= timedelta(days=1)
    while due.weekday() >= 5:
        due -= timedelta(days=1)
    next_run = local_now.replace(hour=7, minute=0, second=0, microsecond=0)
    if next_run <= local_now:
        next_run += timedelta(days=1)
    while next_run.weekday() >= 5:
        next_run += timedelta(days=1)
    whatsapp = read_snapshot(folder, 'whatsapp', now)
    vps = read_snapshot(folder, 'vps', now)
    cards = []
    def card(title, state, text, detail):
        cards.append(dict(title=title, state=state, text=text, detail=detail))
    if not whatsapp or whatsapp['stale']:
        card('WhatsApp', 'warning', 'Monitoramento indisponível' if not whatsapp else 'Monitoramento desatualizado',
             'Última atualização: ' + (format_time(whatsapp['received_at']) if whatsapp else 'sem registro'))
    else:
        auto = whatsapp.get('automatic')
        morning_ok = False
        if auto:
            started = timestamp(auto['started_at']).astimezone(TZ)
            morning_ok = started.date() == due.date() and 6 * 60 + 55 <= started.hour * 60 + started.minute <= 7 * 60 + 10 and auto['status'] == 'success'
        latest = whatsapp.get('latest')
        if not whatsapp['active'] or not whatsapp['schedule_ok']:
            text, state = 'Agendamento requer atenção', 'error'
        elif latest and latest['status'] in {'error', 'crashed', 'canceled'}:
            text, state = 'Última execução falhou', 'error'
        elif morning_ok:
            text, state = 'Execução das 7h concluída', 'ok'
        else:
            text, state = 'Disparo das 7h ainda não confirmado', 'warning'
        detail = 'Esperado: ' + due.strftime('%d/%m às 07:00') + '. Próximo: ' + next_run.strftime('%d/%m às 07:00') + '.'
        if auto:
            detail += ' Última automática: ' + format_time(auto['started_at']) + '.'
        if latest:
            mode = {'trigger': 'automática', 'manual': 'manual', 'retry': 'repetição', 'other': 'outra'}[latest['mode']]
            detail += ' Última tentativa (' + mode + '): ' + format_time(latest['started_at']) + '.'
            detail += (' Mensagens aceitas pela API: ' + str(latest['accepted']) + '.' if latest['accepted'] is not None else ' Contagem de mensagens indisponível.')
            if latest['admin_only']:
                detail += ' Essa execução continha apenas envio ao administrador.'
        detail += ' Aceitação pela API não confirma entrega no WhatsApp.'
        card('WhatsApp', state, text, detail)
    for key, title in [('local', 'Backup local'), ('r2', 'Backup na nuvem')]:
        if not vps or vps['stale']:
            card(title, 'warning', 'Monitoramento indisponível' if not vps else 'Monitoramento desatualizado', 'Não foi possível confirmar um backup recente.')
            continue
        backup = vps[key]
        fresh = backup['at'] and 0 <= (now - timestamp(backup['at'])).total_seconds() <= 36 * 3600
        state = 'ok' if backup['state'] == 'ok' and fresh else 'warning'
        card(title, state, 'Backup recente encontrado' if state == 'ok' else 'Backup requer atenção',
             'Último arquivo: ' + format_time(backup['at']) + '. Presença do arquivo não comprova restauração.')
    if not vps or vps['stale']:
        card('Serviços', 'warning', 'Monitoramento indisponível' if not vps else 'Monitoramento desatualizado', 'Aplicação, banco, Redis e Celery.')
    else:
        labels = {'app': 'Aplicação', 'db': 'Banco', 'redis': 'Redis', 'worker': 'Celery'}
        states = {'ok': 'OK', 'error': 'falha', 'unknown': 'não confirmado'}
        card('Serviços', 'ok' if all(x == 'ok' for x in vps['services'].values()) else 'error',
             'Todos respondendo' if all(x == 'ok' for x in vps['services'].values()) else 'Serviço requer atenção',
             ' · '.join(labels[k] + ': ' + states[v] for k, v in vps['services'].items()) + '. Atualizado: ' + format_time(vps['received_at']))
    return cards
