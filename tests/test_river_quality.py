import sys
import unittest
import importlib.util
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from gto_solver import cards, parse_range
from river_certification import RiverGame,evaluate_river
from multistreet_solver import solve_multistreet
from exact_reference import solve_reference_lp

BOARD=cards('2h 3h 5d 8s Jc')
A='AsKs,7c7d'
B='AcQc,6c6d'


def common():
    ra=parse_range(A,BOARD);rb=parse_range(B,BOARD)
    return list(ra),list(rb),list(ra.values()),list(rb.values())


class TestRiverBranches(unittest.TestCase):
    def test_a_bet_b_folds_and_b_raises_a_folds(self):
        game=RiverGame(BOARD,100,150,(.5,),2.5)
        root=game.actions(('ROOT',('R',),0.))
        self.assertEqual(root[0],'A')
        bet=dict(root[1])['BET 50%']
        self.assertEqual(dict(game.actions(bet)[1])['FOLD'],('FOLD',100.))
        r=dict(game.actions(bet)[1])['RAISE']
        self.assertEqual(dict(game.actions(r)[1])['FOLD'],('FOLD',-50.))
        self.assertEqual(dict(game.actions(r)[1])['CALL'],('SHOW',125.))

    def test_a_checks_b_bets_and_a_raises_b_folds(self):
        game=RiverGame(BOARD,100,150,(.5,),2.5)
        check=dict(game.actions(('ROOT',('R',),0.))[1])['CHECK']
        bet=dict(game.actions(check)[1])['BET 50%']
        self.assertEqual(dict(game.actions(bet)[1])['FOLD'],('FOLD',0.))
        raised=dict(game.actions(bet)[1])['RAISE']
        self.assertEqual(dict(game.actions(raised)[1])['FOLD'],('FOLD',150.))
        self.assertEqual(dict(game.actions(raised)[1])['CALL'],('SHOW',125.))

    def test_allin_disables_raises(self):
        game=RiverGame(BOARD,100,25,(.5,),2.5)
        bet=dict(game.actions(('ROOT',('R',),0.))[1])['BET 50%']
        self.assertEqual(tuple(k for k,_ in game.actions(bet)[1]),('FOLD','CALL'))


class TestQualityGuarantees(unittest.TestCase):
    def test_exact_br_brackets_profile_value(self):
        ha,hb,wa,wb=common()
        diag=evaluate_river(BOARD,100,150,(.5,),2.5,ha,hb,wa,wb,
                            lambda who,hist,i,legal:dict.fromkeys(legal,1))
        self.assertLessEqual(diag.br_b_ev,diag.profile_ev+1e-7)
        self.assertLessEqual(diag.profile_ev,diag.br_a_ev+1e-7)
        self.assertAlmostEqual(diag.nashconv,diag.br_a_ev-diag.br_b_ev)
        self.assertAlmostEqual(diag.exploitability,diag.nashconv/2)

    def test_known_certain_win_equilibrium(self):
        s=solve_multistreet('2c 3d 5h 8s Jc',100,50,'AsAh','7c6d',iterations=700)
        d=s.metadata
        self.assertAlmostEqual(d['profile_ev_exact'],100,delta=1.)
        self.assertLess(d['nashconv'],1.5)
        self.assertEqual(d['missing_eval_infosets'],0)

    def test_turn_and_flop_not_certified(self):
        for board in ['2h 3h 5d','2h 3h 5d 8s']:
            s=solve_multistreet(board,100,150,A,B,iterations=220,seed=5)
            self.assertIsNone(s.metadata['nashconv'])
            self.assertEqual(s.metadata['quality_scope'],'not_measured_multistreet')

    def test_fitted_river_policy_in_br_interval(self):
        s=solve_multistreet('2h 3h 5d 8s Jc',100,150,A,B,river_sizes='50',iterations=250,seed=21)
        d=s.metadata
        self.assertLessEqual(d['br_b_exact'],d['profile_ev_exact']+1e-7)
        self.assertLessEqual(d['profile_ev_exact'],d['br_a_exact']+1e-7)
        self.assertGreaterEqual(d['nashconv'],0.)


@unittest.skipUnless(importlib.util.find_spec("scipy"), "optional SciPy not installed")
class TestReferenceLP(unittest.TestCase):
    def test_lp_minimax_and_best_response_consistency(self):
        ha,hb,wa,wb=common()
        ref=solve_reference_lp(BOARD,100,150,(.5,),2.5,ha,hb,wa,wb)
        self.assertEqual((ref.rows,ref.cols),(144,144))
        self.assertLess(ref.duality_gap,1e-6)
        self.assertAlmostEqual(ref.equilibrium_ev,81.651376146789,places=5)
        solution=solve_multistreet('2h 3h 5d 8s Jc',100,150,A,B,river_sizes='50',iterations=2000,seed=7)
        d=solution.metadata
        self.assertLessEqual(d['br_b_exact']-1e-6,ref.equilibrium_ev)
        self.assertLessEqual(ref.equilibrium_ev,d['br_a_exact']+1e-6)
        self.assertLessEqual(abs(d['profile_ev_exact']-ref.equilibrium_ev),d['nashconv']+1e-5)
        self.assertLess(d['nashconv'],5.)

    def test_reference_pure_always_wins(self):
        b=cards('2c 3d 5h 8s Jc')
        ha=list(parse_range('AsAh',b));hb=list(parse_range('7c6d',b))
        ref=solve_reference_lp(b,100,50,(.5,),2.5,ha,hb,[1],[1])
        self.assertAlmostEqual(ref.equilibrium_ev,100,places=5)
        self.assertLess(ref.duality_gap,1e-5)

    def test_lp_explicit_rejects_large_cases(self):
        board=BOARD
        with self.assertRaises(ValueError):
            a=list(parse_range('AsKs,7c7d,9s9d',board))
            b=list(parse_range(B,board))
            solve_reference_lp(board,100,150,(.5,),2.5,a,b,[1]*len(a),[1]*len(b))

if __name__=='__main__':unittest.main()
