import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from codex_review import build_review_prompt, review_with_codex, start_chatgpt_login
from multistreet_solver import solve_multistreet,audit_saved_multistreet

BASE=dict(board_text='Ah Kd 7c 9s',pot=100,stack=80,
          a_range='AcQc,JsJh',b_range='KcQc,TsTd',
          flop_sizes='50',turn_sizes='50',river_sizes='50',seed=9)

class TestV8Sampler(unittest.TestCase):
    def test_paired_enumerates_all_private_pairs(self):
        r=solve_multistreet(**BASE,iterations=250,private_sampling='paired')
        self.assertEqual(r.metadata['world_updates'],r.pairs*250)
        self.assertEqual(r.metadata['private_sampling'],'paired')
        self.assertIsNotNone(audit_saved_multistreet(r).nashconv)

    def test_systematic_deterministic_and_single_world(self):
        a=solve_multistreet(**BASE,iterations=250,private_sampling='systematic')
        b=solve_multistreet(**BASE,iterations=250,private_sampling='systematic')
        self.assertEqual(a.root_strategies,b.root_strategies)
        self.assertEqual(a.metadata['world_updates'],250)
        self.assertEqual(a.metadata['private_sampling'],'systematic')

    def test_bad_sampler_rejected(self):
        with self.assertRaisesRegex(ValueError,'private_sampling'):
            solve_multistreet(**BASE,iterations=250,private_sampling='wrong')

    def test_paired_combo_cap(self):
        with self.assertRaisesRegex(ValueError,'16'):
            solve_multistreet(**{**BASE,'a_range':'QQ+,AKs','b_range':'JJ+,AQs'},iterations=250,private_sampling='paired')

class FakeCodex:
    last=None
    def __init__(self):
        FakeCodex.last=self
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def thread_start(self,**kw):
        self.opts=kw
        return self
    def run(self,prompt,**kw):
        self.prompt=prompt
        self.run_opts=kw
        return SimpleNamespace(final_response='Проверка завершённой раздачи')
    def login_chatgpt(self):
        return SimpleNamespace(auth_url='https://example.com',wait=lambda: SimpleNamespace(success=True))
    def close(self):self.closed=True

class TestCodex(unittest.TestCase):
    def test_no_offline_report(self):
        with self.assertRaises(ValueError):build_review_prompt({},'question')
    def test_prompt_is_bounded(self):
        with self.assertRaises(ValueError):build_review_prompt({'gto':{'x':'a'*30000}},'question')
    def test_readonly_run_with_json_only(self):
        text=review_with_codex({'river_gto':{'board':'Ac Kd 7s 9h 2c','nashconv':0.5}},'Проверь',factory=FakeCodex)
        self.assertIn('Проверка',text)
        self.assertIn('read_only',str(FakeCodex.last.opts['sandbox']))
        self.assertNotIn('player_name',FakeCodex.last.prompt)
        self.assertIn('nashconv',FakeCodex.last.prompt)
    def test_login_returns_handle(self):
        client,handle=start_chatgpt_login(factory=FakeCodex)
        self.assertTrue(handle.wait().success)
        client.close()
        self.assertTrue(client.closed)

if __name__=='__main__':unittest.main()

class TestComparison(unittest.TestCase):
    def test_equal_budget_and_multiple_seeds(self):
        from benchmark_v8 import compare_private_sampling
        report=compare_private_sampling(BASE,iterations=250,seeds=(9,21))
        self.assertEqual(report['type'],'v8_offline_seeded_equal_worlds')
        self.assertEqual(len(report['results']),2)
        for run in report['results']:
            self.assertEqual(run['v7_random']['world_updates'],250)
            self.assertEqual(run['v8_systematic']['world_updates'],250)
            self.assertGreaterEqual(run['v7_random']['nashconv'],0)
            self.assertGreaterEqual(run['v8_systematic']['nashconv'],0)
    def test_codex_app_context_filters_live_state(self):
        from app import Analyst
        from types import SimpleNamespace
        dummy=SimpleNamespace(
          gto_context={'board':['Ah','Kd','7c','9s','2d']},
          postflop_context=None,
          multistreet_context={'nashconv':2.2},
          live={'players':[{'name':'secret name'}],'hole':['As','Ah']},
          history={'secret':'player data'})
        study=Analyst.codex_offline_studies(dummy)
        self.assertNotIn('secret name',str(study))
        self.assertNotIn('live',study)
        self.assertEqual(set(study),{'river_gto','multistreet_gto'})
