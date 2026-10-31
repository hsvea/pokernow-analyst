/* Transparent preflop heuristics. Pure module, no network and no game actions. */
(function (root) {
  'use strict';
  const ranks = '23456789TJQKA';
  function hand(cards) {
    if (!Array.isArray(cards) || cards.length !== 2 || cards[0] === cards[1] || cards.some(c => !/^[2-9TJQKA][cdhs]$/.test(c))) throw new Error('Нужны две разные карты Hero');
    const a = ranks.indexOf(cards[0][0]), b = ranks.indexOf(cards[1][0]);
    return {hi: Math.max(a,b)+2, lo: Math.min(a,b)+2, pair:a===b, suited:cards[0][1]===cards[1][1],
      label:ranks[Math.max(a,b)]+ranks[Math.min(a,b)]+(a===b?'':cards[0][1]===cards[1][1]?'s':'o')};
  }
  function positions(n) {
    const map = {2:['SB','BB'],3:['BTN','SB','BB'],4:['CO','BTN','SB','BB'],
      5:['HJ','CO','BTN','SB','BB'],6:['UTG','HJ','CO','BTN','SB','BB'],
      7:['UTG','MP','HJ','CO','BTN','SB','BB'],8:['UTG','UTG+1','MP','HJ','CO','BTN','SB','BB'],
      9:['UTG','UTG+1','MP','LJ','HJ','CO','BTN','SB','BB'],10:['UTG','UTG+1','UTG+2','MP','LJ','HJ','CO','BTN','SB','BB']};
    return map[n] || [];
  }
  function inferPosition(players, hero) {
    // Folded players keep their original position; next-hand arrivals do not yet have one.
    players=players.filter(p=>!p.waitingNextHand);
    if (!hero || players.length<2 || players.length>10 || players.filter(p=>p.dealer).length!==1 || players.some(p=>!Number.isInteger(p.seat))) return null;
    const sorted = [...players].sort((a,b)=>a.seat-b.seat);
    if (new Set(sorted.map(p=>p.seat)).size!==sorted.length) return null;
    const dealer = sorted.findIndex(p=>p.dealer), heroIndex = sorted.indexOf(hero);
    if (heroIndex<0) return null;
    const labels=positions(players.length);
    const buttonIndex=players.length===2?0:labels.indexOf('BTN');
    return labels[(heroIndex-dealer+buttonIndex+players.length)%players.length];
  }
  function openRange(h, pos) {
    const late = ['CO','BTN','SB'].includes(pos), middle=['MP','LJ','HJ'].includes(pos);
    if (pos==='BTN' || pos==='SB') return h.pair || (h.hi===14 && (h.suited || h.lo>=5)) || (h.hi>=12&&h.lo>=9) || (h.suited&&h.hi-h.lo<=2&&h.lo>=6);
    if (late) return (h.pair&&h.hi>=4)||(h.hi===14&&(h.suited?h.lo>=7:h.lo>=10))||(h.suited&&h.hi>=11&&h.lo>=10)||(h.hi>=13&&h.lo>=11);
    if (middle) return (h.pair&&h.hi>=6)||(h.hi===14&&(h.suited?h.lo>=10:h.lo>=11))||(h.suited&&h.hi>=12&&h.lo>=11)||(h.hi===13&&h.lo===12);
    return (h.pair&&h.hi>=7)||(h.hi===14&&(h.suited?h.lo>=11:h.lo>=12))||(h.suited&&h.hi===13&&h.lo===12);
  }
  function unraisedSituation(players, hero, bb) {
    if(!hero || !Number.isFinite(bb) || bb<=0)return null;
    const seated=players.filter(p=>!p.waitingNextHand);
    const blind=seated.find(p=>inferPosition(seated,p)==='BB');
    if(!blind || Math.abs(blind.bet-bb)>.001 || seated.some(p=>!Number.isFinite(p.bet)||p.bet<0||p.bet>bb+.001))return null;
    // The BB is identified by seat, not by an optional "big blind" status label.
    // A non-blind contribution of one BB is a limp in an unraised preflop pot.
    const limpers=seated.filter(p=>p!==hero&&p!==blind&&!p.folded&&Math.abs(p.bet-bb)<.001).length;
    return {scenario:limpers?'limped':'unopened',limpers};
  }
  function recommend(input) {
    const h=hand(input.cards), n=Number(input.players), bb=Number(input.bb), stack=Number(input.stack), own=Number(input.heroBet||0), facing=Number(input.totalBet||0);
    const pos=input.position, scenario=input.scenario;
    if (!positions(n).includes(pos)) throw new Error('Укажи позицию для текущего числа игроков');
    if (![bb,stack,own,facing].every(Number.isFinite)||bb<=0||stack<=0||own<0||facing<own) throw new Error('Проверь BB, стек и текущие ставки');
    if (!['unopened','limped','raise','3bet','4bet'].includes(scenario)) throw new Error('Укажи историю повышений вручную');
    const limpers=Number(input.limpers||0);
    if (!Number.isInteger(limpers)||limpers<0||limpers>=n) throw new Error('Некорректное число лимперов');
    if (['unopened','limped'].includes(scenario) && facing>bb) throw new Error('Ставка выше BB: выбери рейз, 3-бет или 4-бет');
    if (['raise','3bet','4bet'].includes(scenario) && facing<=bb) throw new Error('Для рейза ставка должна быть больше BB');
    const call=Math.min(stack,Math.max(0,facing-own)), cap=own+stack, depth=cap/bb;
    const premium=(h.pair&&h.hi>=12)||(h.hi===14&&h.lo===13);
    const veryStrong=(h.pair&&h.hi>=13)||(h.hi===14&&h.lo===13&&h.suited);
    let action=call===0?'CHECK':'FOLD', target=null, reason='Рука вне консервативного диапазона этой ситуации.';
    function raise(label, amount) {
      if (cap<=facing) {action='CALL';target=null;reason='Стек не позволяет повысить: колл на весь остаток.';return;}
      const minimum = facing>bb?Math.max(facing+bb,Number(input.minRaiseTo)||2*facing):2*bb;
      target=Math.min(cap,Math.max(amount,minimum));
      action=label;
      reason=target===cap?'Сайзинг ограничен эффективным стеком (all-in).':'Ориентир размера — общая ставка на улице, включая уже внесённые фишки.';
    }
    if (scenario==='unopened'||scenario==='limped') {
      if (openRange(h,pos==='BB'?'CO':pos)) {
        const amount=(pos==='SB'?3:2.5)*bb+limpers*bb;
        if (depth<15 && !premium && !(h.pair&&h.hi>=9) && !(h.hi===14&&h.lo>=12)) reason='Короткий стек: нужен отдельный push/fold-разбор; агрессивный сайзинг не предлагается.';
        else raise('RAISE',depth<15?cap:amount);
      }
    } else if (scenario==='raise') {
      if (premium) raise('3-BET',facing*(['SB','BB'].includes(pos)?4:3));
      else if (((h.pair&&h.hi>=8)||(h.suited&&h.hi===14&&h.lo>=11)||(h.suited&&h.hi===13&&h.lo===12)) && call<=cap*0.08 && facing<=5*bb) {action='CALL';reason='Небольшой рейз и достаточный стек; решение зависит от позиции открывшегося игрока.';}
    } else if (scenario==='3bet') {
      if (veryStrong) raise('4-BET',facing*2.3);
      else if (premium && call<=cap*0.12) {action='CALL';reason='Сильная рука, умеренная цена колла; без точных диапазонов это лишь ориентир.';}
    } else {
      if (h.pair&&h.hi>=13) {action='CALL';reason='Премиальная пара против 4-бета; отдельный анализ нужен для решения о дальнейшем повышении.';}
    }
    return {hand:h.label, action, target, call, stackBB:depth, reason,
      caveat:'Эвристика, не GTO и не гарантия выигрыша. Не учитывает рейк, анте и точные диапазоны соперников.'};
  }
  const api={hand,positions,inferPosition,unraisedSituation,recommend};
  if(typeof module!=='undefined'&&module.exports) module.exports=api;
  else root.PokerNowPreflop=api;
})(globalThis);
