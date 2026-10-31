"""Postflop HU betting-round abstraction solver for OFFLINE hand review.

Supports flop/turn/river, OOP check or several bet sizes, IP check-back or bet,
fold/call and at most one raise per betting line. This is a *single-street*
game: after both players check or a bet is called, remaining community cards
are dealt uniformly and no further wagers occur. Not full multi-street NLHE.

Chance-sampled CFR+ over privately weighted, card-disjoint combos. Hand equity
is averaged over possible runouts (exact turn/river, sampled flop). No
counterpart's hidden cards are read from PokerNow.
"""
from __future__ import annotations

import bisect
import itertools
import math
import random
from dataclasses import dataclass
from collections import defaultdict

from gto_solver import DECK, cards, parse_range, rank7, shorthand


@dataclass
class PostflopResult:
    board: tuple[str, ...]
    pot: float
    stack: float
    sizes: tuple[float, ...]
    raise_factor: float
    iterations: int
    runouts: int
    n_a: int
    n_b: int
    pairs: int
    mean_ev: float
    # Algorithm diagnostic, NOT convergence/exploitability guarantee.
    avg_weighted_regret: float
    strategy_a: list[dict]
    strategy_b: list[dict]
    responses_b: list[dict]
    responses_a: list[dict]
    results_a: list[dict]
    results_b: list[dict]
    metadata: dict


def parse_sizes(text: str) -> tuple[float, ...]:
    """Accept percentages of the initial pot (e.g. '33,75,125')."""
    try:
        values = tuple(sorted(set(float(x.strip().rstrip('%')) / 100.0
                                  for x in text.replace(';', ',').split(',') if x.strip())))
    except ValueError as exc:
        raise ValueError('Сайзинги — проценты через запятую, например 33,75,125') from exc
    if not values or len(values)>3 or not all(math.isfinite(v) and 0.05<=v<=2.5 for v in values):
        raise ValueError('Укажи 1–3 сайзинга от 5% до 250% банка')
    return values


def equity_for_pair(board: tuple[str, ...], hand_a: tuple[str, str],
                    hand_b: tuple[str, str], max_runouts=100) -> float:
    """Equity including ties; complete turn enumeration and flop sample."""
    known = set(board+hand_a+hand_b)
    if len(known) != len(board)+4:
        raise ValueError('Пересекающиеся карты')
    missing = 5-len(board)
    remain = [c for c in DECK if c not in known]
    if missing == 0:
        a=rank7(board+hand_a); b=rank7(board+hand_b)
        return 1.0 if a>b else .5 if a==b else 0.0
    if missing == 1:
        runouts=[(c,) for c in remain]
    else:
        all_outcomes=list(itertools.combinations(remain,2))
        if max_runouts>=len(all_outcomes):
            runouts=all_outcomes
        else:
            # Stable Monte Carlo for deterministic repeatable tests and UI.
            seed=0
            for c in board+hand_a+hand_b:
                seed=seed*53 + DECK.index(c)+1
            runouts=random.Random(seed).sample(all_outcomes, max_runouts)
    total=0.0
    for run in runouts:
        b=board+run
        v1=rank7(b+hand_a)
        v2=rank7(b+hand_b)
        total+=1.0 if v1>v2 else .5 if v1==v2 else 0.0
    return total / len(runouts)


class _Node:
    __slots__ = ('labels','regret','strategy_sum','visits')
    def __init__(self, labels):
        self.labels=tuple(labels)
        self.regret=[0.0]*len(labels)
        self.strategy_sum=[0.0]*len(labels)
        self.visits=0

    def strategy(self):
        pos=[max(0.0,x) for x in self.regret]
        s=sum(pos)
        return [x/s for x in pos] if s>1e-10 else [1.0/len(pos)]*len(pos)

    def average(self):
        s=sum(self.strategy_sum)
        return [x/s for x in self.strategy_sum] if s>1e-12 else self.strategy()


