import json
import tempfile
import unittest
from pathlib import Path
from core import connect, import_text, stats_table
from profiles import remember, details, snapshot_profiles


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'db.sqlite3'
        self.db=connect(self.path)
        self.addCleanup(self.db.close)

    def test_rename_retains_identity_stats_note(self):
        with self.db:
            remember(self.db,'p:123','First')
            self.db.execute('INSERT INTO samples VALUES(?,?,?,?)',('h','p:123','First',json.dumps({'hands':10,'vpip':3,'pfr':2})))
            self.db.execute('INSERT INTO notes VALUES(?,?)',('p:123','note'))
            remember(self.db,'p:123','Second')
        p=snapshot_profiles(self.path,[{'profileId':'123','name':'Second'}])['p:123']
        self.assertEqual(set(p['aliases']),{'First','Second'})
        self.assertEqual((p['hands'],p['vpip'],p['pfr'],p['note']),(10,30,20,'note'))
        self.assertEqual(stats_table(self.db)[0]['name'],'Second')

    def test_same_name_different_ids_never_merge(self):
        with self.db:
            remember(self.db,'p:1','Same')
            remember(self.db,'p:2','Same')
        self.assertEqual(len(stats_table(self.db)),2)

    def test_legacy_nickname_not_silently_merged(self):
        with self.db:
            remember(self.db,'n:same','Same')
            remember(self.db,'p:1','Same')
        self.assertEqual(len(stats_table(self.db)),2)
        self.assertEqual(details(self.db,'n:same')['identity'],'nickname only')

    def test_migration_preserves_v8_rows(self):
        with self.db:
            self.db.execute("DELETE FROM analyst_migrations WHERE name='profiles-v11'")
            self.db.execute('INSERT INTO samples VALUES(?,?,?,?)',('old','p:old','Old',json.dumps({'hands':1})))
            self.db.execute('INSERT INTO notes VALUES(?,?)',('p:old','saved'))
        another=connect(self.path)
        try:
            self.assertEqual(details(another,'p:old')['aliases'],['Old'])
            self.assertEqual(details(another,'p:old')['note'],'saved')
            self.assertEqual(another.execute('SELECT COUNT(*) FROM samples').fetchone()[0],1)
        finally: another.close()

    def test_empty_sample_is_not_zero_percent(self):
        with self.db: remember(self.db,'p:zero','Zero')
        p=snapshot_profiles(self.path,[{'profileId':'zero','name':'Zero'}])['p:zero']
        self.assertIsNone(p['vpip'])
        self.assertIsNone(p['pfr'])
