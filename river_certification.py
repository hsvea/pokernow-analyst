"""Exact best-response evaluation of the **river-only** v4 abstract betting tree.

This is a diagnostic of a *fixed abstract game* / fitted strategy, not a
certificate for unrestricted no-limit Hold'em. It explicitly evaluates missing
infosets under uniform fallback, making poor node coverage observable.

All payoffs use A's chip EV; NashConv = BR_A - BR_B, and exploitability
= NashConv/2 in two-player zero-sum games. No random samples in evaluation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Mapping

from gto_solver import rank7

EPS = 1e-10


@dataclass(frozen=True)
class RiverDiagnostic:
    profile_ev: float
    br_a_ev: float
    br_b_ev: float
    nashconv: float
    exploitability: float
    nashconv_pot_pct: float
    missing_infosets: int
    model: str = 'river_only_exact_br_fixed_abstract_game'


class RiverGame:
    def __init__(self, board, pot, stack, sizes, raise_factor):
        if len(board) != 5:
            raise ValueError('Точное NashConv доступно только для ривера (5 карт).')
        self.board = tuple(board)
        self.pot = float(pot)
        self.stack = float(stack)
        self.sizes = tuple(sizes)
        self.factor = float(raise_factor)
        if not (self.pot > 0 and self.stack > 0 and self.sizes and 2 <= self.factor <= 5):
            raise ValueError('Некорректные банк, стек или размеры ставок')

    def bet_options(self):
        return [(f'BET {int(round(p*100))}%', min(self.stack, self.pot*p))
                for p in self.sizes if min(self.stack, self.pot*p) > EPS]

    def raise_to(self, bet):
        val = min(self.stack, bet*self.factor)
        return val if val > bet + EPS else None

    def branch(self, state):
        """Return acting player and [(label, child)], child terminal:
        ('FOLD', chip_ev_for_A) or ('SHOW', total_investment_each).
        States: ('ROOT'|'B_CHECK'|'B_VS_A'|'A_VS_B'|'A_VS_B_R'|'B_VS_A_R', hist, bet)
        """
        phase, hist, bet = state
        actions = []
        options = self.bet_options()
        if phase == 'ROOT':
            actions.append(('CHECK', ('B_CHECK', hist+('A:CHECK',), 0.)))
            actions.extend((label, ('B_VS_A', hist+(f'A:{label}',), value)) for label,value in options)
            return 'A', actions
        if phase == 'B_CHECK':
            actions.append(('CHECK', ('SHOW', 0.)))
            actions.extend((label, ('A_VS_B', hist+(f'B:{label}',), value)) for label,value in options)
            return 'B', actions
        if phase == 'B_VS_A':
            actions = [('FOLD', ('FOLD', self.pot)), ('CALL', ('SHOW', bet))]
            to = self.raise_to(bet)
            if to is not None:
                actions.append(('RAISE', ('A_VS_B_R', hist+(f'B:RAISE {to:.6f}',), to)))
            return 'B', actions
        if phase == 'A_VS_B':
            actions = [('FOLD', ('FOLD', 0.)), ('CALL', ('SHOW', bet))]
            to = self.raise_to(bet)
            if to is not None:
                actions.append(('RAISE', ('B_VS_A_R', hist+(f'A:RAISE {to:.6f}',), to)))
            return 'A', actions
        raise ValueError('Unknown game state')

    def actions(self, state):
        """Corrected raising terminals (must remember first bet as well as raise total)."""
        phase, hist, bet = state
        if phase in ('A_VS_B_R', 'B_VS_A_R'):
            if phase == 'A_VS_B_R':
                # B raised original A bet. Search history for the initial BET label.
                first_label = next(item[2:] for item in hist if item.startswith('A:BET '))
                first_bet = dict(self.bet_options())[first_label]
                return 'A', [('FOLD', ('FOLD', -first_bet)), ('CALL', ('SHOW', bet))]
            # A raised original B bet after A checked.
            first_label = next(item[2:] for item in hist if item.startswith('B:BET '))
            first_bet = dict(self.bet_options())[first_label]
            return 'B', [('FOLD', ('FOLD', self.pot + first_bet)), ('CALL', ('SHOW', bet))]
        return self.branch(state)


def evaluate_river(board, pot, stack, sizes, raise_factor,
                   hands_a, hands_b, weights_a, weights_b,
                   get_policy: Callable[[str, tuple[str,...], int, tuple[str,...]], Mapping[str,float]]):
    """Exact EV and unilateral perfect-recall best responses for river game.

    get_policy(player, history, private_combo_index, legal_actions)->dict
    All posterior inference for BR conditions on observed action history,
    own cards and blockers; opponent hidden cards remain unknown.
    """
    game=RiverGame(board,pot,stack,sizes,raise_factor)
    hands_a=list(hands_a);hands_b=list(hands_b)
    wa=list(weights_a);wb=list(weights_b)
    ranks_a=[rank7(tuple(board)+h) for h in hands_a]
    ranks_b=[rank7(tuple(board)+h) for h in hands_b]
    edges=[]
    for i,a in enumerate(hands_a):
        for j,b in enumerate(hands_b):
            if set(a).isdisjoint(b) and wa[i]*wb[j]>0:
                win=1.0 if ranks_a[i]>ranks_b[j] else .5 if ranks_a[i]==ranks_b[j] else 0.0
                edges.append((i,j,wa[i]*wb[j],win))
    total_mass=sum(w for _,_,w,_ in edges)
    if total_mass<=0: raise ValueError('Диапазоны не имеют совместимых комбинаций')
    wins={(i,j):win for i,j,w,win in edges}
    root=('ROOT',('R',),0.)
    missing=set()
    policy_cache={}

    def policy(player, hist, index, labels):
        key=(player,hist,index,tuple(labels))
        if key not in policy_cache:
            raw=get_policy(player,hist,index,tuple(labels))
            if not raw:
                missing.add((player,hist,index))
                vec=[1/len(labels)]*len(labels)
            else:
                vals=[max(0.,float(raw.get(a,0.))) for a in labels]
                s=sum(vals)
                vec=[v/s for v in vals] if s>EPS else [1/len(labels)]*len(labels)
            policy_cache[key]=dict(zip(labels,vec))
        return policy_cache[key]

    def terminal_value(term, i,j):
        if term[0]=='FOLD':return float(term[1])
        assert term[0]=='SHOW'
        invest=term[1]
        return (game.pot+2*invest)*wins[(i,j)]-invest

    def profile(state,i,j):
        if state[0] in ('FOLD','SHOW'):
            return terminal_value(state,i,j)
        actor,options=game.actions(state)
        idx=i if actor=='A' else j
        probs=policy(actor,state[1],idx,tuple(a for a,_ in options))
        return sum(probs[a]*profile(child,i,j) for a,child in options)

    ev=sum(w*profile(root,i,j) for i,j,w,_ in edges)/total_mass

    def best_response(actor):
        # Enumerate own private hand, then correctly condition opponent's
        # hidden hand distribution through action histories. At our nodes
        # choose a SINGLE action for all opponent hands consistent with the
        # infoset, so this does not peek at opponent cards.
        target_a=(actor=='A')
        known=len(hands_a) if target_a else len(hands_b)
        opposite=len(hands_b) if target_a else len(hands_a)
        links=[{} for _ in range(known)]
        for i,j,w,_ in edges:
            k=i if target_a else j
            other=j if target_a else i
            links[k][other]=w

        def recurse(state, k, belief):
            if not belief:return 0.0
            if state[0] in ('FOLD','SHOW'):
                return sum(w*terminal_value(state,k,o) if target_a else
                           w*terminal_value(state,o,k) for o,w in belief.items())
            turn,options=game.actions(state)
            labels=tuple(a for a,_ in options)
            if turn==actor:
                values=[recurse(child,k,belief) for _,child in options]
                return max(values) if target_a else min(values)
            values=0.0
            for name,child in options:
                conditioned={o:w*policy(turn,state[1],o,labels)[name]
                             for o,w in belief.items()}
                conditioned={o:w for o,w in conditioned.items() if w>0.0}
                values+=recurse(child,k,conditioned)
            return values

        return sum(recurse(root,k,links[k]) for k in range(known))/total_mass

    br_a=best_response('A')
    br_b=best_response('B')
    gap=max(0.,br_a-br_b)
    if not all(math.isfinite(x) for x in (ev,br_a,br_b,gap)):
        raise ArithmeticError('Non-finite diagnostic')
    return RiverDiagnostic(profile_ev=ev,br_a_ev=br_a,br_b_ev=br_b,
                           nashconv=gap,exploitability=gap/2,
                           nashconv_pot_pct=100*gap/game.pot,
                           missing_infosets=len(missing))
