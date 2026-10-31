import unittest
from multistreet_solver import balanced_distribution, solve_multistreet
from benchmark_v9 import compare_coverage

BASE=dict(board_text='Ah Kd 7c 9s',pot=100,stack=80,a_range='AcQc:1,JsJh:0.001',
          b_range='KcQc:1,TsTd:0.001',flop_sizes='50',turn_sizes='50',river_sizes='50')

class CoverageTests(unittest.TestCase):
    def test_importance_expectation(self):
        weights=[1,0.01,0.0001]
        q,m=balanced_distribution(weights)
        values=[-17,4,90]
        self.assertAlmostEqual(sum(q),1)
        self.assertAlmostEqual(sum(a*b*v for a,b,v in zip(q,m,values)),sum(w*v for w,v in zip(weights,values))/sum(weights))
        self.assertTrue(all(x>=0.4/3 for x in q))

    def test_deterministic_and_bounded_coverage(self):
        a=solve_multistreet(**BASE,iterations=200,seed=9,private_sampling='balanced')
        b=solve_multistreet(**BASE,iterations=200,seed=9,private_sampling='balanced')
        self.assertEqual(a.root_strategies,b.root_strategies)
        c=a.metadata['pair_coverage']
        self.assertEqual(a.metadata['world_updates'],200)
        self.assertEqual(c['visited'],c['eligible'])
        self.assertGreater(c['ess'],0)
        self.assertLessEqual(c['ess'],200.00001)
        self.assertAlmostEqual(c['target_mass_pct'],100)

    def test_equal_budget_comparison(self):
        r=compare_coverage(BASE,iterations=200,seeds=(1,))
        self.assertEqual([x['world_updates'] for x in r['results']],[200,200])
        self.assertEqual({x['mode'] for x in r['results']},{'systematic','balanced'})

    def test_more_than_40_combos_allowed(self):
        r=solve_multistreet(**{**BASE,'a_range':'22+,AKs','b_range':'QcJc'},iterations=200,seed=9,private_sampling='balanced')
        self.assertGreater(r.n_a,40)
        self.assertLessEqual(r.n_a,80)

    def test_range_cap_retained(self):
        with self.assertRaisesRegex(ValueError,'80'):
            solve_multistreet(**{**BASE,'a_range':'22+,AK,AQ,AJ'},iterations=200)
