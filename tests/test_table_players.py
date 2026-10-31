import json
import tempfile
import unittest
from pathlib import Path
from core import connect
from profiles import snapshot_profiles
from table_players_ui import table_rows


class TablePlayersTests(unittest.TestCase):
    def test_membership_dedup_identity_and_filter(self):
        players=[{'name':'Same','profileId':'1'}, {'name':'Same','profileId':'2','folded':True}, {'name':'Away','profileId':'3','status':'AWAY'}, {'name':'Same','profileId':'1'}]
        profiles={'p:1':{'hands':10},'p:old':{'hands':100}}
        rows=table_rows({'players':players},profiles)
        self.assertEqual([r['key'] for r in rows],['p:1','p:2','p:3'])
        self.assertEqual([r['key'] for r in table_rows({'players':players},profiles,True)],['p:1'])
        self.assertEqual(table_rows({'players':[]},profiles),[])
        self.assertEqual(table_rows({'players':[players[1]]},profiles)[0]['name'],'Same')

    def test_ratios_use_opportunities_and_do_not_count_observations(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'db.sqlite3';db=connect(path)
            with db:
                db.execute('INSERT INTO samples VALUES(?,?,?,?)',('a','p:1','Old',json.dumps({'hands':20,'vpip':6,'pfr':4,'threebet':2,'threebet_opp':5,'f3bet':1,'f3bet_opp':2,'post_bet_raise':6,'post_call':3})))
                db.execute('INSERT INTO observations(room,player,name,status) VALUES(?,?,?,?)',('room','p:1','New','raise'))
            db.close()
            data=snapshot_profiles(path,[{'name':'New','profileId':'1'},{'name':'None','profileId':'2'}])
            st=data['p:1']
            self.assertEqual((st['hands'],st['vpip'],st['pfr'],st['threebet'],st['f3bet'],st['af']),(20,30,20,40,50,2))
            self.assertEqual(st['opportunities']['threebet'],5)
            for field in ('vpip','pfr','threebet','f3bet','af'):
                self.assertIsNone(data['p:2'][field])
