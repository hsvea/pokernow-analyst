"""Import complete visible Session Log hands; never score partial snapshots."""
import csv
import io
import re
from core import ACT, START, END, STACK, normalize_name, connect, parse_log, import_text


def ingest(db_path, room, payload):
    if payload is None:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get('rows'), list):
        raise ValueError('Invalid captured hand')
    rows = payload['rows']
    if not 4 <= len(rows) <= 250 or any(not isinstance(r, str) or len(r) > 3000 for r in rows):
        raise ValueError('Invalid captured rows')
    start, end = START.search(rows[0]), END.search(rows[-1])
    result = {'number': start.group(1) if start else '', 'status': 'rejected', 'added': 0}
    def reject(reason):
        return dict(result, reason=reason)
    if not start or not end or start.group(1) != end.group(1):
        return reject('Нет совпадающих начала и конца раздачи')
    if not re.search(r'No Limit (?:Texas )?Hold.?em|\bNLH\b', rows[0], re.I):
        return reject('Автосбор статистики пока поддерживает только NL Hold’em')
    if not any('posts a small blind' in r.lower() for r in rows) or not any('posts a big blind' in r.lower() for r in rows):
        return reject('Не видны оба блайнда')
    for row in rows[1:-1]:
        if START.search(row) or END.search(row):
            return reject('Смешаны разные раздачи')
        if (row.startswith('Player stacks:') or re.match(r'^(Flop|Turn|River):', row, re.I) or ACT.match(row)):
            continue
        if re.match(r'^Your hand is ', row) or re.match(r'^The (?:admin approved the player .+ participation with a stack of [\d,.]+\.|player .+ (?:requested a seat\.|quits the game with a stack of [\d,.]+\.|stand up with the stack of [\d,.]+\.))$', row):
            continue
        # Known bookkeeping/showdown lines do not affect VPIP/PFR/AF.
        if re.match(r'^(?:.+ collected [\d,.]+ from pot|Uncalled bet of [\d,.]+ returned to .+|.+ (?:does not show|mucks)(?: their hand)?[.!]?)', row, re.I):
            continue
        return reject('Неизвестная строка журнала; рука не учтена')
    out = io.StringIO()
    csv.writer(out).writerows([r] for r in rows)
    text = out.getvalue()
    hands = parse_log(text, room)
    if len(hands) != 1 or not hands[0]['complete'] or not hands[0]['has_stacks']:
        return reject('Не виден полный список участников')
    hand = hands[0]
    stack_rows = [r for r in rows if r.startswith('Player stacks:')]
    seated = {normalize_name(m.group(1))[0] for r in stack_rows for m in STACK.finditer(r.split(':', 1)[1])}
    if len(stack_rows) != 1 or seated != set(hand['participants']):
        return reject('Список участников расходится с действиями')
    if not 2 <= len(hand['participants']) <= 10 or any(not k.startswith('p:') for k in hand['participants']):
        return reject('Не подтверждены PokerNow ID участников')
    # Every participant must be represented in the action log (including blind posts).
    if set(hand['participants']) != {e['player'] for e in hand['events'] if e['player']}:
        return reject('В журнале отсутствуют действия участника')
    conn = connect(db_path)
    try:
        added, _, _ = import_text(conn, text, room)
        total = conn.execute('SELECT COUNT(*) FROM hands WHERE room=?', (room,)).fetchone()[0]
    finally:
        conn.close()
    return dict(result, status='saved' if added else 'duplicate', added=added, total=total,
                reason='Сохранена' if added else 'Уже есть в базе')
