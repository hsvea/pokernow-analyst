"""Exact profile and unilateral BR on a finite, bounded *multi-street abstraction*.

Critical property: all worlds that agree on the responder's hole cards, public
board and public action history are optimized TOGETHER. The best response does
not peek at the opponent's hole cards or unrevealed turn/river cards.

For a full 52-card chance deck this is an exact NashConv diagnostic of this
restricted HU game (for the supplied policies, including their fallback), NOT
of unrestricted NLHE. Optional chance_deck is a smaller *different game* used
only for independent regression tests, never represented as full-deck quality.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from typing import Callable, Mapping

from gto_solver import DECK, rank7

EPS = 1e-9
STREETS = {3: 'F', 4: 'T', 5: 'R'}


class AuditLimitError(RuntimeError):
    """Requested exact audit is too large; no false NashConv is reported."""


@dataclass(frozen=True)
class MultiStreetDiagnostic:
    profile_ev: float
    br_a_ev: float
    br_b_ev: float
    nashconv: float
    exploitability: float
    nashconv_pot_pct: float
    missing_infosets: int
    worlds: int
    visited_world_states: int
    chance_scope: str
    model: str = 'bounded_multistreet_exact_br_fixed_abstract_game'


@dataclass(frozen=True)
class World:
    a: int
    b: int
    runout: tuple[str, ...]
    weight: float
    win_a: float


class AbstractGame:
    """Mirrors v4 multi-street betting tree, including one raise per street."""

    def __init__(self, start, pot, stack, sizes, factor):
        self.start = tuple(start)
        self.pot, self.stack, self.factor = float(pot), float(stack), float(factor)
        self.sizes = sizes

    def begin(self):
        return ('ROOT', self.start, (STREETS[len(self.start)],), 0., 0., 0.)

    def bet_options(self, visible, invested):
        remaining = self.stack-invested
        pnow = self.pot + 2*invested
        choices = []
        for fraction in self.sizes[STREETS[len(visible)]]:
            bet = min(remaining, pnow*fraction)
            if bet > EPS and not any(abs(bet-v)<EPS for _,v in choices):
                choices.append((f'BET {int(round(fraction*100))}%',bet))
        return choices

    def raise_to(self, invested, amount):
        val = min(self.stack-invested, amount*self.factor)
        return val if val>amount+EPS else None

    def next(self, visible, hist, invested):
        if len(visible)==5 or invested>=self.stack-EPS:
            return ('SHOW', visible, hist, invested, 0., 0.)
        return ('CHANCE', visible, hist, invested, 0., 0.)

    def branch(self, state):
        phase, visible, hist, invested, amount, firstbet = state
        options=self.bet_options(visible,invested)
        def make(p,h,amt=0.,fbet=0.):return (p,visible,h,invested,amt,fbet)
        if phase=='ROOT':
            actions=[('CHECK',make('B_CHECK',hist+('A:CHECK',)))]
            actions.extend((label,make('B_VS_A',hist+(f'A:{label}',),bet,bet))
                           for label,bet in options)
            return 'A',actions
        if phase=='B_CHECK':
            actions=[('CHECK',self.next(visible,hist+('B:CHECK',),invested))]
            actions.extend((label,make('A_VS_B',hist+(f'B:{label}',),bet,bet))
                           for label,bet in options)
            return 'B',actions
        if phase=='B_VS_A':
            actions=[('FOLD',('FOLD', self.pot+invested)),
                     ('CALL',self.next(visible,hist+('B:CALL',),invested+amount))]
            raised=self.raise_to(invested,amount)
            if raised is not None:
                actions.append(('RAISE',make('A_VS_B_R',hist+(f'B:RAISE {raised:.6f}',),raised,firstbet)))
            return 'B',actions
        if phase=='A_VS_B':
            actions=[('FOLD',('FOLD',-invested)),
                     ('CALL',self.next(visible,hist+('A:CALL',),invested+amount))]
            raised=self.raise_to(invested,amount)
            if raised is not None:
                actions.append(('RAISE',make('B_VS_A_R',hist+(f'A:RAISE {raised:.6f}',),raised,firstbet)))
            return 'A',actions
        if phase=='A_VS_B_R':
            return 'A',[('FOLD',('FOLD',-(invested+firstbet))),
                        ('CALL',self.next(visible,hist+('A:CALL',),invested+amount))]
        if phase=='B_VS_A_R':
            return 'B',[('FOLD',('FOLD',self.pot+invested+firstbet)),
                        ('CALL',self.next(visible,hist+('B:CALL',),invested+amount))]
        raise AssertionError(f'Unknown state {phase}')


def evaluate_multistreet(board, pot, stack, sizes, raise_factor,
                         hands_a, hands_b, weights_a, weights_b,
                         get_policy: Callable[[str,tuple[str,...],tuple[str,...],int,tuple[str,...]],Mapping[str,float]|None],
                         *, chance_deck=None, max_worlds=12000,
                         max_world_visits=12_000_000):
    """Exact enumeration of cards, strategies and unilateral best responses.

    get_policy(who,visible_board,history,combo_index,legal_actions). A missing
    info set uses a uniform policy and is included in coverage diagnostics.

    Normalization is per compatible private-hand pair: card-removal cannot
    bias the root hand distribution even in an intentionally reduced test deck.
    """
    board=tuple(board); hands_a=list(hands_a); hands_b=list(hands_b)
    if len(board) not in (3,4,5) or len(set(board))!=len(board):
        raise ValueError('Requires 3, 4 or 5 distinct board cards')
    if len(weights_a)!=len(hands_a) or len(weights_b)!=len(hands_b):
        raise ValueError('Range weights length mismatch')
    if not hands_a or not hands_b or not 0<pot<=1e6 or not 0<stack<=1e6:
        raise ValueError('Invalid ranges, pot or stack')
    audit_cards=tuple(DECK if chance_deck is None else chance_deck)
    if len(set(audit_cards))!=len(audit_cards) or any(c not in DECK for c in audit_cards):
        raise ValueError('Chance deck contains duplicate or invalid cards')
    if chance_deck is not None and len(audit_cards)<5-len(board):
        raise ValueError('Not enough chance cards')
    remaining=5-len(board)
    from itertools import permutations
    valid_pairs=[]
    for i,a in enumerate(hands_a):
        if len(a)!=2 or len(set(a))!=2 or set(a)&set(board):
            raise ValueError('Invalid A combo')
        for j,b in enumerate(hands_b):
            if len(b)!=2 or len(set(b))!=2 or set(b)&set(board):
                raise ValueError('Invalid B combo')
            weight=weights_a[i]*weights_b[j]
            if weight>0 and not set(a)&set(b):
                valid_pairs.append((i,j,float(weight)))
    norm=sum(w for _,_,w in valid_pairs)
    if norm<=0:raise ValueError('No compatible private hand pairs')
    estimated=0
    for i,j,_ in valid_pairs:
        used=set(board+tuple(hands_a[i])+tuple(hands_b[j]))
        allowed=sum(c not in used for c in audit_cards)
        if allowed < remaining:raise ValueError('Chance deck blocked by hole cards')
        estimated+=math.perm(allowed,remaining)
    if estimated>max_worlds:
        raise AuditLimitError(f'Миров {estimated:,} > лимита {max_worlds:,}; сократи диапазоны или выбери тёрн/ривер')
    worlds=[]
    for i,j,w in valid_pairs:
        a=tuple(hands_a[i]);b=tuple(hands_b[j]);used=set(board+a+b)
        allowed=tuple(c for c in audit_cards if c not in used)
        denom=math.perm(len(allowed),remaining)
        for runout in permutations(allowed,remaining):
            full_board=board+runout
            ra=rank7(full_board+a);rb=rank7(full_board+b)
            win=1. if ra>rb else .5 if ra==rb else 0.
            worlds.append(World(i,j,runout,(w/norm)/denom,win))
    game=AbstractGame(board,pot,stack,sizes,raise_factor)
    missing=set(); cache={}; visited=0

    def policy(actor,state,hand,labels):
        key=(actor,state[1],state[2],hand,labels)
        if key not in cache:
            raw=get_policy(*key)
            if raw is None:
                missing.add(key[:4]);vals=[1/len(labels)]*len(labels)
            else:
                vals=[max(0.,float(raw.get(a,0.))) for a in labels]
                if not all(math.isfinite(x) for x in vals):raise ValueError('Non-finite policy')
                total=sum(vals)
                vals=[v/total for v in vals] if total>EPS else [1/len(labels)]*len(labels)
            cache[key]=dict(zip(labels,vals))
        return cache[key]

    root_belief=[(idx,w.weight) for idx,w in enumerate(worlds)]

    def traverse(state,belief,target=None):
        nonlocal visited
        if not belief:return 0.
        visited+=len(belief)
        if visited>max_world_visits:
            raise AuditLimitError(f'Точный перебор остановлен: >{max_world_visits:,} world-state посещений')
        if state[0]=='FOLD':return sum(mass*state[1] for idx,mass in belief)
        if state[0]=='SHOW':
            invested=state[3]
            return sum(mass*((pot+2*invested)*worlds[idx].win_a-invested) for idx,mass in belief)
        if state[0]=='CHANCE':
            buckets=defaultdict(list)
            for idx,mass in belief:
                w=worlds[idx]
                buckets[w.runout[len(state[1])-len(board)]].append((idx,mass))
            total=0.
            for nxt,sub in buckets.items():
                visible=state[1]+(nxt,)
                next_state=('ROOT',visible,state[2]+(f'{STREETS[len(visible)]}:{nxt}',),state[3],0.,0.)
                total+=traverse(next_state,sub,target)
            return total
        actor,actions=game.branch(state)
        labels=tuple(a for a,_ in actions)
        if actor==target:
            grouped=defaultdict(list)
            for idx,mass in belief:
                hand=worlds[idx].a if target=='A' else worlds[idx].b
                grouped[hand].append((idx,mass))
            value=0.
            for hand,sub in grouped.items():
                child_values=[traverse(child,sub,target) for _,child in actions]
                value+=max(child_values) if target=='A' else min(child_values)
            return value
        buckets={a:[] for a,_ in actions}
        for idx,mass in belief:
            hand=worlds[idx].a if actor=='A' else worlds[idx].b
            probs=policy(actor,state,hand,labels)
            for action in labels:
                p=probs[action]
                if p>0:buckets[action].append((idx,mass*p))
        return sum(traverse(child,buckets[label],target) for label,child in actions)

    profile_ev=traverse(game.begin(),root_belief)
    br_a=traverse(game.begin(),root_belief,'A')
    br_b=traverse(game.begin(),root_belief,'B')
    gap=max(0.,br_a-br_b)
    if br_a+1e-7<profile_ev or br_b-1e-7>profile_ev:
        raise ArithmeticError('Best-response bounds inconsistent')
    return MultiStreetDiagnostic(profile_ev,br_a,br_b,gap,gap/2,100*gap/pot,
        len(missing),len(worlds),visited,'full_52_card_deck' if chance_deck is None else 'reduced_chance_test_deck')
