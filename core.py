"""PokerNow CSV/visible-state analyzer. Standard library only."""
import csv
import io
import json
import re
import sqlite3
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from profiles import migrate, remember

START = re.compile(r'--\s*starting hand\s*#(\d+)', re.I)
END = re.compile(r'--\s*ending hand\s*#(\d+)', re.I)
STACK = re.compile(r'#\d+\s+(.+?)\s*\(([\d,.]+)\)\s*(?=\||$)')
ACT = re.compile(r'^\s*("[^"]+"|[^\n]+?)\s+(posts a (?:small|big) blind|posts (?:an? )?ante|raises(?: to)?|bets|calls|checks|folds|shows)\b(?:\s+(.+))?$', re.I)


def normalize_name(raw):
    raw = raw.strip().strip('"').strip()
    if ' @ ' in raw:
        name, ident = raw.rsplit(' @ ', 1)
        return 'p:' + ident.strip(), name.strip()
    return 'n:' + raw.lower(), raw


def csv_lines(content):
    # PokerNow exports three CSV columns: event, timestamp, epoch milliseconds.
    # Also accepts pasted one-column text and UI logs with HH:MM prefixes.
    try:
        rows = csv.reader(io.StringIO(content.lstrip('\ufeff'), newline=''))
        for row in rows:
            if row:
                line = row[0].strip()
                if line:
                    yield line, (row[1].strip() if len(row) > 1 else '')
    except csv.Error:
        for line in content.splitlines():
            yield line.strip(), ''


def parse_log(text, room):
    hands = []
    current = None
    for raw, timestamp in csv_lines(text):
        raw = re.sub(r'^\d{1,2}:\d\d(?::\d\d)?\s+', '', raw)
        start = START.search(raw)
        if start:
            if current is not None:
                hands.append(current)
            current = {'id': f'{room}:{start.group(1)}', 'room': room, 'number': int(start.group(1)),
                       'timestamp': timestamp, 'participants': {}, 'events': [], 'complete': False,
                       'has_stacks': False}
            continue
        if current is None:
            continue
        if raw.lower().startswith('player stacks:'):
            for pm in STACK.finditer(raw.split(':', 1)[1]):
                key, name = normalize_name(pm.group(1))
                current['participants'][key] = name
            if current['participants']:
                current['has_stacks'] = True
            continue
        if re.match(r'^(flop|turn|river)\s*:', raw, re.I):
            street = raw.split(':', 1)[0].lower().strip()
            current['events'].append({'street': street, 'kind': 'street', 'player': '', 'name': '', 'amount': None})
            continue
        end = END.search(raw)
        if end:
            current['complete'] = True
            hands.append(current)
            current = None
            continue
        m = ACT.match(raw)
        if m:
            player, name = normalize_name(m.group(1))
            current['participants'].setdefault(player, name)
            verb = m.group(2).lower()
            if verb.startswith('posts'):
                kind = 'post'
            elif verb.startswith('raises'):
                kind = 'raise'
            elif verb.startswith('bets'):
                kind = 'bet'
            elif verb.startswith('calls'):
                kind = 'call'
            elif verb.startswith('checks'):
                kind = 'check'
            elif verb.startswith('folds'):
                kind = 'fold'
            else:
                kind = 'show'
            amount_m = re.search(r'[-+]?\d[\d,]*(?:\.\d+)?', m.group(3) or '')
            amount = float(amount_m.group().replace(',', '')) if amount_m else None
            current['events'].append({'kind': kind, 'player': player, 'name': name, 'amount': amount, 'raw': raw})
    if current is not None:
        hands.append(current)
    return hands


def summarize_hand(hand):
    stats = {k: {'name': name, 'hands': 1, 'vpip': 0, 'pfr': 0, 'threebet': 0,
                 'threebet_opp': 0, 'f3bet': 0, 'f3bet_opp': 0,
                 'post_bet_raise': 0, 'post_call': 0, 'saw_flop': 0,
                 'show': 0, 'folds': 0, 'actions': 0, 'preflop_calls': 0,
                 'preflop_raises': 0} for k, name in hand['participants'].items()}
    street = 'preflop'
    raises = 0
    opener = None
    folded = set()
    for event in hand['events']:
        if event['kind'] == 'street':
            street = event['street']
            if street == 'flop':
                for k, st in stats.items():
                    if k not in folded:
                        st['saw_flop'] = 1
            continue
        k, action = event['player'], event['kind']
        if k not in stats:
            stats[k] = {'name': event['name'], 'hands': 1, 'vpip': 0, 'pfr': 0,
                 'threebet': 0, 'threebet_opp': 0, 'f3bet': 0, 'f3bet_opp': 0,
                 'post_bet_raise': 0, 'post_call': 0, 'saw_flop': 0,
                 'show': 0, 'folds': 0, 'actions': 0, 'preflop_calls': 0,
                 'preflop_raises': 0}
        st = stats[k]
        if action == 'show':
            st['show'] = 1
            continue
        if action == 'post':
            continue
        st['actions'] += 1
        if action == 'fold':
            folded.add(k)
            st['folds'] += 1
        if street == 'preflop':
            if raises == 1 and opener != k and not st['threebet_opp']:
                st['threebet_opp'] = 1
            if raises >= 2 and opener == k and not st['f3bet_opp']:
                st['f3bet_opp'] = 1
                if action == 'fold':
                    st['f3bet'] = 1
            if action in ('call', 'raise', 'bet'):
                st['vpip'] = 1
            if action == 'call':
                st['preflop_calls'] += 1
            if action in ('raise', 'bet'):
                st['pfr'] = 1
                st['preflop_raises'] += 1
                if raises == 1:
                    st['threebet'] = 1
                if raises == 0:
                    opener = k
                raises += 1
        else:
            if action in ('bet', 'raise'):
                st['post_bet_raise'] += 1
            elif action == 'call':
                st['post_call'] += 1
    return stats


