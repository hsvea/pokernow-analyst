"""Independent minimax LP benchmark for tiny river abstractions.

Compared with CFR+ this directly constructs the NORMAL-FORM payoff matrix
(over pure contingent plans) and solves a two-player zero-sum LP using scipy.
Limited to <=2 exact two-card combinations per player and ONE bet size.
It's a reference for this simplified tree ONLY, not for unrestricted NLHE.
SciPy is optional and is imported only when this module is used.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from gto_solver import rank7
from river_certification import RiverGame


@dataclass(frozen=True)
class LPReference:
    equilibrium_ev: float
    duality_gap: float
    rows: int
    cols: int
    status: str = 'exact_minimax_lp_for_tiny_river_game'


def _infosets(game, who):
    bet_label, bet=game.bet_options()[0]
    to=game.raise_to(bet)
    if who=='A':
        states=[('ROOT', ('R',), 0.0),
                ('A_VS_B',('R','A:CHECK',f'B:{bet_label}'),bet)]
        if to is not None:
            states.append(('A_VS_B_R',('R',f'A:{bet_label}',f'B:RAISE {to:.6f}'),to))
    else:
        states=[('B_CHECK',('R','A:CHECK'),0.0),
                ('B_VS_A',('R',f'A:{bet_label}'),bet)]
        if to is not None:
            states.append(('B_VS_A_R',('R','A:CHECK',f'B:{bet_label}',f'A:RAISE {to:.6f}'),to))
    return [(state[1],tuple(action for action,_ in game.actions(state)[1])) for state in states]


def _hand_plans(game, who):
    infosets=_infosets(game,who)
    return [dict(zip((hist for hist,_ in infosets),chosen))
            for chosen in product(*(actions for _,actions in infosets))]


def _pure_ev(game, pa, pb, win):
    state=('ROOT',('R',),0.)
    while state[0] not in ('FOLD','SHOW'):
        turn,actions=game.actions(state)
        chosen=(pa if turn=='A' else pb)[state[1]]
        state=dict(actions)[chosen]
    if state[0]=='FOLD':return state[1]
    invest=state[1]
    return (game.pot+2*invest)*win-invest


def solve_reference_lp(board,pot,stack,sizes,raise_factor,
                       hands_a,hands_b,weights_a,weights_b):
    try:
        import numpy as np
        from scipy.optimize import linprog
    except ImportError as e:
        raise RuntimeError('Для независимого LP-эталона установи: py -3 -m pip install scipy') from e
    hands_a=list(hands_a);hands_b=list(hands_b)
    weights_a=list(weights_a);weights_b=list(weights_b)
    if len(hands_a)>2 or len(hands_b)>2:
        raise ValueError('LP-эталон ограничен двумя конкретными комбинациями на игрока')
    game=RiverGame(board,pot,stack,sizes,raise_factor)
    if len(game.bet_options())!=1:
        raise ValueError('LP-эталон поддерживает ровно один размер ставки')
    a_plans=_hand_plans(game,'A');b_plans=_hand_plans(game,'B')
    npa=len(a_plans);npb=len(b_plans)
    global_a=list(product(range(npa),repeat=len(hands_a)))
    global_b=list(product(range(npb),repeat=len(hands_b)))
    if len(global_a)>1000 or len(global_b)>1000:
        raise ValueError('Матрица слишком большая')
    a_idxs=np.array(global_a,dtype=int)
    b_idxs=np.array(global_b,dtype=int)
    M=np.zeros((len(global_a),len(global_b)),dtype=float)
    mass=0.
    for i,a in enumerate(hands_a):
        for j,b in enumerate(hands_b):
            if not set(a).isdisjoint(b):continue
            w=weights_a[i]*weights_b[j]
            if w<=0:continue
            mass+=w
            ra=rank7(tuple(board)+a);rb=rank7(tuple(board)+b)
            win=1. if ra>rb else 0.5 if ra==rb else 0.
            local=np.array([[_pure_ev(game,pa,pb,win) for pb in b_plans]
                            for pa in a_plans],dtype=float)
            M+=w*local[a_idxs[:,i,None],b_idxs[None,:,j]]
    if not mass: raise ValueError('Диапазоны не имеют совместимых комбинаций')
    M/=mass
    na,nb=M.shape
    # A maximizes v s.t. x^T M >= v (for every B pure strategy).
    A_ub=np.column_stack((-M.T,np.ones(nb)))
    c=np.zeros(na+1);c[-1]=-1
    result_a=linprog(c,A_ub=A_ub,b_ub=np.zeros(nb),
                     A_eq=np.array([[1.]*na+[0.]]),b_eq=[1.],
                     bounds=[(0,None)]*na+[(None,None)],method='highs')
    # B minimizes w s.t. M y <= w (for every A pure strategy).
    B_ub=np.column_stack((M,-np.ones(na)))
    c2=np.zeros(nb+1);c2[-1]=1
    result_b=linprog(c2,A_ub=B_ub,b_ub=np.zeros(na),
                     A_eq=np.array([[1.]*nb+[0.]]),b_eq=[1.],
                     bounds=[(0,None)]*nb+[(None,None)],method='highs')
    if not (result_a.success and result_b.success):
        raise RuntimeError('LP optimizer failed: '+str(result_a.message)+' / '+str(result_b.message))
    lower=float(result_a.x[-1]);upper=float(result_b.x[-1])
    duality_gap=max(0.,upper-lower)
    return LPReference(equilibrium_ev=(upper+lower)/2,duality_gap=duality_gap,
                       rows=na,cols=nb)
