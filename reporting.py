"""Bounded, shared report calculations for HTML, CSV and print."""
from collections import defaultdict
from datetime import date, timedelta
from sqlalchemy import func, or_
from models import db, Booking, Resource, Teacher

PRESETS = {'this_week': 'Esta semana', 'this_month': 'Mês atual', 'last_month': 'Mês anterior', 'last30': 'Últimos 30 dias', 'custom': 'Personalizado'}
GROUPS = {'resource': 'Recurso', 'teacher': 'Professor', 'shift': 'Turno', 'date': 'Data'}
SHIFTS = {'matutino': 'Matutino', 'vespertino': 'Vespertino'}


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except ValueError:
        from datetime import datetime
        return datetime.strptime(value, '%d/%m/%Y').date()


def validate_range(start, end):
    if start.year < 1900 or end.year > 2100:
        raise ValueError('Selecione datas entre 1900 e 2100.')
    if end < start or (end - start).days > 365:
        raise ValueError('Selecione datas em ordem e um intervalo de até 366 dias.')


def filters_from(values, today):
    legacy = bool(values.get('start_date') and not values.get('preset'))
    preset = values.get('preset') or ('custom' if legacy else 'this_month')
    if preset not in PRESETS:
        raise ValueError('Período inválido.')
    if preset == 'custom':
        try: start, end = parse_date(values.get('start_date', '')), parse_date(values.get('end_date', ''))
        except (ValueError, TypeError): raise ValueError('Informe datas válidas.') from None
    elif preset == 'this_week': start, end = today - timedelta(days=today.weekday()), today
    elif preset == 'this_month': start, end = today.replace(day=1), today
    elif preset == 'last_month':
        end = today.replace(day=1) - timedelta(days=1); start = end.replace(day=1)
    else: start, end = today - timedelta(days=29), today
    validate_range(start, end)
    compare = values.get('compare', 'previous')
    if compare not in {'previous', 'custom', 'none'}: raise ValueError('Comparação inválida.')
    if compare == 'custom':
        try: previous_start, previous_end = parse_date(values.get('compare_start', '')), parse_date(values.get('compare_end', ''))
        except (ValueError, TypeError): raise ValueError('Informe as datas do período de comparação.') from None
        validate_range(previous_start, previous_end)
    else:
        previous_end = start - timedelta(days=1)
        previous_start = previous_end - (end - start)
    group = values.get('group', 'teacher' if legacy else 'resource')
    granularity = values.get('granularity', 'auto')
    shift = values.get('shift', '')
    if group not in GROUPS or granularity not in {'auto', 'day', 'week', 'month'} or shift not in {'', *SHIFTS}:
        raise ValueError('Agrupamento ou turno inválido.')
    ids = {}
    for key, model in [('resource_id', Resource), ('teacher_id', Teacher)]:
        try: value = int(values.get(key) or 0)
        except (ValueError, TypeError): raise ValueError('Recurso ou professor inválido.') from None
        if value < 0 or (value and not db.session.get(model, value)):
            raise ValueError('Recurso ou professor não encontrado.')
        ids[key] = value
    weekdays_values = values.getlist('weekdays') if hasattr(values, 'getlist') else [values.get('weekdays', '0' if legacy else '1')]
    weekdays = (weekdays_values[-1] if weekdays_values else ('0' if legacy else '1')) == '1'
    return dict(preset=preset, start=start, end=end, previous_start=previous_start, previous_end=previous_end,
                compare=compare, group=group, granularity=granularity, shift=shift, weekdays=weekdays, **ids)


def query_params(filters):
    return dict(preset='custom', start_date=filters['start'].isoformat(), end_date=filters['end'].isoformat(),
                compare=filters['compare'], compare_start=filters['previous_start'].isoformat(), compare_end=filters['previous_end'].isoformat(),
                resource_id=filters['resource_id'], teacher_id=filters['teacher_id'], shift=filters['shift'],
                group=filters['group'], granularity=filters['granularity'], weekdays=int(filters['weekdays']))


def percent(current, previous):
    return round(100 * (current - previous) / previous, 1) if previous else (0.0 if not current else None)


