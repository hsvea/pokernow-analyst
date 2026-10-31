import sqlite3
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import parse_log, summarize_hand, connect, import_text, stats_table, percent

SAMPLE='''"-- starting hand #1 (No Limit Texas Hold'em) (dealer: \"Amy @ a1\") --",2026-10-31 02:00:00
"Player stacks: #1 \"Amy @ a1\" (100) | #2 \"Bob @ b1\" (100) | #3 \"Cara @ c1\" (100)",2026-10-31 02:00:01
"\"Amy @ a1\" posts a small blind of 1",2026-10-31 02:00:02
"\"Bob @ b1\" posts a big blind of 2",2026-10-31 02:00:03
"\"Cara @ c1\" raises to 6",2026-10-31 02:00:04
"\"Amy @ a1\" raises to 18",2026-10-31 02:00:05
"\"Bob @ b1\" folds",2026-10-31 02:00:06
"\"Cara @ c1\" folds",2026-10-31 02:00:07
"Uncalled bet of 12 returned to \"Amy @ a1\"",2026-10-31 02:00:07
"\"Amy @ a1\" collected 22 from pot",2026-10-31 02:00:08
"-- ending hand #1 --",2026-10-31 02:00:08
"-- starting hand #2 (No Limit Texas Hold'em) --",2026-10-31 02:01:00
"Player stacks: #1 \"Amy @ a1\" (101) | #2 \"Bob @ b1\" (98) | #3 \"Cara @ c1\" (100)",2026-10-31 02:01:01
"\"Amy @ a1\" posts a small blind of 1",2026-10-31 02:01:02
"\"Bob @ b1\" posts a big blind of 2",2026-10-31 02:01:03
"\"Cara @ c1\" calls 2",2026-10-31 02:01:04
"\"Amy @ a1\" calls 2",2026-10-31 02:01:05
"\"Bob @ b1\" checks",2026-10-31 02:01:06
"Flop: [As, 2h, 7h]",2026-10-31 02:01:07
"\"Amy @ a1\" checks",2026-10-31 02:01:08
"\"Bob @ b1\" bets 5",2026-10-31 02:01:09
"\"Cara @ c1\" calls 5",2026-10-31 02:01:10
"\"Amy @ a1\" folds",2026-10-31 02:01:11
"Turn: As, 2h, 7h [4c]",2026-10-31 02:01:12
"\"Bob @ b1\" checks",2026-10-31 02:01:13
"\"Cara @ c1\" bets 8",2026-10-31 02:01:14
"\"Bob @ b1\" calls 8",2026-10-31 02:01:15
"River: As, 2h, 7h, 4c [9h]",2026-10-31 02:01:16
"\"Bob @ b1\" checks",2026-10-31 02:01:17
"\"Cara @ c1\" checks",2026-10-31 02:01:18
"\"Cara @ c1\" shows a Ah, Jh",2026-10-31 02:01:19
"-- ending hand #2 --",2026-10-31 02:01:20
'''

# Convert the readable raw fixture into a correctly quoted PokerNow-style CSV.
SAMPLE = '\n'.join('"' + line.rsplit('",2026-', 1)[0][1:].replace('"', '""') + '",2026-' + line.rsplit('",2026-', 1)[1] for line in SAMPLE.splitlines() if '",2026-' in line) + '\n'

class TestCore(unittest.TestCase):
    def test_parse(self):
        hands=parse_log(SAMPLE,'room1')
        self.assertEqual(len(hands),2)
        self.assertEqual(len(hands[0]['participants']),3)
        first=summarize_hand(hands[0])
        self.assertEqual(first['p:a1']['threebet'],1)
        self.assertEqual(first['p:a1']['threebet_opp'],1)
        self.assertEqual(first['p:c1']['f3bet'],1)
        self.assertEqual(first['p:b1']['vpip'],0)
        second=summarize_hand(hands[1])
        self.assertEqual(second['p:c1']['vpip'],1)
        self.assertEqual(second['p:c1']['post_call'],1)
        self.assertEqual(second['p:c1']['post_bet_raise'],1)
        self.assertEqual(second['p:c1']['show'],1)
        self.assertEqual(second['p:b1']['saw_flop'],1)
    def test_storage_dedup(self):
        conn=connect(':memory:')
        a=import_text(conn,SAMPLE,'r1')
        b=import_text(conn,SAMPLE,'r1')
        self.assertEqual(a[0],2)
        self.assertEqual(b[0],0)
        st={r['key']:r for r in stats_table(conn)}
        self.assertEqual(st['p:a1']['hands'],2)
        self.assertEqual(st['p:a1']['pfr'],1)
        self.assertEqual(st['p:c1']['vpip'],2)
        self.assertEqual(st['p:c1']['f3bet_opp'],1)
        self.assertEqual(percent(1,2),'50.0%')
    def test_incomplete_hand_excluded(self):
        conn=connect(':memory:')
        count,*_=import_text(conn,SAMPLE.split('"-- ending hand #2')[0],'r2')
        self.assertEqual(count,1)

if __name__=='__main__':unittest.main()
