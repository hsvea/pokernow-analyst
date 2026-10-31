"""Offline paired-seed, equal-world-budget audit of v7 and v8 private hand sampling.

A benchmark is not a proof of broad convergence; report failures as failures.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from statistics import mean
from multistreet_solver import solve_multistreet,audit_saved_multistreet
from gto_solver import cards, parse_range


def compare_private_sampling(kwargs, *, iterations=650, seeds=(9,21,37), max_worlds=12000):
    """Compare private random vs systematic with same chance and epoch budget."""
    kw=dict(kwargs)
    for key in ('iterations','seed','private_sampling','averaging','chance_sampling','exact_river','inspect_runout'):
        kw.pop(key,None)
    board=cards(kw['board_text'])
    if len(board) not in (3,4):
        raise ValueError('Сравнение v8 рассчитано для флопа/тёрна; ривер использует точный перебор пар')
    if iterations<200 or iterations>10000:
        raise ValueError('Итерации для сравнения: 200–10000')
    if not seeds or len(seeds)>6:
        raise ValueError('Допускается 1–6 seed')
    ra=parse_range(kw['a_range'],board); rb=parse_range(kw['b_range'],board)
    pairs=sum(not set(a)&set(b) for a in ra for b in rb)
    if pairs>6:
        raise ValueError('Для точного сравнения ограничь диапазоны до 6 совместимых пар')
    results=[]
    for seed in seeds:
        runs={}
        for mode in ('random','systematic'):
            start=time.perf_counter()
            r=solve_multistreet(**kw,iterations=iterations,seed=seed,
                                averaging='linear',chance_sampling='stratified',
                                private_sampling=mode,exact_river='never')
            train=time.perf_counter()-start
            diag=audit_saved_multistreet(r,max_worlds=max_worlds)
            runs[mode]={'nashconv':round(diag.nashconv,6),
                        'exploitability':round(diag.exploitability,6),
                        'missing_infosets':diag.missing_infosets,
                        'world_updates':r.metadata['world_updates'],
                        'training_seconds':round(train,4)}
        results.append({'seed':seed,'v7_random':runs['random'],'v8_systematic':runs['systematic']})
    a=mean(r['v7_random']['nashconv'] for r in results)
    b=mean(r['v8_systematic']['nashconv'] for r in results)
    return {
        'type':'v8_offline_seeded_equal_worlds',
        'scope':'fixed_bounded_hu_game_not_full_NLHE',
        'board':kw['board_text'], 'iterations_per_seed':iterations,
        'joint_private_pairs':pairs,'seeds':list(seeds),'results':results,
        'mean_nashconv_v7':round(a,6),'mean_nashconv_v8':round(b,6),
        'mean_reduction_pct':round((a-b)/a*100,3) if a>1e-12 else None,
        'guarantee':'none; seed/sample dependent, improvement not guaranteed',
    }


if __name__=='__main__':
    data=compare_private_sampling(dict(board_text='Ah Kd 7c 9s',pot=100,stack=80,
        a_range='AcQc,JsJh',b_range='KcQc,TsTd',flop_sizes='50',
        turn_sizes='50',river_sizes='50'),iterations=650)
    file=Path('examples/v8_sample_comparison.json')
    file.parent.mkdir(parents=True,exist_ok=True)
    file.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(data,indent=2,ensure_ascii=False))
