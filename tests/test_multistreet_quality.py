"""Independent diagnostic regression tests; stdlib only."""
import unittest

from gto_solver import cards
from river_certification import evaluate_river
from multistreet_quality import evaluate_multistreet, AuditLimitError
from multistreet_solver import solve_multistreet, audit_saved_multistreet

SIZES={'F':(.5,), 'T':(.5,), 'R':(.5,)}


class MultiStreetQualityTests(unittest.TestCase):
    def setUp(self):
        self.board=cards('Ah Kd 7c 2s 9h')
        self.ha=[cards('Ac Qc')]
        self.hb=[cards('Jd Td')]

    def evaluate(self, board=None, get_policy=None, **kwargs):
        return evaluate_multistreet(board or self.board,100,80,SIZES,2.5,
                                    self.ha,self.hb,[1],[1],get_policy or (lambda *args:None),**kwargs)

    def test_river_matches_independent_existing_evaluator(self):
        audit=self.evaluate()
        river=evaluate_river(self.board,100,80,SIZES['R'],2.5,self.ha,self.hb,[1],[1],lambda *args:None)
        for attr,other in [('profile_ev',river.profile_ev),('br_a_ev',river.br_a_ev),
                           ('br_b_ev',river.br_b_ev),('nashconv',river.nashconv)]:
            self.assertAlmostEqual(getattr(audit,attr),other,places=8)

    def test_turn_exact_full_deck(self):
        audit=self.evaluate(board=self.board[:4])
        self.assertEqual(audit.worlds,44)
        self.assertEqual(audit.chance_scope,'full_52_card_deck')
        self.assertLessEqual(audit.br_b_ev,audit.profile_ev+1e-8)
        self.assertGreaterEqual(audit.br_a_ev,audit.profile_ev-1e-8)

    def test_flop_exact_full_deck(self):
        audit=self.evaluate(board=self.board[:3])
        self.assertEqual(audit.worlds,45*44)
        self.assertEqual(audit.chance_scope,'full_52_card_deck')
        self.assertGreaterEqual(audit.nashconv,-1e-8)

    def test_reduced_chance_is_explicitly_not_full_deck(self):
        d=self.evaluate(board=self.board[:3],chance_deck=('2s','9h','3h','4c','5c','6d'))
        self.assertEqual(d.worlds,30)
        self.assertEqual(d.chance_scope,'reduced_chance_test_deck')

    def test_no_clairvoyant_response_to_opponents_hidden_hand(self):
        board=cards('Ah Kd 7c 2s 9h')
        a=[cards('As Qs')]
        b=[cards('Jc Tc'),cards('Kh Kc')]
        # B always calls the shove after A bets, and checks back after A checks.
        def b_strategy(who,vis,hist,idx,labels):
            if who=='B':
                if 'CALL' in labels:return {'CALL':1}
                if 'CHECK' in labels:return {'CHECK':1}
            return None
        result=evaluate_multistreet(board,100,50,SIZES,2.5,a,b,[1],[1,1],b_strategy)
        # Check has EV 50, bet has EV 50. Clairvoyantly betting winners alone
        # would yield EV 75, which must NOT be reachable for the real BR.
        self.assertAlmostEqual(result.br_a_ev,50.,places=8)

    def test_raise_folding_accounting_and_max_response(self):
        r=self.evaluate()
        self.assertGreaterEqual(r.br_a_ev,r.profile_ev-1e-8)
        self.assertLessEqual(r.br_b_ev,r.profile_ev+1e-8)
        self.assertAlmostEqual(r.exploitability,r.nashconv/2)

    def test_known_nuts_equilibrium_full_flop_runouts(self):
        # A holds all four aces and cannot be outdrawn on this flop.
        # Check/check, call enemy bets, fold when facing bets from A is NE.
        def equilibrium(who,visible,hist,idx,labels):
            if who=='A':
                if 'CHECK' in labels:return {'CHECK':1.}
                if 'CALL' in labels:return {'CALL':1.}
            if who=='B':
                if 'CHECK' in labels:return {'CHECK':1.}
                if 'FOLD' in labels:return {'FOLD':1.}
            return None
        d=evaluate_multistreet(cards('As Ah 2c'),100,80,SIZES,2.5,
            [cards('Ac Ad')],[cards('Kd Qd')],[1],[1],equilibrium)
        self.assertEqual(d.worlds,45*44)
        self.assertAlmostEqual(d.profile_ev,100.,places=6)
        self.assertAlmostEqual(d.nashconv,0.,places=6)

    def test_limits_never_produce_false_numbers(self):
        with self.assertRaises(AuditLimitError):
            self.evaluate(board=self.board[:3], max_worlds=200)
        with self.assertRaises(AuditLimitError):
            self.evaluate(board=self.board[:4], max_world_visits=20)

    def test_trained_strategy_is_auditable_without_mutation(self):
        r=solve_multistreet('Ah Kd 7c',100,80,'AcQc','JdTd',
                            flop_sizes='50',turn_sizes='50',river_sizes='50',iterations=200)
        before=[tuple(node.regret) for node in r._audit_state[0].values()]
        report=audit_saved_multistreet(r)
        after=[tuple(node.regret) for node in r._audit_state[0].values()]
        self.assertEqual(before,after)
        self.assertEqual(report.worlds,45*44)
        self.assertGreater(report.nashconv,0.)
        self.assertLessEqual(report.br_b_ev, report.profile_ev+1e-7)
        self.assertGreaterEqual(report.br_a_ev, report.profile_ev-1e-7)


if __name__=='__main__':unittest.main()