def connect(db_path):
    conn = sqlite3.connect(str(db_path), check_same_thread=True)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS hands (id TEXT PRIMARY KEY,room TEXT NOT NULL,number INTEGER NOT NULL,
       timestamp TEXT,complete INTEGER,raw_json TEXT);
    CREATE TABLE IF NOT EXISTS samples (hand_id TEXT,player TEXT,name TEXT,stats_json TEXT,
       PRIMARY KEY(hand_id,player));
    CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY AUTOINCREMENT,room TEXT,player TEXT,name TEXT,
       street TEXT,status TEXT,bet REAL,ts TEXT);
    CREATE INDEX IF NOT EXISTS idx_obs_player ON observations(player);
    CREATE INDEX IF NOT EXISTS idx_samples_player ON samples(player);
    CREATE TABLE IF NOT EXISTS notes (player TEXT PRIMARY KEY, note TEXT NOT NULL);
    ''')
    conn.commit()
    migrate(conn)
    return conn


def import_text(conn, content, room):
    hands = parse_log(content, room)
    added = 0
    participants = set()
    with conn:
        for hand in hands:
            # Avoid double-counting incomplete imports; only score completed hands.
            if not hand['complete']:
                continue
            if conn.execute('SELECT 1 FROM hands WHERE id=?', (hand['id'],)).fetchone():
                continue
            conn.execute('INSERT INTO hands VALUES(?,?,?,?,?,?)',
                (hand['id'], room, hand['number'], hand['timestamp'], 1,
                 json.dumps(hand, ensure_ascii=False)))
            for player, data in summarize_hand(hand).items():
                remember(conn, player, data['name'])
                participants.add(player)
                conn.execute('INSERT INTO samples VALUES (?,?,?,?)',
                    (hand['id'], player, data['name'], json.dumps(data)))
            added += 1
    return added, len(participants), len(hands)

FIELDS = ['hands','vpip','pfr','threebet','threebet_opp','f3bet','f3bet_opp',
          'post_bet_raise','post_call','saw_flop','show','folds','actions',
          'preflop_calls','preflop_raises']


def stats_table(conn):
    rows = conn.execute('SELECT player,name,stats_json FROM samples').fetchall()
    stats = {}
    for key, name, data in rows:
        st = stats.setdefault(key, {'key': key, 'name': name, **{k:0 for k in FIELDS}})
        d = json.loads(data)
        for k in FIELDS:
            st[k] += d.get(k, 0)
    for key,name in conn.execute('SELECT player,current_name FROM player_profiles'):
        st = stats.setdefault(key, {'key':key, 'name':name, **{k:0 for k in FIELDS}})
        st['name'] = name
    return sorted(stats.values(), key=lambda r: (-r['hands'], r['name'].lower()))


def percent(a,b):
    return f'{a * 100 / b:.1f}%' if b else '—'


def player_report(st):
    if not st:
        return 'Выбери игрока.'
    h = st['hands']
    vpip = st['vpip'] / h * 100 if h else 0
    pfr = st['pfr'] / h * 100 if h else 0
    hints = [f"Игрок: {st['name']} · {h} полностью записанных раздач."]
    if h < 30:
        hints.append('Малая выборка (<30): выводы предварительные, не делай сильных предположений о диапазонах.')
    elif h < 100:
        hints.append('Средняя выборка: отдельные показатели (особенно 3-беты) всё ещё нестабильны.')
    else:
        hints.append('Выборка достаточна для первичной оценки VPIP/PFR; редким ситуациям нужно больше наблюдений.')
    if h:
        if vpip >= 36 and pfr <= 16:
            hints.append('Профиль: лузово-пассивный. Чаще входит в банк коллом, чем рейзом. Не переоценивай блефы против такого соперника.')
        elif vpip >= 32 and pfr >= 23:
            hints.append('Профиль: лузово-агрессивный. Диапазон широк, агрессия выражена. Проверяй защиту против частых рейзов.')
        elif vpip <= 17 and pfr <= 15:
            hints.append('Профиль: тайтовый. Дорогие ставки могут представлять более сильный диапазон, но необходим контекст позиции.')
        elif vpip <= 28 and pfr >= 17:
            hints.append('Профиль ближе к тайтово-агрессивному. Оценивай диапазон открытия с учётом позиции.')
        else:
            hints.append('Профиль промежуточный: одной пары VPIP/PFR недостаточно для надёжного эксплойта.')
    if st['threebet_opp'] < 10:
        hints.append('3Bet: недостаточно ситуаций для вывода.')
    if st['f3bet_opp'] < 10:
        hints.append('Fold to 3Bet: недостаточно ситуаций для вывода.')
    calls = st['post_call']
    if calls >= 5:
        af = st['post_bet_raise']/calls
        hints.append(f'Постфлоп AF ≈ {af:.2f}; сравнивай с типом борда и позицией, а не как прямой сигнал для колла.')
    return '\n\n'.join(hints)


def room_from_filename(path):
    name = Path(path).stem
    for prefix in ('poker_now_log_', 'poker-now-hands-game-', 'pokernow_log_'):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name
