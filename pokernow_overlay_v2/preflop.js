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
  function raiseTracker(){
    let previous=null,anchor=false,blocked='',raises=0,high=0,increment=0,limpers=0,targets=[];
    const key=p=>p.profileId||('seat:'+p.seat);
    const close=(a,b)=>Math.abs(a-b)<.001;
    function clear(){anchor=false;blocked='';raises=0;high=0;increment=0;limpers=0;targets=[];}
    return {observe(state,now=Date.now(),visible=true){
      const players=state.players.filter(p=>!p.waitingNextHand);
      const next={table:state.table,dealer:state.dealerKey,hand:state.handId,board:state.board.length,bb:state.bb,now,
        bets:new Map(players.map(p=>[key(p),p.bet]))};
      const boundary=previous&&(previous.table!==next.table || (previous.dealer&&next.dealer&&previous.dealer!==next.dealer) ||
        (previous.hand&&next.hand&&previous.hand!==next.hand) || (previous.board>0&&next.board===0));
      if(boundary)clear();
      const stop=reason=>({usable:false,reason,raises,targets:[...targets]});
      if(!visible){clear();previous=null;return stop('Вкладка была скрыта: жду исходные ставки новой раздачи');}
      if(next.board){clear();previous=next;return stop('Трекер повышений работает на префлопе');}
      if(!state.holdem){clear();previous=next;return stop('Трекер повышений — только NL Hold’em');}
      if(!anchor){
        const initial=unraisedSituation(players,state.hero,state.bb);
        if(initial){anchor=true;high=state.bb;increment=state.bb;limpers=initial.limpers;blocked='';}
        previous=next;
        if(!anchor)return stop('Начало повышений не наблюдалось. Оставь стол открытым до новой раздачи или укажи сценарий этой руки.');
      }else if(previous&&!boundary){
        if(now-previous.now>5000 || now<previous.now)blocked='Был перерыв в наблюдении: последовательность повышений не подтверждена';
        if(!close(state.bb,previous.bb)||!Number.isFinite(state.bb))blocked='Изменился или пропал размер BB';
        if(previous.bets.size!==next.bets.size||[...next.bets.keys()].some(k=>!previous.bets.has(k)))blocked='Изменился состав раздачи: последовательность ставок неполная';
        const changes=players.filter(p=>!close(p.bet,previous.bets.get(key(p))));
        if(changes.some(p=>!Number.isFinite(p.bet)||p.bet<(previous.bets.get(key(p))??0)-.001))blocked='Ставки сбросились до завершения префлопа: жду новую раздачу';
        const higher=changes.filter(p=>p.bet>high+.001);
        if(higher.length){
          if(changes.length!==1)blocked='Несколько ставок изменились одновременно: могло быть пропущено повышение';
          else if(higher[0].bet-high+.001<increment)blocked='Неполное повышение all-in: нужен отдельный разбор';
          else if(!blocked){increment=higher[0].bet-high;high=higher[0].bet;raises++;targets.push(high);}
        }
        if(!raises){const initial=unraisedSituation(players,state.hero,state.bb);if(initial)limpers=initial.limpers;}
        previous=next;
      }
      if(blocked)return stop(blocked);
      if(raises>3)return stop('Наблюдалось больше трёх повышений: сценарий вне модели');
      return {usable:true,scenario:raises?['','raise','3bet','4bet'][raises]:limpers?'limped':'unopened',
        raises,targets:[...targets],facing:high,limpers,minRaiseTo:high+increment,reason:'Последовательность наблюдалась по ставкам стола'};
    }};
  }
  function postflopDecision({pot,call,equity}){
    if(!Number.isFinite(call)||call<0||!Number.isFinite(pot)||pot<0)return {action:'Нет цены колла',reason:'Не распознаны банк или сумма колла. Проверь значения стола.'};
    if(call===0)return {action:'CHECK',reason:'Можно продолжить без доплаты. Для выбора ставки нужны диапазоны и оценка фолд-эквити.'};
    if(!Number.isFinite(equity)||equity<0||equity>1)return {action:'Считаю equity…',reason:'Ожидаю завершения симуляции против случайных рук.'};
    const threshold=call/(pot+call),margin=equity-threshold;
    const action=Math.abs(margin)<.03?'Пограничный колл':margin>0?'CALL · ориентир':'FOLD · ориентир';
    return {action,threshold,reason:'Equity '+(equity*100).toFixed(1)+'% против случайных рук; порог колла '+(threshold*100).toFixed(1)+'%. '+(Math.abs(margin)<.03?'Разница меньше 3 п.п.; слабое основание для решения.':'Реальный диапазон ставки соперника может изменить вывод.')+' Без рейка и будущих ставок.'};
  }
  const api={hand,positions,inferPosition,unraisedSituation,raiseTracker,postflopDecision,recommend};
  if(typeof module!=='undefined'&&module.exports) module.exports=api;
  else root.PokerNowPreflop=api;
})(globalThis);
