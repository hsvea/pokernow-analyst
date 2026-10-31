"""Pure Python river heads-up CFR+ solver for an intentionally LIMITED poker game.

Game tree: first player (bettor) checks -> showdown, or bets one fixed size;
second player (defender) folds or calls; showdown if called. No raises,
no multiple bet sizes, no post-check betting. Both players have ranges of
private two-card combos compatible with the five-card board. This computes
approximate equilibrium IN THIS ABSTRACT GAME ONLY, not unrestricted NLHE GTO.

All outputs are chip EV from bettor's view, measured as share of the pot
owned by neither player at start of the modeled street. Ranges are mutually
independent before card-removal conditioning.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

RANKS = '23456789TJQKA'
SUITS = 'cdhs'
DECK = tuple(r + s for r in RANKS for s in SUITS)
PRESETS = {
    'Тайтовый': '88+,ATs+,KQs,AQo+',
    'Средний': '55+,A2s+,K9s+,QTs+,JTs,T9s,98s,87s,AJo+,KQo',
    'Широкий': '22+,A2s+,K2s+,Q6s+,J7s+,T7s+,97s+,86s+,75s+,65s,54s,A2o+,K8o+,Q9o+,JTo',
}


def cards(text: str, expected: int | None = None) -> tuple[str, ...]:
    """Parse cards like 'Ah Kd 7c 2s 9h' or 'Ah,Kd,7c,2s,9h'."""
    words = re.split(r'[\s,;]+', text.strip().replace('10', 'T'))
    found = []
    for word in words:
        if not word:
            continue
        word = word[0].upper() + word[1:].lower()
        if len(word) != 2 or word not in DECK:
            raise ValueError(f'Неизвестная карта: {word}')
        found.append(word)
    if expected is not None and len(found) != expected:
        raise ValueError(f'Нужно {expected} карт(ы), получено {len(found)}')
    if len(found) != len(set(found)):
        raise ValueError('Одинаковая карта указана дважды')
    return tuple(found)


def rank7(all_cards: tuple[str, ...]) -> tuple[int, ...]:
    """Rank a 5-7 card hold'em hand. Higher lexicographic tuple is stronger."""
    counts = [0] * 15
    by_suit = {s: [] for s in SUITS}
    for c in all_cards:
        r = RANKS.index(c[0]) + 2
        counts[r] += 1
        by_suit[c[1]].append(r)

    def straight_high(rvals):
        vals = set(rvals)
        if 14 in vals:
            vals.add(1)
        for hi in range(14, 4, -1):
            if all(x in vals for x in range(hi - 4, hi + 1)):
                return hi
        return 0

    for rs in by_suit.values():
        if len(rs) >= 5:
            sf = straight_high(rs)
            if sf:
                return 8, sf
    quad = next((r for r in range(14, 1, -1) if counts[r] == 4), None)
    if quad:
        return 7, quad, max(r for r in range(2, 15) if r != quad and counts[r])
    trips = [r for r in range(14, 1, -1) if counts[r] >= 3]
    if trips:
        pairs = [r for r in range(14, 1, -1) if r != trips[0] and counts[r] >= 2]
        if pairs:
            return 6, trips[0], pairs[0]
    for rs in by_suit.values():
        if len(rs) >= 5:
            return (5, *sorted(rs, reverse=True)[:5])
    straight = straight_high(r for r in range(2, 15) if counts[r])
    if straight:
        return 4, straight
    if trips:
        kick = [r for r in range(14, 1, -1) if r != trips[0] and counts[r]][:2]
        return 3, trips[0], *kick
    pairs = [r for r in range(14, 1, -1) if counts[r] >= 2]
    if len(pairs) >= 2:
        kicker = max(r for r in range(2, 15) if r not in pairs[:2] and counts[r])
        return 2, pairs[0], pairs[1], kicker
    if pairs:
        kick = [r for r in range(14, 1, -1) if r != pairs[0] and counts[r]][:3]
        return 1, pairs[0], *kick
    return 0, *[r for r in range(14, 1, -1) if counts[r]][:5]


