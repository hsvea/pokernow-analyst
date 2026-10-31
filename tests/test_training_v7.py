import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from multistreet_solver import solve_multistreet,audit_saved_multistreet
from benchmark_training import run_benchmark

RIVER='Ah Kd 7c 9s 2d'
A='AcQc,JsJh'
B='KcQc,TsTd'
KW=dict(board_text=RIVER,pot=100,stack=80,a_range=A,b_range=B,
        flop_sizes='50',turn_sizes='50',river_sizes='50',seed=9)


class TestTrainingV7(unittest.TestCase):
    def test_exact_river_enumerates_every_pair_each_epoch(self):
        r=solve_multistreet(**KW,iterations=250)
        self.assertTrue(r.metadata['exact_river_training'])
        self.assertEqual(r.metadata['world_updates'],250*r.pairs)
        self.assertEqual(r.metadata['averaging'],'linear')
        self.assertEqual(r.metadata['chance_sampling'],'not_applicable')
        self.assertEqual(r.metadata['missing_eval_infosets'],0)

    def test_linear_exact_improves_specific_river_reference_case(self):
        old=solve_multistreet(**KW,iterations=1000,averaging='uniform',chance_sampling='random',exact_river='never')
        new=solve_multistreet(**KW,iterations=1000)
        self.assertLess(new.metadata['nashconv'],old.metadata['nashconv'])
        self.assertGreaterEqual(new.metadata['nashconv'],0.)
        self.assertLess(new.metadata['nashconv'],1.)

    def test_river_seed_does_not_change_exact_solution(self):
        kwargs={k:v for k,v in KW.items() if k!='seed'}
        x=solve_multistreet(**kwargs,iterations=400,seed=8)
        y=solve_multistreet(**kwargs,iterations=400,seed=21)
        self.assertAlmostEqual(x.metadata['nashconv'],y.metadata['nashconv'],places=10)
        self.assertEqual(x.root_strategies,y.root_strategies)

    def test_stratification_covers_single_combo_flop_by_1980_samples(self):
        kw={**KW,'board_text':'Ah Kd 7c','a_range':'AcQc','b_range':'JdTd'}
        r=solve_multistreet(**kw,iterations=2000)
        self.assertFalse(r.metadata['exact_river_training'])
        diag=audit_saved_multistreet(r)
        self.assertEqual(diag.missing_infosets,0)
        self.assertEqual(diag.worlds,1980)
        self.assertEqual(r.metadata['world_updates'],2000)

    def test_validation_and_explicit_fallback(self):
        for opts in ({'averaging':'other'}, {'chance_sampling':'other'}, {'exact_river':'other'}):
            with self.assertRaises(ValueError):solve_multistreet(**KW,iterations=250,**opts)
        with self.assertRaises(ValueError):
            solve_multistreet(**{**KW,'board_text':'Ah Kd 7c'},iterations=250,exact_river='always')

    def test_benchmark_measures_same_audited_game(self):
        report=run_benchmark(KW,checkpoints=(200,300))
        self.assertEqual(report['checkpoints'],[200,300])
        self.assertEqual(len(report['comparison']),2)
        for key in ('v7_improved','v6_like_baseline'):
            for point in report['modes'][key]:
                self.assertGreaterEqual(point['nashconv'],0)
                self.assertEqual(point['worlds_evaluated'],3)
                self.assertEqual(point['missing_infosets'],0)
                self.assertLessEqual(point['br_b_ev'],point['profile_ev']+1e-6)
                self.assertLessEqual(point['profile_ev'],point['br_a_ev']+1e-6)
        self.assertGreater(report['modes']['v7_improved'][0]['world_updates'],
                           report['modes']['v6_like_baseline'][0]['world_updates'])

if __name__=='__main__':unittest.main()
