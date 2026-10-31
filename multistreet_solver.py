"""Educational, offline, card-aware, multi-street HU NLHE abstraction.

Starts with a flop/turn/river board; moves through ALL remaining streets.
Players have disjoint weighted two-card ranges; turn/river cards are sampled
uniformly from the undealt deck, and public board cards enter information-set
keys only WHEN exposed. Betting is no-limit-ish but abstracted to 1-2 sizes
per street and at most one raise in each betting round (no re-raises).

Sampled chance CFR+ updates; strategies are *approximations*. For RIVER STARTS ONLY,
exact best-response diagnostics are available for the fixed abstract tree.
Absolutely NOT full NLHE GTO.
All EV is measured in chips to A relative to the preexisting pot. The engine
is isolated from the live PokerNow feed and cannot press poker buttons.
"""
from __future__ import annotations

import bisect
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field

from gto_solver import DECK, cards, parse_range, rank7, shorthand
from postflop_solver import parse_sizes
from river_certification import evaluate_river

EPS = 1e-8
STREETS = {3:'F', 4:'T', 5:'R'}


@dataclass
class MultiStreetResult:
    board: tuple[str,...]
    pot: float
    stack: float
    sizes: dict[str,tuple[float,...]]
    raise_factor: float
    iterations: int
    n_a: int
    n_b: int
    pairs: int
    mean_ev: float
    root_strategies: list[dict]
    flop_b_responses: list[dict]
    posterior: dict
    example_path: list[dict]
    public_nodes: dict[str,int]
    status: str
    metadata: dict = field(default_factory=dict)


class _Node:
    __slots__ = ('actions','regret','sum','visits')

    def __init__(self, actions):
        self.actions=tuple(actions)
        self.regret=[0.0 for _ in actions]
        self.sum=[0.0 for _ in actions]
        self.visits=0

    def strategy(self):
        pos=[max(0.0, r) for r in self.regret]
        denom=sum(pos)
        if denom<=EPS:
            return [1/len(pos)]*len(pos)
        return [r/denom for r in pos]

    def average(self):
        denom=sum(self.sum)
        return [v/denom for v in self.sum] if denom>EPS else self.strategy()


def terminal_a_equity(initial_pot, invested_a, invested_b, win_fraction):
    """Net chips gained by A from a called showdown, invested chips subtracted."""
    return (initial_pot+invested_a+invested_b)*win_fraction - invested_a


def parse_street_sizes(flop: str, turn: str, river: str) -> dict[str,tuple[float,...]]:
    result={}
    for name, value in [('F',flop),('T',turn),('R',river)]:
        sizes=parse_sizes(value)
        if len(sizes)>2:
            raise ValueError(f'{name}: допускается 1–2 сайзинга на улицу в мультистрит-модели')
        result[name]=sizes
    return result