def expand_class(token: str) -> set[tuple[str, str]]:
    """Support AKs, AQo, AK, TT, 77+, AJs+, A2s-A5s, 99-66 and exact AhKd."""
    token = token.strip()
    if re.fullmatch('[2-9TJQKA][cdhs][2-9TJQKA][cdhs]', token, re.I):
        cc = cards(token[:2] + ' ' + token[2:], 2)
        return {tuple(sorted(cc))}
    m = re.fullmatch(r'([2-9TJQKA])([2-9TJQKA])([so]?)((?:\+)|(?:-[2-9TJQKA]{2}[so]?)|)', token, re.I)
    if not m:
        raise ValueError(f'Непонятный элемент диапазона: {token}')
    r1,r2,suit,suffix = m.groups()
    r1,r2,suit = r1.upper(),r2.upper(),suit.lower()
    if RANKS.index(r1) < RANKS.index(r2):
        raise ValueError(f'Сначала укажи старший ранг: {token}')
    if r1 == r2 and suit:
        raise ValueError(f'Для пар не используется s/o: {token}')
    classes=[]
    if suffix == '+':
        if r1 == r2:
            for rank in RANKS[RANKS.index(r1):]:
                classes.append((rank,rank,suit))
        else:
            for rank in RANKS[RANKS.index(r2):RANKS.index(r1)]:
                classes.append((r1,rank,suit))
    elif suffix.startswith('-'):
        end1,end2 = suffix[1].upper(),suffix[2].upper()
        end_suit = suffix[3:].lower()
        if end_suit and end_suit != suit:
            raise ValueError(f'Конечный суффикс должен совпадать: {token}')
        if r1 == r2 and end1 == end2:
            rr = sorted((RANKS.index(r1),RANKS.index(end1)))
            for ri in range(rr[0],rr[1]+1):
                classes.append((RANKS[ri],RANKS[ri],''))
        elif r1 == end1 and r2 != r1 and end2 != r1:
            rr = sorted((RANKS.index(r2),RANKS.index(end2)))
            for ri in range(rr[0],rr[1]+1):
                classes.append((r1,RANKS[ri],suit))
        else:
            raise ValueError(f'В интервале меняется только младший ранг или пара: {token}')
    else:
        classes = [(r1,r2,suit)]

    result = set()
    for a,b,typ in classes:
        if a==b:
            for s1,s2 in combinations(SUITS,2):
                result.add(tuple(sorted((a+s1,b+s2))))
        else:
            for s1 in SUITS:
                for s2 in SUITS:
                    if (typ=='s' and s1!=s2) or (typ=='o' and s1==s2):
                        continue
                    result.add(tuple(sorted((a+s1,b+s2))))
    return result


def parse_range(text: str, board: tuple[str, ...]) -> dict[tuple[str,str], float]:
    forbidden=set(board)
    result={}
    tokens = [t for t in re.split(r'[\s,;]+',text.strip()) if t]
    if not tokens:
        raise ValueError('Диапазон пуст')
    for t in tokens:
        parts=t.split(':')
        if len(parts)>2:
            raise ValueError(f'Неверный вес диапазона: {t}')
        weight=float(parts[1]) if len(parts)==2 else 1.0
        if not 0<=weight<=1:
            raise ValueError('Вес должен быть от 0 до 1')
        for combo in expand_class(parts[0]):
            if not forbidden.intersection(combo):
                result[combo]=max(result.get(combo,0.0),weight)
    result={k:v for k,v in result.items() if v>0}
    if not result:
        raise ValueError('Нет комбинаций, совместимых с бордом')
    if len(result)>260:
        raise ValueError('Для скорости демонстрационной версии максимум 260 комбинаций в диапазоне')
    return dict(sorted(result.items()))


def shorthand(c:tuple[str,str])->str:
    r1,r2 = sorted([c[0][0],c[1][0]],key=lambda x:RANKS.index(x),reverse=True)
    if r1==r2:
        return r1+r2
    return r1+r2+('s' if c[0][1]==c[1][1] else 'o')