def solve_postflop(board_text: str, pot: float, stack: float,
                   a_range: str, b_range: str,
                   sizes_text: str='33,75', raise_factor: float=2.5,
                   iterations: int=30000, max_runouts: int=80,
                   seed: int=1337) -> PostflopResult:
    """CFR+ on a single betting round, chance sampled at hand-combination level.

    The sampled game is exactly the current betting round with terminal equity
    on the five-card board (no strategic play on later streets). Strategies
    indexed by acting player's combo and public betting sequence, never by
    the opponent's actual hidden cards.
    """
    board=cards(board_text)
    if len(board) not in (3,4,5):
        raise ValueError('Борд должен содержать 3, 4 или 5 карт')
    pot=float(pot); stack=float(stack); raise_factor=float(raise_factor)
    if not (math.isfinite(pot) and math.isfinite(stack) and 0 < pot <= 1e6 and 0 < stack <=1e6):
        raise ValueError('Банк и эффективный стек должны быть положительными')
    if not (2.0<=raise_factor<=5.0):
        raise ValueError('Множитель рейза: 2–5')
    if not (1000<=iterations<=500000):
        raise ValueError('Итераций: от 1000 до 500000')
    if not (12<=max_runouts<=900):
        raise ValueError('Число прогона борда: 12–900')
    sizes=parse_sizes(sizes_text)
    bets=[]
    for x in sizes:
        val=min(stack, pot*x)
        if not any(abs(v-val)<1e-8 for v in bets):
            bets.append(val)
    # If stack smaller than the size, bet becomes all-in and no raising is possible.
    if not bets:
        raise ValueError('Не получилось сформировать ставки')
    a=parse_range(a_range, board)
    b=parse_range(b_range, board)
    if len(a)>100 or len(b)>100:
        raise ValueError('Максимум 100 комбинаций в диапазоне для текущего постфлоп-решателя')
    ha=list(a); hb=list(b)
    # First do all expensive equity evaluation, then the optimization iterations.
    edges=[]; total_w=0.0
    for i,ah in enumerate(ha):
        used=set(ah)
        for j,bh in enumerate(hb):
            if not used.isdisjoint(bh):
                continue
            w=a[ah]*b[bh]
            if w<=0: continue
            eq=equity_for_pair(board,ah,bh,max_runouts)
            edges.append((i,j,eq,w))
            total_w+=w
    if not edges:
        raise ValueError('Диапазоны не имеют совместимых пар карт')
    # Stable weighted chance sample of a compatible combination pair.
    cumul=[]; subtotal=0.0
    for _,_,_,w in edges:
        subtotal+=w
        cumul.append(subtotal)
    rng=random.Random(seed)
    nodes={}

    def get_node(key, labels):
        node=nodes.get(key)
        if node is None:
            node=_Node(labels)
            nodes[key]=node
        return node

    def bet_choices():
        return ['CHECK']+[f'BET {int(round(bv/pot*100))}%' for bv in bets]

    def raise_to(bet):
        amount=min(stack, bet*raise_factor)
        return amount if amount>bet+1e-9 else None

    def showdown(eq, spent_a=0.0):
        return (pot+2*spent_a)*eq-spent_a

    def traverse(i,j,eq,average_weight,accumulate=False):
        # Cache current node strategies within this iteration/traversal.
        # Regress at the end of traversal so that all public branches see the
        # same strategy profile.
        updates=[]
        def decision(player, history, actions, funcs, reach_a,reach_b):
            key=(player,history, i if player=='A' else j)
            node=get_node(key,actions)
            sigma=node.average() if accumulate else node.strategy()
            if accumulate:
                reach=reach_a if player=='A' else reach_b
                # Own reach is relevant to the average policy; since dealing
                # was sampled, chance weights already enter via sampling.
                for idx,sp in enumerate(sigma):
                    node.strategy_sum[idx]+=average_weight*reach*sp
                node.visits+=1
            evs=[]
            for idx,func in enumerate(funcs):
                x=reach_a*sigma[idx] if player=='A' else reach_a
                y=reach_b*sigma[idx] if player=='B' else reach_b
                evs.append(func(x,y))
            ev=sum(z*p for z,p in zip(evs,sigma))
            if not accumulate:
                opp_reach=reach_b if player=='A' else reach_a
                sign=1.0 if player=='A' else -1.0
                updates.append((node,[sign*opp_reach*(v-ev)/(pot+stack) for v in evs]))
                # Average of *current* strategies, not the accumulator!
                own_reach=reach_a if player=='A' else reach_b
                for idx,sp in enumerate(sigma):
                    node.strategy_sum[idx]+=average_weight*own_reach*sp
                node.visits+=1
            return ev

        def response_a_to_b(bet, ra,rb):
            raise_val=raise_to(bet)
            labels=['FOLD','CALL']+(['RAISE'] if raise_val is not None else [])
            fs=[lambda x,y: 0.0,
                lambda x,y: showdown(eq,bet)]
            if raise_val is not None:
                fs.append(lambda x,y: decision('B',('CHECK','B_BET',bet,'A_RAISE',raise_val),
                    ['FOLD','CALL'], [lambda a1,b1:pot+bet,
                                     lambda a1,b1:showdown(eq,raise_val)],x,y))
            return decision('A',('CHECK','B_BET',bet),labels,fs,ra,rb)

        def response_b_to_a(bet,ra,rb):
            raise_val=raise_to(bet)
            labels=['FOLD','CALL']+(['RAISE'] if raise_val is not None else [])
            fs=[lambda x,y:pot,
                lambda x,y:showdown(eq,bet)]
            if raise_val is not None:
                fs.append(lambda x,y: decision('A',('A_BET',bet,'B_RAISE',raise_val),
                    ['FOLD','CALL'], [lambda a1,b1:-bet,
                                     lambda a1,b1:showdown(eq,raise_val)],x,y))
            return decision('B',('A_BET',bet),labels,fs,ra,rb)

        def after_a_check(ra,rb):
            labels=['CHECK']+[f'BET {int(round(z/pot*100))}%' for z in bets]
            fs=[lambda x,y: showdown(eq)] + [(lambda bet:lambda x,y:response_a_to_b(bet,x,y))(bb) for bb in bets]
            return decision('B',('A_CHECK',),labels,fs,ra,rb)
        first_labels=bet_choices()
        first_functions=[lambda x,y: after_a_check(x,y)] + [(lambda bet:lambda x,y:response_b_to_a(bet,x,y))(bb) for bb in bets]
        v=decision('A',('ROOT',),first_labels,first_functions,1.0,1.0)
        for node,vals in updates:
            for k,val in enumerate(vals):
                node.regret[k]=max(0.0,node.regret[k]+val)
        return v

    # Accumulate strategies for chance-sampled online CFR+.
    # Including warmup averaging dampens tail variance in rare infosets.
    for t in range(iterations):
        k=bisect.bisect_left(cumul, rng.random()*total_w)
        i,j,eq,w=edges[k]
        traverse(i,j,eq,1.0)

    def strat(label, hand_idx, hist, labels):
        node=nodes.get((label,hist,hand_idx))
        return dict(zip(labels,node.average())) if node is not None else {a:1/len(labels) for a in labels}

    first=bet_choices()
    def group_results(who):
        groups=defaultdict(lambda:{'combinations':0,'weight':0.0,'counts':defaultdict(float)})
        every=[]
        hands=ha if who=='A' else hb
        for idx,combo in enumerate(hands):
            key='ROOT' if who=='A' else 'AFTER_CHECK'
            if who=='A':
                acts=strat('A',idx,('ROOT',),first)
            else:
                acts=strat('B',idx,('A_CHECK',),first)
            row={'combo':''.join(combo),'class':shorthand(combo),'actions':acts}
            every.append(row)
            g=groups[row['class']]
            g['combinations']+=1
            weight=(a if who=='A' else b)[combo]
            g['weight']+=weight
            for k,v in acts.items(): g['counts'][k]+=weight*v
        result=[]
        for name,g in groups.items():
            result.append({'class':name,'combos':g['combinations'],
                'actions':{key:100*g['counts'].get(key,0)/g['weight'] for key in first}})
        result.sort(key=lambda x:(-max(x['actions'].values()),x['class']))
        return result,every

    a_groups,a_each=group_results('A')
    b_groups,b_each=group_results('B')

    def response_groups(who):
        table=[]
        hands=hb if who=='B' else ha
        range_weights=b if who=='B' else a
        for bet in bets:
            buckets=defaultdict(lambda:{'weight':0.0,'combos':0,'freq':defaultdict(float)})
            if who=='B':
                history=('A_BET',bet)
            else:
                history=('CHECK','B_BET',bet)
            labels=['FOLD','CALL']+(['RAISE'] if raise_to(bet) is not None else [])
            for idx,combo in enumerate(hands):
                v=strat(who,idx,history,labels)
                g=buckets[shorthand(combo)]
                w=range_weights[combo]
                g['weight']+=w;g['combos']+=1
                for k,freq in v.items():g['freq'][k]+=w*freq
            rows=[]
            for classname,g in buckets.items():
                rows.append({'class':classname,'combos':g['combos'],
                    'actions':{k:100*g['freq'].get(k,0.0)/g['weight'] for k in labels}})
            rows.sort(key=lambda z:(-z['actions'].get('CALL',0),z['class']))
            table.append({'bet':bet,'bet_pct':bet/pot*100,'classes':rows})
        return table

    responses_b=response_groups('B')
    responses_a=response_groups('A')

    # Evaluate the averaged strategy, never accumulate policy values here.
    def mean_given_edge(i,j,eq):
        def respondent_b(bet):
            q=strat('B',j,('A_BET',bet),['FOLD','CALL']+(['RAISE'] if raise_to(bet) else []))
            result=q['FOLD']*pot+q['CALL']*showdown(eq,bet)
            if 'RAISE' in q:
                r=raise_to(bet)
                a_strat=strat('A',i,('A_BET',bet,'B_RAISE',r),['FOLD','CALL'])
                result+=q['RAISE']*(a_strat['FOLD']*(-bet)+a_strat['CALL']*showdown(eq,r))
            return result
        def respondent_a(bet):
            q=strat('A',i,('CHECK','B_BET',bet),['FOLD','CALL']+(['RAISE'] if raise_to(bet) else []))
            result=q['CALL']*showdown(eq,bet)
            if 'RAISE' in q:
                r=raise_to(bet)
                b_strat=strat('B',j,('CHECK','B_BET',bet,'A_RAISE',r),['FOLD','CALL'])
                result+=q['RAISE']*(b_strat['FOLD']*(pot+bet)+b_strat['CALL']*showdown(eq,r))
            return result
        s_a=strat('A',i,('ROOT',),first)
        s_b=strat('B',j,('A_CHECK',),first)
        after_check=s_b['CHECK']*showdown(eq)
        for index,bet in enumerate(bets,1):
            after_check+=s_b[first[index]]*respondent_a(bet)
        result=s_a['CHECK']*after_check
        for index,bet in enumerate(bets,1):
            result+=s_a[first[index]]*respondent_b(bet)
        return result

    value=sum(w*mean_given_edge(i,j,eq) for i,j,eq,w in edges)/total_w
    positive_regret=sum(sum(node.regret) for node in nodes.values())/max(1,len(nodes))
    return PostflopResult(
        board=board,pot=pot,stack=stack,sizes=sizes,raise_factor=raise_factor,
        iterations=iterations,runouts=0 if len(board)==5 else (44 if len(board)==4 else max_runouts),
        n_a=len(a),n_b=len(b),pairs=len(edges),mean_ev=value,
        avg_weighted_regret=positive_regret,
        strategy_a=a_groups,strategy_b=b_groups,responses_b=responses_b,
        responses_a=responses_a,results_a=a_each,results_b=b_each,
        metadata={'game':'single-street','raises_per_line':1,'future_betting':False,
                  'showdown_equity':'exact' if len(board)>=4 else 'sampled',
                  'method':'chance-sampled CFR+','convergence_certified':False})
