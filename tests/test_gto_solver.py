import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gto_solver import cards, rank7, expand_class, parse_range, solve_river, PRESETS


class GTOParserTests(unittest.TestCase):
    def test_valid_and_invalid_cards(self):
        self.assertEqual(cards('Ah, 10s 2c 4d Kd', 5),('Ah','Ts','2c','4d','Kd'))
        for s in ('Ah Ah 2c 3s 4d', 'Ah A3 2c 3s 4d'):
            with self.assertRaises(ValueError):
                cards(s, 5)
    def test_hand_classes(self):
        self.assertEqual(len(expand_class('AA')),6)
        self.assertEqual(len(expand_class('AKs')),4)
        self.assertEqual(len(expand_class('AKo')),12)
        self.assertEqual(len(expand_class('AK')),16)
        self.assertEqual(len(expand_class('99+')),36)
        self.assertEqual(len(expand_class('AJs+')),12)
        self.assertEqual(len(expand_class('A2s-A5s')),16)
        self.assertEqual(len(expand_class('99-77')),18)
        self.assertEqual(len(expand_class('AhKd')),1)
    def test_ranges_account_for_board_cards(self):
        r=parse_range('AA:0.2,AKs:0.7',cards('Ah 7d 2c 9s Kd',5))
        self.assertTrue(all('Ah' not in c and 'Kd' not in c for c in r))
        self.assertEqual(r[tuple(sorted(('Ac','Ad')))],0.2)
        self.assertEqual(r[tuple(sorted(('As','Ks')))],0.7)
    def test_rank(self):
        sf=rank7(cards('As Ks Qs Js Ts 2d 3d',7))
        four=rank7(cards('As Ah Ad Ac 2d Kc 4c',7))
        full=rank7(cards('As Ah Ad 2s 2d Kc 4c',7))
        flush=rank7(cards('As Ks 8s 4s 2s 3d 9h',7))
        straight=rank7(cards('As 2h 3d 4c 5s 9c Qd',7))
        trips=rank7(cards('As Ah Ad Ks Qh 8c 4c',7))
        two=rank7(cards('As Ah Kd Ks Qh 8c 4c',7))
        pair=rank7(cards('As Ah Kd Qs 9h 8c 4c',7))
        high=rank7(cards('As Kh Qd 9s 8h 7c 4c',7))
        self.assertEqual([x[0] for x in (sf,four,full,flush,straight,trips,two,pair,high)],
                         list(range(8,-1,-1)))
        self.assertTrue(sf>four>full>flush>straight>trips>two>pair>high)
        self.assertEqual(straight, (4,5))
    def test_invalid_range(self):
        with self.assertRaises(ValueError):
            parse_range('FOO',cards('Ah 7d 2c 9s Kd',5))
        with self.assertRaises(ValueError):
            parse_range('AKs:7',cards('Ah 7d 2c 9s Kd',5))


class GTOEquilibriumTests(unittest.TestCase):
    def test_solution_probability_and_small_gap(self):
        x=solve_river('Ah 7d 2c 9s Kd',100,50,
                      PRESETS['Тайтовый'],PRESETS['Средний'],1200)
        self.assertGreater(x.pairs,1000)
        self.assertGreater(x.mean_ev,0)
        self.assertLess(x.mean_ev,150)
        self.assertLess(x.br_gap,.15)
        for row in x.strategy:
            self.assertGreaterEqual(row['bet_pct'],0)
            self.assertLessEqual(row['bet_pct'],100)
            self.assertAlmostEqual(row['bet_pct']+row['check_pct'],100,places=7)
        for row in x.defender:
            self.assertGreaterEqual(row['call_pct'],0)
            self.assertLessEqual(row['call_pct'],100)
    def test_known_stronger_hand_has_pot_ev(self):
        # Each player holds one specific compatible hand; A always beats B.
        s=solve_river('2c 3d 5h 8s Jc',100,50,'AsAh','7c6d',800)
        self.assertAlmostEqual(s.mean_ev,100,delta=.1)
        self.assertLess(s.br_gap,.1)
    def test_tie_has_half_pot(self):
        s=solve_river('As Ks Qs Js Ts',100,50,'2c3d','4c5d',800)
        self.assertAlmostEqual(s.mean_ev,50,delta=.1)
        self.assertLess(s.br_gap,.1)
    def test_zero_pair_rejected(self):
        with self.assertRaises(ValueError):
            solve_river('Ah 7d 2c 9s Kd',100,50,'AsQs','AsQs',200)

if __name__=='__main__':
    unittest.main()

class TestCompletedRiverBoards(unittest.TestCase):
    def test_finds_only_completed_rivers(self):
        from gto_solver import completed_river_boards
        fixture='\n'.join([
            '"-- starting hand #1 --",t',
            '"Flop: [As, 2h, 7h]",t',
            '"Turn: As, 2h, 7h [4c]",t',
            '"River: As, 2h, 7h, 4c [9h]",t',
            '"-- ending hand #1 --",t',
            '"-- starting hand #2 --",t',
            '"River: As, 2h, 7h, 4c [9h]",t',
        ])
        self.assertEqual(completed_river_boards(fixture), [('As','2h','7h','4c','9h')])
