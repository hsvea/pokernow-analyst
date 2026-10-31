import unittest
from postflop_solver import equity_for_pair, parse_sizes, solve_postflop
from gto_solver import cards

class PostflopStudyTests(unittest.TestCase):
    def test_sizings_validation(self):
        self.assertEqual(parse_sizes('75,33,75'),(.33,.75))
        for text in ['', '10,30,50,70', 'none', '0', '300']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_sizes(text)

    def test_equity_known_nuts_tie_and_river(self):
        board=cards('2c 3d 5h 8s Jc')
        self.assertEqual(equity_for_pair(board,cards('As Ah',2),cards('7c 6d',2)),1.0)
        self.assertEqual(equity_for_pair(board,cards('2s 4s',2),cards('As Ad',2)),0.0)
        self.assertEqual(equity_for_pair(cards('As Ks Qs Js Ts'),cards('2c 3d',2),cards('4c 5d',2)),0.5)

    def test_turn_runout_exact_and_repeatable_flop(self):
        b=cards('Ah 7d 2c 9s')
        a=cards('As Qs',2); v=cards('Kc Kh',2)
        e=equity_for_pair(b,a,v)
        self.assertEqual(e,equity_for_pair(b,a,v,500))
        self.assertGreaterEqual(e,0.0); self.assertLessEqual(e,1.0)
        f=cards('Ah 7d 2c')
        self.assertEqual(equity_for_pair(f,a,v,60),equity_for_pair(f,a,v,60))

    def test_river_tie_ev_and_strategies(self):
        x=solve_postflop('As Ks Qs Js Ts',100,300,'2c3d','4c5d',
                         sizes_text='33,75',iterations=10000)
        self.assertAlmostEqual(x.mean_ev,50.0,delta=3.0)
        self.assertEqual(x.metadata['game'],'single-street')
        self.assertFalse(x.metadata['future_betting'])
        for row in x.strategy_a+x.strategy_b:
            self.assertAlmostEqual(sum(row['actions'].values()),100.0,places=4)
            for val in row['actions'].values():
                self.assertGreaterEqual(val,-1e-6)
                self.assertLessEqual(val,100.00001)

    def test_five_to_three_cards_and_raise_choice(self):
        for board in ('Ah 7d 2c','Ah 7d 2c 9s','Ah 7d 2c 9s Kd'):
            with self.subTest(board=board):
                x=solve_postflop(board,100,300,'AsQs,AcQc,KsQs','JcJd,TcTd,8h8c',
                                 iterations=1000,max_runouts=40)
                self.assertEqual(len(x.board),len(board.split()))
                self.assertEqual(x.pairs,9)
                self.assertTrue(all('CHECK' in row['actions'] for row in x.strategy_a))
                self.assertIn('BET 33%',x.strategy_a[0]['actions'])

    def test_invalid_inputs_and_card_removal(self):
        args=('Ah 7d 2c',100,300,'AsQs','AsQs')
        with self.assertRaisesRegex(ValueError,'совместимых'):
            solve_postflop(*args,iterations=1000)
        with self.assertRaises(ValueError):
            solve_postflop('Ah 7d',100,300,'AsQs','KhKd',iterations=1000)
        with self.assertRaises(ValueError):
            solve_postflop('Ah 7d 2c',100,-100,'AsQs','KhKd',iterations=1000)

    def test_repeatable_seed(self):
        args=('Ah 7d 2c',100,300,'AsQs,AcQc','KhKd,KsKc')
        x=solve_postflop(*args,iterations=1100,seed=44)
        y=solve_postflop(*args,iterations=1100,seed=44)
        self.assertEqual(x.mean_ev,y.mean_ev)
        self.assertEqual(x.strategy_a,y.strategy_a)

if __name__=='__main__':unittest.main()
