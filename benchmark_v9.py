"""Equal-world comparison of private pair coverage, not equilibrium quality."""
import argparse
import json
from pathlib import Path
from multistreet_solver import solve_multistreet


def compare_coverage(kwargs, iterations=650, seeds=(9, 21)):
    args = dict(kwargs)
    for key in ('iterations', 'seed', 'private_sampling', 'exact_river'):
        args.pop(key, None)
    rows = []
    for seed in seeds:
        for mode in ('systematic', 'balanced'):
            result = solve_multistreet(**args, iterations=iterations, seed=seed,
                                      private_sampling=mode, exact_river='never')
            rows.append({'seed': seed, 'mode': mode, 'world_updates': result.metadata['world_updates'],
                         **result.metadata['pair_coverage']})
    return {'scope': 'private-pair coverage, not NashConv or proof of equilibrium', 'results': rows}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--iterations', type=int, default=650)
    p.add_argument('--output', default='examples/v9_coverage_reconstructed.json')
    args = p.parse_args()
    report = compare_coverage(dict(board_text='Ah Kd 7c 9s', pot=100, stack=80,
        a_range='AcQc:1,JsJh:0.001,TsTh:0.001', b_range='KcQc:1,TsTd:0.001,8s8h:0.001',
        flop_sizes='50', turn_sizes='50', river_sizes='50'), iterations=args.iterations)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