def solve_multistreet(board_text: str, pot: float, stack: float,
                      a_range: str, b_range: str,
                      flop_sizes: str='50', turn_sizes: str='75',river_sizes: str='75',
                      raise_factor: float=2.5, iterations: int=3500,
                      seed: int=20261031, inspect_runout: str='',
                      averaging: str='linear', chance_sampling: str='stratified',
                      exact_river: str='auto', private_sampling: str='random') -> MultiStreetResult:
    """Solve sampled abstract play on the remaining 1-3 streets.

    Each iteration samples a compatible pair of hole-card combos AND the
    entire uniformly random runout; future cards never appear in earlier
    street infoset keys or action choices. Each terminal path accounts for
    chips contributed on *all* streets. Averaged policies are exposed for
    studying public action ranges after flop bet/call, not realtime coaching.
    """
    board=cards(board_text)
    if len(board) not in (3,4,5):
        raise ValueError('Борд: флоп (3), тёрн (4) или ривер (5 карт)')
    pot,stack,raise_factor=float(pot),float(stack),float(raise_factor)
    if not all(math.isfinite(v) for v in (pot,stack,raise_factor)) or not (0<pot<=1e6 and 0<stack<=1e6):
        raise ValueError('Положительный банк и эффективный стек обязательны')
    if not (2<=raise_factor<=5):
        raise ValueError('Рейз x от 2 до 5')
    if not 200<=iterations<=100000:
        raise ValueError('Итерации: от 200 до 100000')
    if averaging not in ('uniform', 'linear'):
        raise ValueError('Усреднение: uniform или linear')
    if chance_sampling not in ('random', 'stratified'):
        raise ValueError('Выбор карт: random или stratified')
    if private_sampling not in ('random', 'systematic', 'paired'):
        raise ValueError('private_sampling: random, systematic или paired')
    if exact_river not in ('auto', 'always', 'never'):
        raise ValueError('Ривер: auto, always или never')
    sizes=parse_street_sizes(flop_sizes,turn_sizes,river_sizes)
    known_next=cards(inspect_runout) if inspect_runout.strip() else ()
    if len(known_next)>5-len(board) or set(known_next).intersection(board):
        raise ValueError('Карты для разбора линии пересекаются с бордом или их слишком много')
    if len(known_next)<5-len(board):
        # Only for post-solve line inspection, never fixes chance in training.
        known_next=known_next+tuple(c for c in DECK if c not in set(board+known_next))[:5-len(board)-len(known_next)]
    ar=parse_range(a_range,board)
    br=parse_range(b_range,board)
    if len(ar)>40 or len(br)>40:
        raise ValueError('Ограничение v4: максимум 40 комбинаций на игрока (скорость дерева)')
    ha=list(ar); hb=list(br)
    # Compatible joint distribution: card blockers imply conditional ranges.
    pairs=[]; cumul=[]; mass=0.0
    for i,a in enumerate(ha):
        for j,b in enumerate(hb):
            if not set(a).isdisjoint(b):
                continue
            w=ar[a]*br[b]
            if w<=0:continue
            mass+=w
            pairs.append((i,j))
            cumul.append(mass)
    if not pairs:
        raise ValueError('Диапазоны несовместимы: все комбинации пересекаются')
    rng=random.Random(seed)
    use_exact_river=(len(board)==5 and exact_river != 'never' and
                     (len(pairs)<=80 or exact_river=='always'))
    if exact_river=='always' and len(board)<5:
        raise ValueError('Точный перебор пар работает только на ривере')
    if private_sampling=='paired' and len(pairs)>16:
        raise ValueError('Paired CFR+: максимум 16 совместимых пар (лимит скорости)')
    if use_exact_river and len(pairs)>500:
        raise ValueError('Для точного ривера допускается не больше 500 совместимых пар')
    pair_weights=[ar[ha[i]]*br[hb[j]] for i,j in pairs]
    # Per-compatible-hand-pair public chance schedule. An affine permutation
    # enumerates every legal turn/river runout exactly once per cycle. This
    # reduces duplicates; it does not remove sampling variance or guarantee NE.
    chance_cycle={}
    def sample_public_runout(pair_idx, a, b):
        used=set(board+a+b)
        available=[c for c in DECK if c not in used]
        n=len(available)
        missing=5-len(board)
        if missing==0:return ()
        if chance_sampling=='random':
            return tuple(rng.sample(available,missing))
        npaths=n if missing==1 else n*(n-1)
        record=chance_cycle.get(pair_idx)
        if record is None or record[2]>=npaths:
            stride=rng.randrange(1,npaths)
            while math.gcd(stride,npaths)!=1:stride=rng.randrange(1,npaths)
            record=[rng.randrange(npaths),stride,0]
            chance_cycle[pair_idx]=record
        ix=(record[0]+record[1]*record[2])%npaths
        record[2]+=1
        if missing==1:return (available[ix],)
        first,second=divmod(ix,n-1)
        if second>=first:second+=1
        return (available[first],available[second])

    nodes={}
    start_stage=len(board)-3
    public_nodes=defaultdict(int)
    visited_total=0

    def get_node(player, visible_board, hist, hand_index, action_labels):
        key=(player,visible_board,hist,hand_index)
        node=nodes.get(key)
        if node is None:
            if len(nodes)>=230000:
                raise ValueError('Превышен лимит 230 000 узлов: уменьши диапазоны, сайзинги или итерации')
            node=_Node(action_labels)
            nodes[key]=node
            public_nodes[STREETS[len(visible_board)]]+=1
        elif node.actions!=tuple(action_labels):
            raise RuntimeError('Несовпадающие действия одного информационного множества')
        return node

    def policy(player, visible_board, hist, hand_index, default_actions):
        node=nodes.get((player,visible_board,hist,hand_index))
        if node is None:
            return {a:1/len(default_actions) for a in default_actions}
        return dict(zip(node.actions,node.average()))

    def bet_options(visible, invested):
        remaining=stack-invested
        pot_now=pot+2*invested
        options=[]
        for p in sizes[STREETS[len(visible)]]:
            bet=min(remaining, pot_now*p)
            if bet>EPS and not any(abs(bet-prev)<EPS for _,prev in options):
                options.append((f'BET {int(round(p*100))}%',bet))
        return options

    def raise_value(bet,invested):
        val=min(stack-invested,bet*raise_factor)
        # No raise when all-in or insufficient remaining stack.
        return val if val>bet+EPS else None

    total_ev=0.0
    total_world_updates=0
    systematic_offset = rng.random()
    systemic_cycle = 128
    for iteration in range(1,iterations+1):
        # Exact enumeration is inexpensive for small river ranges. All pair
        # regrets are accumulated *before* the CFR+ clipping step, instead of
        # letting the iteration's first private hand bias later hands.
        if use_exact_river:
            worlds=((slot,i,j,pair_weights[slot]/mass) for slot,(i,j) in enumerate(pairs))
        elif private_sampling=='paired':
            # Full enumeration of compatible *private* pairs, but only one
            # stratified public runout per pair. Simultaneous regret clipping.
            # One epoch costs len(pairs) world updates; report both budgets.
            worlds=((slot,i,j,pair_weights[slot]/mass) for slot,(i,j) in enumerate(pairs))
        else:
            if private_sampling=='systematic':
                # Randomly shifted systematic CDF allocation: each block of
                # 128 samples covers the joint range mass evenly (within one
                # sample of its expected count), reducing private-hand droughts.
                # Rotation is randomized once per block, reproducibly by seed.
                if (iteration-1)%systemic_cycle==0:
                    systematic_offset=rng.random()
                u=(((iteration-1)%systemic_cycle)+systematic_offset)/systemic_cycle
            else:
                u=rng.random()
            slot=bisect.bisect_left(cumul,u*mass)
            i,j=pairs[slot]
            worlds=((slot,i,j,1.0),)
        epoch_updates=defaultdict(lambda:None)
        epoch_ev=0.0
        avg_weight=float(iteration) if averaging=='linear' else 1.0
        for slot,i,j,sample_weight in worlds:
            ah=ha[i];bh=hb[j]
            runout=sample_public_runout(slot,ah,bh)
            full_board=board+runout
            r_a=rank7(full_board+ah)
            r_b=rank7(full_board+bh)
            equity=1.0 if r_a>r_b else 0.5 if r_a==r_b else 0.0
            updates=[]
            total_world_updates+=1

            def decide(player, visible, history, action_handlers, ra, rb):
                # No opponent-card or unrevealed-card info in the key.
                handidx=i if player=='A' else j
                labels=list(action_handlers)
                node=get_node(player,visible,history,handidx,labels)
                probs=node.strategy()
                values=[]
                for act,pr in zip(labels,probs):
                    va=ra*pr if player=='A' else ra
                    vb=rb*pr if player=='B' else rb
                    values.append(action_handlers[act](va,vb))
                current=sum(v*p for v,p in zip(values,probs))
                opp_reach=rb if player=='A' else ra
                sign=1.0 if player=='A' else -1.0
                updates.append((node, [sign*opp_reach*(v-current)/(pot+2*stack) for v in values]))
                own_reach=ra if player=='A' else rb
                for k,pr in enumerate(probs):
                    node.sum[k]+=sample_weight*avg_weight*own_reach*pr
                node.visits+=1
                return current

            def payoff(a_in,b_in):
                return terminal_a_equity(pot,a_in,b_in,equity)

            def next_round(stage, a_in,b_in,history,ra,rb):
                # Future streets still exist if remaining stack > 0.
                if stage==2 or stack-a_in<=EPS:
                    return payoff(a_in,b_in)
                next_stage=stage+1
                next_visible=full_board[:3+next_stage]
                marker=f'{STREETS[len(next_visible)]}:{next_visible[-1]}'
                return play_round(next_stage,a_in,b_in,history+(marker,),ra,rb)

            def play_round(stage, a_in,b_in,history,ra,rb):
                visible=full_board[:3+stage]
                assert abs(a_in-b_in)<EPS
                invested=a_in
                choices=bet_options(visible,invested)
                actions={}
                # First A check, then IP B can check/bet.
                def after_a_check(ra1,rb1):
                    b_choices={'CHECK':lambda r_a1,r_b1:next_round(stage,a_in,b_in,history+('A:CHECK','B:CHECK'),r_a1,r_b1)}
                    for label,bet in choices:
                        def ip_bet(r_a1,r_b1,bet=bet,label=label):
                            h=history+('A:CHECK',f'B:{label}')
                            raise_to=raise_value(bet,invested)
                            resp={
                                'FOLD': lambda x,y:-a_in,
                                'CALL': lambda x,y:next_round(stage,a_in+bet,b_in+bet,h+('A:CALL',),x,y),
                            }
                            if raise_to is not None:
                                def raise_a(x,y):
                                    h2=h+(f'A:RAISE {raise_to:.6f}',)
                                    return decide('B',visible,h2,{
                                        'FOLD':lambda p,q:pot+b_in+bet,
                                        'CALL':lambda p,q:next_round(stage,a_in+raise_to,b_in+raise_to,h2+('B:CALL',),p,q),
                                    },x,y)
                                resp['RAISE']=raise_a
                            return decide('A',visible,h,resp,r_a1,r_b1)
                        b_choices[label]=ip_bet
                    return decide('B',visible,history+('A:CHECK',),b_choices,ra1,rb1)
                actions['CHECK']=after_a_check
                for label,bet in choices:
                    def a_bet(ra1,rb1,label=label,bet=bet):
                        h=history+(f'A:{label}',)
                        raise_to=raise_value(bet,invested)
                        resp={
                            'FOLD':lambda x,y:pot+b_in,
                            'CALL':lambda x,y:next_round(stage,a_in+bet,b_in+bet,h+('B:CALL',),x,y),
                        }
                        if raise_to is not None:
                            def raise_b(x,y):
                                h2=h+(f'B:RAISE {raise_to:.6f}',)
                                return decide('A',visible,h2,{
                                    'FOLD':lambda p,q:-(a_in+bet),
                                    'CALL':lambda p,q:next_round(stage,a_in+raise_to,b_in+raise_to,h2+('A:CALL',),p,q),
                                },x,y)
                            resp['RAISE']=raise_b
                        return decide('B',visible,h,resp,ra1,rb1)
                    actions[label]=a_bet
                return decide('A',visible,history,actions,ra,rb)

            hist=(STREETS[len(board)],)
            # Histories in postflop from current board; earlier action history is
            # deliberately absent unless specified by user as a new starting range.
            ev=play_round(start_stage,0.0,0.0,hist,1.0,1.0)
            epoch_ev+=ev*sample_weight
            for node,deltas in updates:
                if epoch_updates[node] is None:
                    epoch_updates[node]=[0.0]*len(deltas)
                acc=epoch_updates[node]
                for k,delta in enumerate(deltas):
                    acc[k]+=sample_weight*delta

        total_ev+=epoch_ev
        # CFR+ applies regret-matching-plus to the whole epoch. On the river
        # this means every compatible private pair contributes to the same
        # simultaneous update, exactly as in tabular full-tree CFR+.
        for node,deltas in epoch_updates.items():
            for k,delta in enumerate(deltas):
                node.regret[k]=max(0.0,node.regret[k]+delta)

    opening=(STREETS[len(board)],)
    initial_choices=['CHECK']+[k for k,_ in bet_options(board,0.0)]
    groups=defaultdict(lambda:{'weight':0.0,'combos':0,'counts':defaultdict(float)})
    for i,hand in enumerate(ha):
        s=policy('A',board,opening,i,initial_choices)
        g=groups[shorthand(hand)]
        g['weight']+=ar[hand];g['combos']+=1
        for a,p in s.items():g['counts'][a]+=ar[hand]*p
    root=[]
    for classname,g in sorted(groups.items()):
        root.append({'class':classname,'combos':g['combos'],
                     'actions':{a:100*g['counts'].get(a,0)/g['weight'] for a in initial_choices}})

    responses=[]
    posterior={}
    # Card-removal-conditioned posterior for a common public line:
    # flop/starting-street A bets selected size, B calls. These posterior
    # distributions can be carried to the next street after filtering board.
    for label,bet in bet_options(board,0.0):
        h=opening+(f'A:{label}',)
        p_b=defaultdict(float);p_a=defaultdict(float)
        p_resp=defaultdict(float); total=0.0
        for aa,bb in pairs:
            w=ar[ha[aa]]*br[hb[bb]]
            pbet=policy('A',board,opening,aa,initial_choices).get(label,0)
            opts=['FOLD','CALL']+(['RAISE'] if raise_value(bet,0.0) is not None else [])
            sb=policy('B',board,h,bb,opts)
            for act,p in sb.items():p_resp[act]+=w*pbet*p
            call=w*pbet*sb.get('CALL',0.0)
            if call>0:
                p_a[ha[aa]]+=call;p_b[hb[bb]]+=call;total+=call
        def top(d):
            vals=defaultdict(float)
            for combo,weight in d.items():vals[shorthand(combo)]+=weight
            total_w=sum(vals.values())
            return [{'class':name,'probability_pct':100*w/total_w}
                    for name,w in sorted(vals.items(),key=lambda z:z[1],reverse=True)[:10]] if total_w>0 else []
        tot_action=sum(p_resp.values())
        responses.append({'size':label,'actions':{k:100*v/tot_action for k,v in p_resp.items()} if tot_action else {}})
        posterior[label]={'A':top(p_a),'B':top(p_b),'line':f'A {label} → B CALL',
                          'joint_weight':total/mass, 'meaning':'model-derived posterior, not observed opponent hand'}

    # Demonstrate *sequential* Bayes updating along a public, selected line:
    # A bets first legal size, B calls, selected next card is revealed, repeat.
    # The runout is used solely for posterior inspection AFTER optimization;
    # it never influences decisions at a previous street.
    path=[]
    sample_board=board
    sample_hist=(STREETS[len(board)],)
    sample_invested=0.0
    joint={(i,j):ar[ha[i]]*br[hb[j]] for i,j in pairs}
    for offset in range(5-len(board)+1):
        # Condition on the next public card, excluding impossible private hands.
        joint={(i,j):w for (i,j),w in joint.items()
               if set(ha[i]+hb[j]).isdisjoint(sample_board)}
        denom=sum(joint.values())
        if denom<=EPS or stack-sample_invested<=EPS:
            break
        joint={ij:w/denom for ij,w in joint.items()}
        options=bet_options(sample_board,sample_invested)
        if not options:
            break
        bet_label,bet_value=options[0]
        response_history=sample_hist+(f'A:{bet_label}',)
        newjoint={}
        covered_a=covered_b=0.0
        for (i,j),w in joint.items():
            anode=nodes.get(('A',sample_board,sample_hist,i))
            bnode=nodes.get(('B',sample_board,response_history,j))
            if anode:covered_a+=w
            if bnode:covered_b+=w
            a_labels=['CHECK']+[n for n,_ in options]
            b_labels=['FOLD','CALL']+(['RAISE'] if raise_value(bet_value,sample_invested) else [])
            pa=policy('A',sample_board,sample_hist,i,a_labels).get(bet_label,0.0)
            pb=policy('B',sample_board,response_history,j,b_labels).get('CALL',0.0)
            newjoint[i,j]=w*pa*pb
        prob=sum(newjoint.values())
        if prob<=EPS:
            path.append({'board':' '.join(sample_board),'line':f'A {bet_label}, B CALL',
                         'prob_pct':0.0,'A':[],'B':[], 'node_coverage_a_pct':100*covered_a,
                         'node_coverage_b_pct':100*covered_b})
            break
        joint={ij:w/prob for ij,w in newjoint.items()}
        def summarize(who):
            class_mass=defaultdict(float)
            for (i,j),weight in joint.items():
                class_mass[shorthand(ha[i] if who=='A' else hb[j])]+=weight
            return [{'class':key,'probability_pct':100*v} for key,v in
                    sorted(class_mass.items(),key=lambda x:-x[1])[:10]]
        path.append({'board':' '.join(sample_board),'line':f'A {bet_label}, B CALL',
                     'prob_pct':100*prob,'A':summarize('A'),'B':summarize('B'),
                     'node_coverage_a_pct':100*covered_a,'node_coverage_b_pct':100*covered_b})
        sample_invested+=bet_value
        sample_hist=response_history+('B:CALL',)
        if len(sample_board)==5:break
        next_card=known_next[len(sample_board)-len(board)]
        sample_board=sample_board+(next_card,)
        sample_hist=sample_hist+(f'{STREETS[len(sample_board)]}:{next_card}',)

    # Exact best-response diagnostic ONLY when there are no future chance cards.
    # For flop and turn, evaluating BR with future public card chance and all
    # information sets would require a substantially larger evaluation engine.
    # It is therefore deliberately unavailable, rather than approximated by
    # an inaccurate percentage.
    quality = None
    if len(board) == 5:
        def policy_for_eval(who, hist, index, labels):
            node=nodes.get((who,board,hist,index))
            if node is None:
                return None
            if tuple(labels)!=node.actions:
                raise RuntimeError('Different action ordering in evaluator')
            return dict(zip(node.actions,node.average()))
        quality = evaluate_river(board,pot,stack,sizes['R'],raise_factor,
                                 ha,hb,[ar[h] for h in ha],[br[h] for h in hb],
                                 policy_for_eval)

    result = MultiStreetResult(
        board=board,pot=pot,stack=stack,sizes=sizes,raise_factor=raise_factor,
        iterations=iterations,n_a=len(ar),n_b=len(br),pairs=len(pairs),
        mean_ev=total_ev/iterations, root_strategies=root,
        flop_b_responses=responses, posterior=posterior, example_path=path,
        public_nodes=dict(public_nodes),
        status=('River: exact abstract-game NashConv measured' if quality else
                'EXPERIMENTAL — multistreet not equilibrium-verified'),
        metadata={'method':('exact-private-hand CFR+ at river' if use_exact_river else 'chance-sampled CFR+ (private hand pair and public runout)'),
                  'game':'multi-street abstract HU','all_remaining_streets':True,
                  'averaging':averaging, 'chance_sampling':chance_sampling if not use_exact_river else 'not_applicable',
                  'private_sampling':('exact' if use_exact_river else private_sampling),
                  'exact_river_training':use_exact_river,'world_updates':total_world_updates,
                  'training_epochs':iterations,
                  'worlds_per_epoch':len(pairs) if (use_exact_river or private_sampling=='paired') else 1,
                  'max_bet_sizes_per_street':2,'raises_per_street':1,
                  'no_reraises':True,'chance':'uniform conditioned on both hole cards',
                  'future_cards_not_visible_in_earlier_infosets':True,
                  'nashconv':quality.nashconv if quality else None,
                  'exploitability':quality.exploitability if quality else None,
                  'profile_ev_exact':quality.profile_ev if quality else None,
                  'br_a_exact':quality.br_a_ev if quality else None,
                  'br_b_exact':quality.br_b_ev if quality else None,
                  'nashconv_pot_pct':quality.nashconv_pot_pct if quality else None,
                  'missing_eval_infosets':quality.missing_infosets if quality else None,
                  'quality_scope':'exact_br_river_fixed_abstract_game' if quality else 'not_measured_multistreet',
                  'hand_strength':'exact rank7 at sampled showdown',
                  'seed':seed,'root_range_posterior_method':'joint action-Bayes',
                  'inspection_runout':' '.join(known_next),
                  'inspection_only_not_known_to_flop_policy':True})
    # In-memory only: this audit handle is deliberately not exported by asdict()
    # and never sent to a browser or cloud API.
    result._audit_state = (nodes, ha, hb, ar, br)
    return result


def audit_saved_multistreet(result, *, max_worlds=12000, max_world_visits=12_000_000):
    """Exact BR for trained policies if the entire fixed game fits audit caps.

    Missing trained policies are uniformly assigned, and counted. No changes
    are made to the stored CFR+ regrets or averages.
    """
    from multistreet_quality import evaluate_multistreet

    if not hasattr(result, '_audit_state'):
        raise ValueError('Аудит доступен только для расчёта, выполненного в текущей сессии')
    nodes, ha, hb, ar, br = result._audit_state

    def lookup(who, visible, hist, idx, actions):
        node=nodes.get((who,visible,hist,idx))
        if node is None:return None
        if node.actions != actions:
            raise RuntimeError('Несовпадение дерева ставок обучающей модели и аудитора')
        return dict(zip(actions,node.average()))

    return evaluate_multistreet(
        result.board,result.pot,result.stack,result.sizes,result.raise_factor,
        ha,hb,[ar[h] for h in ha],[br[h] for h in hb],lookup,
        max_worlds=max_worlds,max_world_visits=max_world_visits)
