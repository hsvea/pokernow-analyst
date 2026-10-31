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
