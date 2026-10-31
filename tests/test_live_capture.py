import csv
import io
import tempfile
import unittest
from pathlib import Path
from core import connect, import_text
from profiles import snapshot_profiles
from live_capture import ingest


ROWS = ['-- starting hand #12 (id: test) No Limit Texas Hold\'em --',
        'Player stacks: #1 "Same @ a" (100) | #2 "Same @ b" (100)',
        '"Same @ a" posts a small blind of 1', '"Same @ b" posts a big blind of 2',
        '"Same @ a" raises to 6', '"Same @ b" calls 6', 'Flop: [As, Kd, 2h]',
        '"Same @ b" checks', '"Same @ a" bets 4', '"Same @ b" calls 4',
        'Turn: [As, Kd, 2h, 3d]', '"Same @ b" checks', '"Same @ a" bets 10',
        '"Same @ b" folds', 'Uncalled bet of 10 returned to "Same @ a"',
        '"Same @ a" collected 20 from pot', '-- ending hand #12 --']


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'db.sqlite3'
        connect(self.path).close()

    def test_save_retry_csv_dedup_and_behavior(self):
        self.assertEqual(ingest(self.path, 'room', {'rows': ROWS})['added'], 1)
        self.assertEqual(ingest(self.path, 'room', {'rows': ROWS})['status'], 'duplicate')
        data = snapshot_profiles(self.path, [{'profileId': p, 'name': 'Same'} for p in ['a','b']])
        self.assertEqual((data['p:a']['hands'],data['p:a']['vpip'],data['p:a']['pfr']), (1,100,100))
        self.assertEqual((data['p:b']['hands'],data['p:b']['vpip'],data['p:b']['pfr']), (1,100,0))
        self.assertEqual(data['p:b']['opportunities']['post_call'], 1)
        out = io.StringIO(); csv.writer(out).writerows([r] for r in ROWS)
        conn = connect(self.path)
        try: self.assertEqual(import_text(conn, out.getvalue(), 'room')[0], 0)
        finally: conn.close()

    def test_reject_incomplete_unknown_variant_identity_and_roster(self):
        cases = [ROWS[:-1], ROWS[1:], [r.replace('hand #12 --','hand #13 --') for r in ROWS],
                 ROWS[:5]+['"Same @ b" straddles 4']+ROWS[5:],
                 [r.replace("No Limit Texas Hold'em",'Pot Limit Omaha') for r in ROWS],
                 [r.replace('Same @ b','Same') for r in ROWS],
                 [r for r in ROWS if not r.startswith('Player stacks:')],
                 ROWS[:5]+['"Other @ c" calls 6']+ROWS[5:]]
        for rows in cases:
            with self.subTest(rows=rows):
                self.assertEqual(ingest(self.path, 'room', {'rows': rows})['status'], 'rejected')
        conn = connect(self.path)
        try: self.assertEqual(conn.execute('SELECT COUNT(*) FROM hands').fetchone()[0], 0)
        finally: conn.close()

    def test_table_identity_and_payload_limits(self):
        for room in ['first','second']:
            self.assertEqual(ingest(self.path, room, {'rows': ROWS})['added'], 1)
        for bad in [[], {'rows': [None]*4}, {'rows': ['x'*3001]*4}, {'rows': ROWS*30}]:
            with self.assertRaises(ValueError): ingest(self.path, 'room', bad)
