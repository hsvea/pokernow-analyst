"""Deduplicated visible table events. These are not complete hand samples."""
import math
from core import connect
from profiles import remember

KINDS = {'seen','call','raise','bet','check','fold','chips'}


def ingest_table(db_path, room, events):
    if events is None:
        return None
    if not isinstance(events, list) or len(events)>80:
        raise ValueError('Invalid table event batch')
    if not events:
        return []
    for e in events:
        if not isinstance(e, dict) or any(not isinstance(e.get(k),str) or not 0<len(e[k])<=120 for k in ['id','hand','name','street']):
            raise ValueError('Invalid table event')
        if not isinstance(e.get('profileId'),str) or len(e['profileId'])>100 or e.get('kind') not in KINDS:
            raise ValueError('Invalid table actor/action')
        if not isinstance(e.get('bet'),(int,float)) or not math.isfinite(e['bet']) or e['bet']<0:
            raise ValueError('Invalid table bet')
    conn=connect(db_path)
    try:
        with conn:
            for e in events:
                key='p:'+e['profileId'] if e['profileId'] else 'n:'+e['name'].lower()
                remember(conn,key,e['name'])
                conn.execute('INSERT OR IGNORE INTO table_events VALUES(?,?,?,?,?,?,?,?)',
                             (room+':'+e['id'],room,e['hand'],key,e['name'],e['kind'],e['street'],e['bet']))
        return [e['id'] for e in events]
    finally:
        conn.close()
