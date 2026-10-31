import tempfile
import unittest
from pathlib import Path
from core import connect
from profiles import snapshot_profiles
from table_capture import ingest_table

class TableCaptureTests(unittest.TestCase):
    def test_table_only_retry_identity_and_separation_from_complete_hands(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'history.sqlite3';connect(path).close()
            events=[dict(id=str(i),hand='hand1',profileId='a',name='Same',kind=k,street='PREFLOP',bet=2) for i,k in enumerate(['seen','call','raise','fold','chips'])]
            for _ in range(2):self.assertEqual(ingest_table(path,'table',events),[str(i) for i in range(5)])
            p=snapshot_profiles(path,[{'profileId':'a','name':'Same'},{'profileId':'b','name':'Same'}])
            self.assertEqual(p['p:a']['live']['actions'],3)
            self.assertEqual(p['p:a']['live']['seen'],1)
            self.assertEqual(p['p:b']['live']['actions'],0)
            self.assertEqual(p['p:a']['hands'],0)
            self.assertIsNone(p['p:a']['vpip'])
            bad=events+[dict(events[0],id='bad',bet=float('nan'))]
            with self.assertRaises(ValueError):ingest_table(path,'table',bad)
            self.assertEqual(snapshot_profiles(path,[{'profileId':'a','name':'Same'}])['p:a']['live']['actions'],3)