def aggregate(filters):
    query = db.session.query(Booking.date, Booking.resource_id, Booking.teacher_id, Booking.shift, func.count(Booking.id))
    ranges = [Booking.date.between(filters['start'], filters['end'])]
    if filters['compare'] != 'none': ranges.append(Booking.date.between(filters['previous_start'], filters['previous_end']))
    query = query.filter(Booking.status == 'booked', or_(*ranges))
    if filters['resource_id']: query = query.filter(Booking.resource_id == filters['resource_id'])
    if filters['teacher_id']: query = query.filter(Booking.teacher_id == filters['teacher_id'])
    if filters['shift']: query = query.filter(Booking.shift == filters['shift'])
    records = query.group_by(Booking.date, Booking.resource_id, Booking.teacher_id, Booking.shift).all()
    def summarize(start, end):
        selected = [r for r in records if start <= r[0] <= end and (not filters['weekdays'] or r[0].weekday() < 5)]
        counts = {k: defaultdict(int) for k in ['resource', 'teacher', 'shift', 'date', 'weekday']}
        for day, resource, teacher, shift, count in selected:
            for key, value in [('resource', resource), ('teacher', teacher), ('shift', shift), ('date', day), ('weekday', day.weekday())]: counts[key][value] += count
        weekday_days = sum((start + timedelta(days=i)).weekday() < 5 for i in range((end - start).days + 1))
        weekday_reservations = sum(r[4] for r in selected if r[0].weekday() < 5)
        return dict(total=sum(r[4] for r in selected), teachers=len(counts['teacher']), resources=len(counts['resource']),
                    mean=round(weekday_reservations / weekday_days, 2) if weekday_days else None, days=weekday_days, counts=counts)
    current = summarize(filters['start'], filters['end'])
    previous = summarize(filters['previous_start'], filters['previous_end']) if filters['compare'] != 'none' else None
    resources = {r.id: r.name + (' (Pausado)' if not r.is_active else '') for r in Resource.query.all()}
    teachers = {t.id: t.name + ' · ' + t.registration + (' (Pausado)' if not t.is_active else '') for t in Teacher.query.all()}
    def label(key, value):
        if key == 'resource': return resources.get(value, 'Recurso removido')
        if key == 'teacher': return teachers.get(value, 'Professor removido')
        if key == 'shift': return SHIFTS.get(value, value)
        return value.strftime('%d/%m/%Y')
    group = filters['group']
    keys = set(current['counts'][group]) | (set(previous['counts'][group]) if previous else set())
    keys = sorted(keys) if group == 'date' else sorted(keys, key=lambda k: (-current['counts'][group][k], label(group, k)))
    table = []
    for key in keys:
        now, before = current['counts'][group][key], previous['counts'][group][key] if previous else 0
        table.append(dict(label=label(group, key), current=now, previous=before, difference=now-before, percent=percent(now, before)))
    resource_keys = set(current['counts']['resource']) | (set(previous['counts']['resource']) if previous else set())
    resource_keys = sorted(resource_keys, key=lambda k: -(current['counts']['resource'][k] + (previous['counts']['resource'][k] if previous else 0)))
    visible, other = resource_keys[:10], resource_keys[10:]
    resource_chart = dict(labels=[resources.get(k, 'Recurso removido') for k in visible], current=[current['counts']['resource'][k] for k in visible], previous=[previous['counts']['resource'][k] if previous else 0 for k in visible])
    if other:
        resource_chart['labels'].append('Outros'); resource_chart['current'].append(sum(current['counts']['resource'][k] for k in other)); resource_chart['previous'].append(sum(previous['counts']['resource'][k] for k in other) if previous else 0)
    span = (filters['end'] - filters['start']).days + 1
    grain = filters['granularity'] if filters['granularity'] != 'auto' else ('day' if span <= 31 else 'week' if span <= 120 else 'month')
    def bucket(day):
        if grain == 'week': return day - timedelta(days=day.weekday())
        if grain == 'month': return day.replace(day=1)
        return day
    def series(summary, start, end):
        values = defaultdict(int)
        for i in range((end-start).days+1):
            day = start + timedelta(days=i)
            if not filters['weekdays'] or day.weekday() < 5: values[bucket(day)] += 0
        for day, count in summary['counts']['date'].items(): values[bucket(day)] += count
        days = sorted(values)
        return dict(labels=[d.strftime('%m/%Y' if grain == 'month' else '%d/%m') for d in days], values=[values[d] for d in days])
    evolution = series(current, filters['start'], filters['end'])
    weekdays_chart = dict(labels=['Seg', 'Ter', 'Qua', 'Qui', 'Sex'], values=[current['counts']['weekday'][i] for i in range(5)])
    shift_chart = dict(labels=list(SHIFTS.values()), current=[current['counts']['shift'][k] for k in SHIFTS], previous=[previous['counts']['shift'][k] if previous else 0 for k in SHIFTS])
    kpis = []
    for key, title in [('total', 'Reservas'), ('teachers', 'Professores participantes'), ('resources', 'Recursos utilizados'), ('mean', 'Média por dia de seg–sex')]:
        value, before = current[key], previous[key] if previous else None
        kpis.append(dict(title=title, value=value, previous=before, percent=percent(value, before) if value is not None and before is not None else None))
    return dict(table=table, kpis=kpis, current=current, previous=previous, charts=dict(resource=resource_chart, evolution=evolution, shift=shift_chart, weekday=weekdays_chart), grain=grain)


def csv_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')): return "'" + value
    return value
