"""Additive player identity/history storage; never merge different IDs by nickname."""
import json
import sqlite3
from datetime import datetime, timezone


def player_key(player):
    name = str(player.get('name', '')).strip()[:90]
    pid = str(player.get('profileId') or '').strip()[:100]
    return ('p:' + pid if pid else 'n:' + name.lower()), name


def remember(conn, key, name):
    if not name:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn.execute('INSERT INTO player_profiles(player,current_name,last_seen) VALUES(?,?,?) '
                 'ON CONFLICT(player) DO UPDATE SET current_name=excluded.current_name,last_seen=excluded.last_seen',
                 (key, name[:90], now))
    conn.execute('INSERT INTO player_aliases(player,name,first_seen,last_seen) VALUES(?,?,?,?) '
                 'ON CONFLICT(player,name) DO UPDATE SET last_seen=excluded.last_seen', (key,name[:90],now,now))


def migrate(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS player_profiles(player TEXT PRIMARY KEY,current_name TEXT NOT NULL,last_seen TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS player_aliases(player TEXT NOT NULL,name TEXT NOT NULL,first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,PRIMARY KEY(player,name));
    CREATE TABLE IF NOT EXISTS analyst_migrations(name TEXT PRIMARY KEY);
    ''')
    if not conn.execute("SELECT 1 FROM analyst_migrations WHERE name='profiles-v11'").fetchone():
        with conn:
            for key,name in conn.execute('SELECT player,name FROM samples ORDER BY rowid').fetchall():
                remember(conn,key,name)
            for key,name in conn.execute('SELECT player,name FROM observations ORDER BY id').fetchall():
                remember(conn,key,name)
            conn.execute("INSERT INTO analyst_migrations VALUES('profiles-v11')")


def details(conn, key):
    row = conn.execute('SELECT current_name,last_seen FROM player_profiles WHERE player=?',(key,)).fetchone()
    aliases = [r[0] for r in conn.execute('SELECT name FROM player_aliases WHERE player=? ORDER BY last_seen DESC,name',(key,))]
    note = conn.execute('SELECT note FROM notes WHERE player=?',(key,)).fetchone()
    return {'key':key, 'name':row[0] if row else '', 'aliases':aliases, 'note':note[0] if note else '',
            'identity':'PokerNow ID' if key.startswith('p:') else 'nickname only'}


def snapshot_profiles(db_path, players):
    """Called on HTTP worker using its own read-only connection."""
    conn = sqlite3.connect(db_path.resolve().as_uri()+'?mode=ro', uri=True, timeout=2)
    try:
        result = {}
        for p in players:
            key,name = player_key(p)
            if not name:
                continue
            entry = details(conn,key)
            live = dict(conn.execute('SELECT kind,COUNT(*) FROM table_events WHERE player=? GROUP BY kind',(key,)))
            entry['live'] = {field:live.get(field,0) for field in ('seen','call','raise','bet','check','fold','chips')}
            entry['live']['actions'] = sum(live.get(field,0) for field in ('call','raise','bet','check','fold'))
            totals = {field:0 for field in ('hands','vpip','pfr','threebet','threebet_opp','f3bet','f3bet_opp','post_bet_raise','post_call')}
            for (raw,) in conn.execute('SELECT stats_json FROM samples WHERE player=?',(key,)):
                sample = json.loads(raw)
                for field in totals:
                    totals[field] += sample.get(field,0)
            h = totals['hands']
            entry.update(hands=h, vpip=round(100*totals['vpip']/h,1) if h else None,
                         pfr=round(100*totals['pfr']/h,1) if h else None)
            ratio = lambda a,b: round(100*totals[a]/totals[b],1) if totals[b] else None
            entry.update(threebet=ratio('threebet','threebet_opp'), f3bet=ratio('f3bet','f3bet_opp'),
                         af=round(totals['post_bet_raise']/totals['post_call'],2) if totals['post_call'] else None,
                         opportunities={'threebet':totals['threebet_opp'],'f3bet':totals['f3bet_opp'],
                                        'post_call':totals['post_call']}, basis='all stored completed hands')
            # Keep local bridge payload bounded even for large note histories.
            entry['note'] = entry['note'][:300]
            entry['aliases'] = entry['aliases'][:12]
            result[key] = entry
        return result
    finally:
        conn.close()
