"""Reproducible, offline CFR+ convergence comparisons for bounded HU models.

The baseline reproduces v6's uniform-weight / independent-random-world sampler.
NashConv is computed by exact exhaustive best responses in the *same*
abstract game, never estimated from the training samples. LP verification
is optional and only available for very small river problems.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from gto_solver import cards, parse_range
from multistreet_solver import solve_multistreet, audit_saved_multistreet

MODES = {
    'v6_like_baseline': {'averaging': 'uniform', 'chance_sampling': 'random', 'exact_river': 'never'},
    'v7_improved': {'averaging': 'linear', 'chance_sampling': 'stratified', 'exact_river': 'auto'},
}


def run_benchmark(solver_args: dict, checkpoints=(300, 1000, 2000), *, include_lp=False,
                  max_worlds=12000, max_world_visits=12_000_000) -> dict:
    """Return comparable, exact-audited numbers, or an explicit error.

    Each checkpoint starts a fresh training session with the same seed. All
    modes train on identical ranges and betting trees. 'Iterations' represents
    epochs, but exact-river v7 evaluates each compatible pair per epoch, so
    world_updates are always reported to prevent unfair compute comparisons.
    """
    safe_args = dict(solver_args)
    for key in ('averaging', 'chance_sampling', 'exact_river', 'iterations'):
        safe_args.pop(key, None)
    checks = sorted(set(int(v) for v in checkpoints))
    if not checks or len(checks) > 8 or any(n < 200 or n > 10000 for n in checks):
        raise ValueError('Checkpoints must contain 1–8 values in [200, 10000]')
    report = {
        'type': 'offline_cfr_convergence_benchmark',
        'scope': 'exact_nashconv_for_fixed_bounded_hu_game_only',
        'input': safe_args,
        'checkpoints': checks,
        'important': ('Iterations are not equivalent computational budgets when exact-river '
                      'enumeration is enabled. Compare world_updates and training_seconds; '
                      'results are seed-dependent and NashConv need not decrease monotonically.'),
        'modes': {}, 'lp_reference': None,
    }
    for name, mode in MODES.items():
        entries=[]
        for n in checks:
            started=time.perf_counter()
            result=solve_multistreet(**safe_args, iterations=n, **mode)
            trained=time.perf_counter()-started
            audit=audit_saved_multistreet(result,max_worlds=max_worlds,max_world_visits=max_world_visits)
            entries.append({
                'iterations': n,
                'training_seconds': round(trained, 5),
                'world_updates': result.metadata['world_updates'],
                'nashconv': audit.nashconv,
                'exploitability': audit.exploitability,
                'profile_ev': audit.profile_ev,
                'br_a_ev': audit.br_a_ev,
                'br_b_ev': audit.br_b_ev,
                'missing_infosets': audit.missing_infosets,
                'worlds_evaluated': audit.worlds,
                'chance_scope': audit.chance_scope,
                'exact_river_training': result.metadata['exact_river_training'],
            })
        report['modes'][name]=entries
    baselines=report['modes']['v6_like_baseline']; improved=report['modes']['v7_improved']
    report['comparison']=[{
        'iterations':b['iterations'],
        'nashconv_reduction_pct':(100*(b['nashconv']-v['nashconv'])/b['nashconv']
                                  if b['nashconv'] > 1e-12 else None),
        'baseline_nashconv':b['nashconv'],
        'v7_nashconv':v['nashconv'],
        'baseline_world_updates':b['world_updates'],
        'v7_world_updates':v['world_updates'],
    } for b,v in zip(baselines,improved)]
    if include_lp:
        board=cards(safe_args['board_text'])
        if len(board)!=5:
            report['lp_reference']={'status':'unavailable_on_nonriver'}
        else:
            try:
                from exact_reference import solve_reference_lp
                from multistreet_solver import parse_street_sizes
                ranges_a=parse_range(safe_args['a_range'],board)
                ranges_b=parse_range(safe_args['b_range'],board)
                sizes=parse_street_sizes(safe_args.get('flop_sizes','50'),
                                         safe_args.get('turn_sizes','75'),
                                         safe_args.get('river_sizes','75'))
                lp=solve_reference_lp(board,float(safe_args['pot']),
                                      float(safe_args['stack']),sizes['R'],
                                      float(safe_args.get('raise_factor',2.5)),
                                      list(ranges_a),list(ranges_b),
                                      list(ranges_a.values()),list(ranges_b.values()))
                report['lp_reference']=asdict(lp)
                report['lp_reference']['v7_last_ev_abs_error']=(
                    abs(improved[-1]['profile_ev']-lp.equilibrium_ev))
                report['lp_reference']['lp_inside_best_response_bounds']=(
                    improved[-1]['br_b_ev']-1e-7<=lp.equilibrium_ev<=improved[-1]['br_a_ev']+1e-7)
            except (ValueError,RuntimeError) as e:
                report['lp_reference']={'status':'unavailable','reason':str(e)}
    return report


def main():
    parser=argparse.ArgumentParser(description='Offline CFR convergence benchmark (no live tables)')
    parser.add_argument('--board',default='Ah Kd 7c 9s 2d')
    parser.add_argument('--a-range',default='AcQc,JsJh')
    parser.add_argument('--b-range',default='KcQc,TsTd')
    parser.add_argument('--pot',type=float,default=100)
    parser.add_argument('--stack',type=float,default=80)
    parser.add_argument('--flop-sizes',default='50')
    parser.add_argument('--turn-sizes',default='50')
    parser.add_argument('--river-sizes',default='50')
    parser.add_argument('--raise-factor',type=float,default=2.5)
    parser.add_argument('--seed',type=int,default=9)
    parser.add_argument('--checkpoints',default='300,1000,2000')
    parser.add_argument('--lp',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    kwargs=dict(board_text=args.board,pot=args.pot,stack=args.stack,
                a_range=args.a_range,b_range=args.b_range,flop_sizes=args.flop_sizes,
                turn_sizes=args.turn_sizes,river_sizes=args.river_sizes,
                raise_factor=args.raise_factor,seed=args.seed)
    report=run_benchmark(kwargs,tuple(map(int,args.checkpoints.split(','))),include_lp=args.lp)
    rendered=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(rendered+'\n',encoding='utf-8')
        print('Saved:',args.output)
    else:
        print(rendered)


if __name__=='__main__':main()