def regret_prob(r: list[float]) -> float:
    a,b = max(0.,r[0]),max(0.,r[1])
    return b/(a+b) if a+b>0 else .5


@dataclass
class GTOResult:
    board: tuple[str,...]
    pot: float
    bet: float
    n_first: int
    n_second: int
    pairs: int
    iterations: int
    mean_ev: float
    br_gap: float
    strategy: list[dict]
    defender: list[dict]
    detailed: dict


def solve_river(board_text: str, pot: float, bet: float,
                first_range: str, second_range: str, iterations: int = 2000) -> GTOResult:
    """Solve the one-bet river game by CFR+; no approximations in hand strength."""
    board=cards(board_text,5)
    pot,bet = float(pot),float(bet)
    if not 0<pot<=1_000_000 or not 0<bet<=1_000_000:
        raise ValueError('Банк и ставка должны быть положительными')
    if not 100<=iterations<=20000:
        raise ValueError('Итерации: от 100 до 20000')
    range1=parse_range(first_range,board)
    range2=parse_range(second_range,board)
    hands1=list(range1)
    hands2=list(range2)
    weights1=[range1[h] for h in hands1]
    weights2=[range2[h] for h in hands2]
    ranks1=[rank7(board+h) for h in hands1]
    ranks2=[rank7(board+h) for h in hands2]
    edges=[]
    sum1=[0.]*len(hands1)
    sum2=[0.]*len(hands2)
    joint=0.
    for i, h1 in enumerate(hands1):
        for j,h2 in enumerate(hands2):
            if not set(h1).isdisjoint(h2):
                continue
            win = 1. if ranks1[i]>ranks2[j] else .5 if ranks1[i]==ranks2[j] else 0.
            check=pot*win
            called=(pot+2*bet)*win-bet
            edges.append((i,j,check,called,weights1[i],weights2[j]))
            sum1[i]+=weights2[j]
            sum2[j]+=weights1[i]
            joint+=weights1[i]*weights2[j]
    if not edges:
        raise ValueError('Не существует совместимых комбинаций между диапазонами')
    # Two regrets per information set: [check,bet] or [fold,call].
    r1=[[0.,0.] for _ in hands1]
    r2=[[0.,0.] for _ in hands2]
    sum_x=[0.]*len(hands1)
    sum_y=[0.]*len(hands2)
    total_average_weight=0.
    # Normalize by max potential payoff to avoid regret magnitudes growing with stakes.
    scale=pot+bet
    for t in range(1,iterations+1):
        x=[regret_prob(r) for r in r1]
        y=[regret_prob(r) for r in r2]
        delta1=[0.]*len(hands1)
        delta2=[0.]*len(hands2)
        for i,j,check,called,wi,wj in edges:
            delta1[i] += wj*((1-y[j])*pot + y[j]*called-check)
            # Defender wants MINIMIZE bettor EV: her payoff call minus fold.
            delta2[j] += wi*x[i]*(pot-called)
        for i, r in enumerate(r1):
            d=delta1[i]/max(sum1[i]*scale,1e-12)
            r[0]=max(0.,r[0]-x[i]*d)
            r[1]=max(0.,r[1]+(1-x[i])*d)
        for j, r in enumerate(r2):
            d=delta2[j]/max(sum2[j]*scale,1e-12)
            r[0]=max(0.,r[0]-y[j]*d)
            r[1]=max(0.,r[1]+(1-y[j])*d)
        if t>iterations//4:
            # Linear average of strategy profiles for CFR+.
            w=t-iterations//4
            total_average_weight+=w
            for i,v in enumerate(x):
                sum_x[i]+=w*v
            for j,v in enumerate(y):
                sum_y[j]+=w*v
    x=[v/total_average_weight for v in sum_x]
    y=[v/total_average_weight for v in sum_y]

    ev_check=[0.]*len(hands1)
    ev_bet=[0.]*len(hands1)
    v_check=0.
    v_fold=[0.]*len(hands2)
    v_call=[0.]*len(hands2)
    total=0.
    for i,j,check,called,wi,wj in edges:
        call_ev= (1-y[j])*pot+y[j]*called
        ev_check[i]+=wj*check
        ev_bet[i]+=wj*call_ev
        v_check+=wi*wj*(1-x[i])*check
        v_fold[j]+=wi*x[i]*pot
        v_call[j]+=wi*x[i]*called
        total+=wi*wj*((1-x[i])*check+x[i]*call_ev)
    hero_br=sum(weights1[i]*max(ev_check[i],ev_bet[i]) for i in range(len(hands1)))/joint
    defender_br=(v_check+sum(weights2[j]*min(v_fold[j],v_call[j]) for j in range(len(hands2))))/joint
    gap=max(0.,hero_br-defender_br)
    detailed={}
    groups=defaultdict(lambda: {'frequency':0.,'check_ev':0.,'bet_ev':0.,'weight':0.,'combos':0})
    for i,h in enumerate(hands1):
        if not sum1[i]:
            continue
        check_ev=ev_check[i]/sum1[i]
        bet_ev=ev_bet[i]/sum1[i]
        vals={'combo': ''.join(h), 'class': shorthand(h), 'bet_pct':100*x[i],
              'check_pct':100*(1-x[i]),'ev_bet':bet_ev,'ev_check':check_ev}
        detailed[''.join(h)]=vals
        g=groups[vals['class']]
        g['combos']+=1
        g['frequency']+=weights1[i]*x[i]
        g['check_ev']+=weights1[i]*check_ev
        g['bet_ev']+=weights1[i]*bet_ev
        g['weight']+=weights1[i]
    strategy=[]
    for key, g in groups.items():
        z=g['weight']
        strategy.append({'hand':key,'combos':g['combos'], 'bet_pct':100*g['frequency']/z,
                         'check_pct':100*(1-g['frequency']/z),
                         'ev_bet':g['bet_ev']/z,'ev_check':g['check_ev']/z})
    strategy.sort(key=lambda d:(-d['bet_pct'], -d['ev_bet'],d['hand']))
    defender=[]
    d_groups=defaultdict(lambda:{'weight':0.,'call':0.,'combos':0})
    for j,h in enumerate(hands2):
        if not sum2[j]: continue
        g=d_groups[shorthand(h)]
        g['weight']+=weights2[j]
        g['call']+=weights2[j]*y[j]
        g['combos']+=1
    for hand,g in d_groups.items():
        defender.append({'hand':hand,'combos':g['combos'],'call_pct':100*g['call']/g['weight']})
    defender.sort(key=lambda d:(-d['call_pct'],d['hand']))
    return GTOResult(board,pot,bet,len(hands1),len(hands2),len(edges),iterations,
                     total/joint,gap,strategy,defender,detailed)


def completed_river_boards(csv_text: str) -> list[tuple[str, ...]]:
    """Extract boards from completed PokerNow CSV hands; useful for post-hand study.

    Accepts both full river lines and separate flop/turn/river card formats.
    Does not infer pot or betting ranges.
    """
    # Import locally to avoid forcing the collector into this solver module.
    from core import START, END, csv_lines
    board=[]
    active=False
    results=[]
    for raw, _ in csv_lines(csv_text):
        if START.search(raw):
            active=True
            board=[]
            continue
        if not active:
            continue
        m=re.match(r'^(Flop|Turn|River)\s*:\s*(.*)$', raw.strip(), re.I)
        if m:
            ranks=re.findall(r'(?<![A-Za-z0-9])(?:10|[2-9TJQKA])[cdhs](?![A-Za-z0-9])',m.group(2),re.I)
            for tok in ranks:
                try:
                    c=cards(tok,1)[0]
                    if c not in board:
                        board.append(c)
                except ValueError:
                    continue
        if END.search(raw):
            if len(board)==5:
                results.append(tuple(board))
            active=False
            board=[]
    return results
