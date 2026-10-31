import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from multistreet_solver import (solve_multistreet,parse_street_sizes,
                                terminal_a_equity)

A='AsKs,AcKc,QcQd,JcJd'
B='KsQs,KcQc,9h9s,ThTd'

class MultiStreetTests(unittest.TestCase):
    def test_payoff_accounting(self):
        # A risks own chips and gets the full existing pot + B's chips.
        self.assertEqual(terminal_a_equity(100,25,25,1),125)
        self.assertEqual(terminal_a_equity(100,25,25,0),-25)
        self.assertEqual(terminal_a_equity(100,25,25,.5),50)
        self.assertEqual(terminal_a_equity(100,0,0,.5),50)

    def test_validation(self):
        self.assertEqual(parse_street_sizes('33,75','50','100')['F'],(.33,.75))
        with self.assertRaises(ValueError):parse_street_sizes('33,75,125','50','100')
        with self.assertRaises(ValueError):solve_multistreet('Ah Ah 2c',100,100,A,B,iterations=200)
        with self.assertRaises(ValueError):solve_multistreet('Ah 7d 2c',0,100,A,B,iterations=200)
        with self.assertRaises(ValueError):solve_multistreet('Ah 7d 2c',100,100,A,B,iterations=99)

    def test_all_three_streets_and_strategy_probabilities(self):
        x=solve_multistreet('Ah 7d 2c',100,200,A,B,iterations=320,seed=4)
        self.assertGreater(x.public_nodes['F'],0)
        self.assertGreater(x.public_nodes['T'],0)
        self.assertGreater(x.public_nodes['R'],0)
        self.assertTrue(x.metadata['future_cards_not_visible_in_earlier_infosets'])
        self.assertTrue(x.metadata['all_remaining_streets'])
        self.assertGreater(x.pairs,1)
        self.assertEqual(len(x.flop_b_responses),1)
        for hand in x.root_strategies:
            self.assertAlmostEqual(sum(hand['actions'].values()),100.0,places=5)
            self.assertTrue(all(0<=v<=100 for v in hand['actions'].values()))
        for r in x.flop_b_responses:
            self.assertAlmostEqual(sum(r['actions'].values()),100,places=5)

    def test_two_sizes_and_posterior_normalization(self):
        x=solve_multistreet('Ah 7d 2c',100,200,A,B,
                            flop_sizes='33,75',turn_sizes='75,100',
                            river_sizes='33,75',iterations=240)
        self.assertEqual(set(x.posterior),{'BET 33%','BET 75%'})
        self.assertEqual(x.metadata['max_bet_sizes_per_street'],2)
        for item in x.posterior.values():
            self.assertGreaterEqual(item['joint_weight'],0)
            self.assertLessEqual(item['joint_weight'],1)
            for who in ('A','B'):
                if item[who]:
                    self.assertLessEqual(sum(c['probability_pct'] for c in item[who]),100.001)

    def test_turn_starts_on_turn_and_river_starts_on_river(self):
        turn=solve_multistreet('Ah 7d 2c 9s',100,150,A,B,iterations=240)
        self.assertEqual(turn.public_nodes.get('F',0),0)
        self.assertGreater(turn.public_nodes.get('T',0),0)
        self.assertGreater(turn.public_nodes.get('R',0),0)
        river=solve_multistreet('Ah 7d 2c 9s 4d',100,150,A,B,iterations=240)
        self.assertEqual(river.public_nodes.get('F',0),0)
        self.assertEqual(river.public_nodes.get('T',0),0)
        self.assertGreater(river.public_nodes.get('R',0),0)

    def test_known_hand_showdown_river(self):
        s=solve_multistreet('2c 3d 5h 8s Jc',100,50,'AsAh','7c6d',iterations=700)
        self.assertAlmostEqual(s.mean_ev,100,delta=1.5)
        tie=solve_multistreet('As Ks Qs Js Ts',100,50,'2c3d','4c5d',iterations=700)
        self.assertAlmostEqual(tie.mean_ev,50,delta=1.5)

    def test_deterministic_seed(self):
        args=dict(board_text='Ah 7d 2c',pot=100,stack=120,
                  a_range='AsKs,AcKc',b_range='KsQs,KcQc',iterations=220,seed=7)
        x=solve_multistreet(**args)
        y=solve_multistreet(**args)
        self.assertEqual(x.mean_ev,y.mean_ev)
        self.assertEqual(x.root_strategies,y.root_strategies)
        self.assertEqual(x.posterior,y.posterior)

    def test_runout_inspection_does_not_change_flop_strategy(self):
        base=dict(board_text='Ah 7d 2c',pot=100,stack=300,
                  a_range=A,b_range=B,flop_sizes='33',turn_sizes='50',
                  river_sizes='75',iterations=350,seed=900)
        first=solve_multistreet(**base,inspect_runout='9s Kd')
        second=solve_multistreet(**base,inspect_runout='4s 6h')
        self.assertEqual(first.root_strategies,second.root_strategies)
        self.assertEqual(first.mean_ev,second.mean_ev)
        self.assertEqual(first.public_nodes,second.public_nodes)
        self.assertGreater(len(first.example_path),1)
        self.assertEqual(first.example_path[1]['board'],'Ah 7d 2c 9s')
        with self.assertRaises(ValueError):
            solve_multistreet(**base,inspect_runout='Ah')

    def test_all_in_stops_future_betting_on_inspected_line(self):
        s=solve_multistreet('Ah 7d 2c',100,20,A,B,iterations=240,inspect_runout='9s Kd')
        self.assertEqual(len(s.example_path),1)
        # Other branches can still check all the way to the river.
        self.assertGreater(s.public_nodes.get('R',0),0)

    def test_blocker_conditioning(self):
        # A holds AsKs: incompatible B AsQs must be excluded before action update.
        s=solve_multistreet('2c 3d 5h 8s Jc',100,50,'AsKs','AsQs,KdQd',iterations=250)
        self.assertEqual(s.pairs,1)
        self.assertEqual(s.n_a,1)
        self.assertEqual(s.n_b,2)

if __name__ == '__main__':unittest.main()
