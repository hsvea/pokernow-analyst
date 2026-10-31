import http.client
import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from app import make_handler
from core import connect
from profiles import remember
from release_config import VERSION


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db_path = Path(self.tmp.name) / 'history.sqlite3'
        db = connect(db_path)
        with db:
            remember(db, 'p:42', 'Old')
            db.execute('INSERT INTO notes VALUES(?,?)', ('p:42', 'saved note'))
        db.close()
        self.events = queue.Queue()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler('test-token', self.events, db_path))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, token='test-token', name='New'):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        try:
            conn.request('POST', '/v1/snapshot', json.dumps({'tableId':'fixture','players':[{'profileId':'42','name':name}]}), {'Authorization':'Bearer '+token})
            res = conn.getresponse()
            return res.status, json.loads(res.read())
        finally:
            conn.close()

    def test_authenticated_profiles_and_version(self):
        status, result = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(result['version'], VERSION)
        self.assertEqual(result['profiles']['p:42']['note'], 'saved note')
        self.assertEqual(result['profiles']['p:42']['aliases'], ['Old'])
        self.assertEqual(self.events.get_nowait()[0], 'snapshot')

    def test_bad_token_rejected(self):
        self.assertEqual(self.request(token='wrong')[0], 401)
        self.assertTrue(self.events.empty())

    def test_invalid_player_rejected(self):
        self.assertEqual(self.request(name={'html':'bad'})[0], 400)
        self.assertTrue(self.events.empty())

    def test_capture_is_committed_before_ack_and_profiles(self):
        from test_live_capture import ROWS
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        try:
            payload = {'tableId':'fixture','players':[{'profileId':'a','name':'Same'}], 'capturedHand':{'rows':ROWS}}
            for expected in ['saved','duplicate']:
                conn.request('POST','/v1/snapshot',json.dumps(payload),{'Authorization':'Bearer test-token'})
                response=conn.getresponse();body=json.loads(response.read())
                self.assertEqual(response.status,200)
                self.assertEqual(body['capture']['status'],expected)
                self.assertEqual(body['profiles']['p:a']['hands'],1)
                self.assertEqual(body['profiles']['p:a']['pfr'],100)
        finally: conn.close()

    def test_table_actions_without_log_are_saved_before_ack(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        try:
            event=dict(id='sample:1',hand='sample:h1',profileId='42',name='New',kind='call',street='PREFLOP',bet=2)
            for _ in range(2):
                payload={'tableId':'fixture','players':[{'profileId':'42','name':'New'}],'tableEvents':[event]}
                conn.request('POST','/v1/snapshot',json.dumps(payload),{'Authorization':'Bearer test-token'})
                res=conn.getresponse();data=json.loads(res.read())
                self.assertEqual(res.status,200);self.assertEqual(data['tableAck'],['sample:1'])
                self.assertEqual(data['profiles']['p:42']['live']['call'],1)
                self.assertEqual(data['profiles']['p:42']['hands'],0)
        finally: conn.close()
