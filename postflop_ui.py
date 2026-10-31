"""Tkinter study tab for limited postflop CFR+, deliberately disconnected from live controls."""
from __future__ import annotations
import csv
import json
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from postflop_solver import solve_postflop, parse_sizes
from gto_solver import cards, completed_river_boards

TIGHT='88+,ATs+,KQs,AQo+'
MEDIUM='77+,AJs+,KQs,AQo+'
NIT='TT+,AQs+,AKo'
LOOSE='77+,A9s+,KJs+,QJs,AJo+'


class PostflopTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app=app
        self.last=None
        self.profile_msg=''
        self.build()

    def heading(self,parent,text,size=10,color='#c9d9e7',bold=False):
        x=tk.Label(parent,text=text,bg='#0c1420',fg=color,anchor='w',justify='left',
            font=('Segoe UI',size,'bold' if bold else 'normal'))
        return x

    def field(self,parent, label,var,width):
        f=ttk.Frame(parent)
        f.pack(side='left',padx=(0,14))
        self.heading(f,label,9).pack(anchor='w')
        ttk.Entry(f,textvariable=var,width=width).pack(anchor='w',pady=(4,0))

    def build(self):
        self.heading(self,'POSTFLOP · HU CFR+ · разбор завершённых рук',17,'#7ae4d9',True).pack(anchor='w',pady=(8,4))
        self.heading(self,'Ограниченная игра НА ОДНОЙ УЛИЦЕ: A CHECK/BET, B CHECK или FOLD/CALL/RAISE. '
            'После колла — доска до ривера без дальнейших ставок. Флоп ≠ полный многоуличный GTO.',
            10,'#a6becd').pack(anchor='w',pady=(0,10))
        row=ttk.Frame(self);row.pack(fill='x',pady=(0,8))
        self.board=tk.StringVar(value='Ah 7d 2c')
        self.pot=tk.StringVar(value='100')
        self.stack=tk.StringVar(value='300')
        self.bets=tk.StringVar(value='33,75')
        self.raise_x=tk.StringVar(value='2.5')
        self.iterations=tk.StringVar(value='30000')
        self.runouts=tk.StringVar(value='80')
        self.import_street=tk.StringVar(value='Ривер')
        for n,v,w in [('Борд 3–5 карт',self.board,19),('Банк',self.pot,9),('Эфф. стек',self.stack,10),
                      ('Ставки % банка',self.bets,15),('Рейз x',self.raise_x,9),
                      ('Итераций',self.iterations,9),('Runouts (флоп)',self.runouts,10)]:
            self.field(row,n,v,w)
        rr=ttk.Frame(self);rr.pack(fill='x',pady=(0,6))
        self.range_a=tk.StringVar(value=TIGHT)
        self.range_b=tk.StringVar(value=MEDIUM)
        for title,var in [('A · вне позиции · первым',self.range_a),('B · в позиции · отвечает',self.range_b)]:
            c=ttk.Frame(rr);c.pack(side='left',fill='x',expand=True,padx=(0,12))
            self.heading(c,title,10,'#9ff0d4',True).pack(anchor='w')
            ttk.Entry(c,textvariable=var).pack(fill='x',pady=(4,0))
        self.heading(self,'Диапазоны: AA, 77+, AKs, AQo, AhKh, AKs:0.5. До 100 комбо у каждого. '
                     'Сайзинги от банка; только один рейз в каждой линии.',9,'#8bafbc').pack(anchor='w',pady=(0,5))
        tool=ttk.Frame(self);tool.pack(fill='x',pady=(4,8))
        self.solve_button=ttk.Button(tool,text='Рассчитать CFR+ (офлайн)',command=self.run)
        self.solve_button.pack(side='left')
        ttk.Button(tool,text='Борд из CSV',command=self.load_board).pack(side='left',padx=9)
        ttk.Combobox(tool,textvariable=self.import_street,values=('Флоп','Тёрн','Ривер'),
                     state='readonly',width=7).pack(side='left')
        ttk.Button(tool,text='Подобрать пресет по VPIP/PFR',command=self.use_profile).pack(side='left',padx=9)
        ttk.Button(tool,text='Сохранить результат JSON',command=self.export_result).pack(side='right')
        ttk.Button(tool,text='Объяснить через AI',command=self.explain).pack(side='right',padx=(0,10))
        self.status=tk.StringVar(value='Режим изучения завершённых раздач; автоматических подсказок на живом столе нет.')
        tk.Label(self,textvariable=self.status,bg='#0c1420',fg='#b1dfeb',wraplength=1240,
                 anchor='w',justify='left',font=('Segoe UI',10)).pack(fill='x',pady=(0,10))
        body=ttk.Frame(self);body.pack(fill='both',expand=True)
        left=ttk.Frame(body);left.pack(side='left',fill='both',expand=True,padx=(0,8))
        self.heading(left,'A · частоты первых действий по классам',11,'#8ceec8',True).pack(anchor='w',pady=(0,4))
        self.tree=ttk.Treeview(left,columns=('hand','n','check','b1','b2','b3'),show='headings',height=15)
        for key,name,w in [('hand','Рука',75),('n','Комбо',65),('check','CHECK',75),
                           ('b1','BET 1',75),('b2','BET 2',75),('b3','BET 3',75)]:
            self.tree.heading(key,text=name)
            self.tree.column(key,width=w,anchor='center',minwidth=55)
        tree_scroll=ttk.Scrollbar(left,orient='vertical',command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side='left',fill='both',expand=True)
        tree_scroll.pack(side='right',fill='y')
        right=ttk.Frame(body);right.pack(side='right',fill='both',expand=True,padx=(8,0))
        self.heading(right,'EV · частоты B · ограничения модели',11,'#8ceec8',True).pack(anchor='w',pady=(0,4))
        self.report=self.app.textbox(right,height=20,readonly=True)
        self.report.pack(fill='both',expand=True)
        self.app.set_text(self.report,'После расчёта здесь появятся EV, размеры ставок и стратегия обоих игроков.\n\n'
            'Обрати внимание: разрешённые действия и условное завершение после текущей улицы '
            'определяют результат. Частоты не следует считать точным GTO всей раздачи.')

    def run(self):
        try:
            board=self.board.get(); cards_parsed=cards(board)
            if len(cards_parsed) not in (3,4,5): raise ValueError('Нужно 3, 4 или 5 карт')
            args=dict(board_text=board,pot=float(self.pot.get()),stack=float(self.stack.get()),
                a_range=self.range_a.get(),b_range=self.range_b.get(),sizes_text=self.bets.get(),
                raise_factor=float(self.raise_x.get()),iterations=int(self.iterations.get()),
                max_runouts=int(self.runouts.get()))
            parse_sizes(args['sizes_text'])
        except (ValueError,TypeError) as exc:
            messagebox.showwarning('Проверь поля ввода',str(exc));return
        self.solve_button.configure(state='disabled')
        self.status.set('Считаю equity допустимых комбинаций и стратегии CFR+…')
        def work():
            try: self.app.events.put(('postflop_ready',(solve_postflop(**args),None)))
            except Exception as exc: self.app.events.put(('postflop_ready',(None,str(exc))))
        threading.Thread(target=work,daemon=True).start()

    def show_result(self,payload):
        self.solve_button.configure(state='normal')
        result,error=payload
        if error:
            self.status.set('Ошибка расчёта: '+error);return
        self.last=result
        self.status.set(f"{len(result.board)} карт на столе · банк {result.pot:g} · стек {result.stack:g} · "
            f"A {result.n_a} комбо / B {result.n_b} комбо · {result.pairs} совместимых пар · "
            f"{result.iterations:,} итераций CFR+ · equity {result.metadata['showdown_equity']}")
        for iid in self.tree.get_children():self.tree.delete(iid)
        labels=['CHECK']+[f'BET {int(round(min(result.stack,result.pot*z)/result.pot*100))}%' for z in result.sizes]
        # Effective sizes may merge due to all-in; derive actually occurring action labels.
        labels=list(result.strategy_a[0]['actions']) if result.strategy_a else labels
        for row in result.strategy_a:
            vals=[f"{row['actions'].get(k,0):.1f}%" for k in labels]
            self.tree.insert('',tk.END,values=(row['class'],row['combos'],*(vals+['—']*4)[:4]))
        out=[f"Борд: {' '.join(result.board)}",
             f'Банк {result.pot:g} · стек {result.stack:g} · бет-сайзинги {self.bets.get()}% банка',
             f'EV игрока A: {result.mean_ev:.2f} фишек от банка в начале улицы.',
             f'Алгоритм: {result.metadata["method"]}, {result.iterations:,} итераций.',
             'Это НЕ сертифицированное равновесие: NashConv / exploitability здесь не вычисляется.',
             'Стратегия относится только к выбранной абстракции одной улицы.',
             '', 'Игрок B · его действия ПОСЛЕ ЧЕКА A:']
        for row in result.strategy_b[:19]:
            desc=' | '.join(f'{a} {v:.0f}%' for a,v in row['actions'].items() if v>=4)
            out.append(f"{row['class']:<5}  {desc}")
        if result.responses_b:
            first_size=result.responses_b[0]
            out.append('')
            out.append(f"B · против ставки A {first_size['bet_pct']:.0f}% банка (FOLD/CALL/RAISE):")
            for row in first_size['classes'][:12]:
                desc=' / '.join(f'{k} {v:.0f}%' for k,v in row['actions'].items())
                out.append(f"{row['class']:<5}  {desc}")
        if result.responses_a:
            first_size=result.responses_a[0]
            out.append('')
            out.append(f"A · против ставки B {first_size['bet_pct']:.0f}% после чека (FOLD/CALL/RAISE):")
            for row in first_size['classes'][:8]:
                desc=' / '.join(f'{k} {v:.0f}%' for k,v in row['actions'].items())
                out.append(f"{row['class']:<5}  {desc}")
        if self.profile_msg:
            out.extend(['', 'Поведенческий пресет:',self.profile_msg])
        if len(result.board)<5:
            out.extend(['', 'После колла — случайный ривер без дополнительных ставок.',
                        'На флопе equity оценивается по выборке ранаутов; это добавляет погрешность.'])
        self.app.set_text(self.report,'\n'.join(out))
        # Safe JSON summary only. No real-time action trigger.
        self.app.postflop_context={
            'type':'posthand_offline_study','board':' '.join(result.board),
            'pot':result.pot,'stack':result.stack,'bet_sizing_pct':self.bets.get(),
            'raise_factor':result.raise_factor,'range_A':self.range_a.get(),
            'range_B':self.range_b.get(),'iterations':result.iterations,
            'mean_ev_a':round(result.mean_ev,3), 'strategy_a':result.strategy_a[:35],
            'strategy_b_after_check':result.strategy_b[:30],
            'strategy_b_vs_bet':result.responses_b,
            'strategy_a_vs_ip_bet':result.responses_a,
            'limitations':result.metadata,'profile_caution':self.profile_msg,
            'note':'Only one betting round. Later streets force showdown without betting. No exploitability guarantee.'}

    def use_profile(self):
        st=next((x for x in self.app.all_stats if x['key']==self.app.current_selected),None)
        if not st:
            messagebox.showinfo('Игрок','Выбери игрока на вкладке «Игроки и статистика».');return
        hands=st['hands']
        if hands<30:
            messagebox.showinfo('Недостаточно данных',
                f'У игрока {hands} завершённых раздач; минимум 30 для грубого выбора шаблона.')
            return
        vpip=100*st['vpip']/hands
        pfr=100*st['pfr']/hands
        if vpip>=35: preset=LOOSE; name='широкий'
        elif vpip<=18: preset=NIT; name='тайтовый'
        else:preset=MEDIUM;name='средний'
        self.range_b.set(preset)
        self.profile_msg=(f"{st['name']}: VPIP {vpip:.1f}%, PFR {pfr:.1f}%, {hands} раздач. "
            f"Выбран стартовый {name} ПРЕФЛОП-пресет; это не оценка реального "
            'постфлоп-диапазона с учётом действий, позиции и борда. Скорректируй вручную.')
        self.status.set(self.profile_msg)

    def load_board(self):
        paths=filedialog.askopenfilenames(filetypes=[('PokerNow CSV','*.csv *.txt'),('Все','*.*')])
        if not paths:return
        found=[]
        for path in paths:
            try:found.extend(completed_river_boards(Path(path).read_text(encoding='utf-8-sig')))
            except (UnicodeError,OSError) as e:messagebox.showwarning('Ошибка файла',str(e))
        if not found:
            messagebox.showinfo('CSV','Нет завершённых раздач с полным бордом.');return
        n={'Флоп':3,'Тёрн':4,'Ривер':5}[self.import_street.get()]
        self.board.set(' '.join(found[-1][:n]))
        self.status.set('Загружен борд последней завершённой раздачи на выбранной улице; банк/стек/диапазоны задай отдельно.')

    def export_result(self):
        if not self.last:
            messagebox.showinfo('Результат','Сначала рассчитай стратегию.');return
        path=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json')],
                                          initialfile='pokernow_postflop_study.json')
        if not path:return
        try:
            Path(path).write_text(json.dumps(self.app.postflop_context,ensure_ascii=False,indent=2),encoding='utf-8')
        except OSError as e:messagebox.showerror('Запись файла',str(e));return
        self.status.set('Результат сохранён: '+path)

    def explain(self):
        if not self.last:
            messagebox.showinfo('GTO','Сначала выполни расчёт.');return
        self.app.question.delete('1.0',tk.END)
        self.app.question.insert('1.0',
            'Объясни стратегию ОФФЛАЙН разбора завершённой раздачи. Как работают частоты CHECK/BET '
            'и рейзы в ограниченной одностритовой модели? Отдели модельные выводы от догадок о сопернике, '
            'не выдавай эти результаты за многоуличное GTO или точный exploitability.')
        self.app.notebook.select(self.app.agent_tab)
        self.app.set_text(self.app.answer,'Контекст оффлайн CFR+ добавлен. Для отправки данных нажми «Спросить AI через API» и подтверди запрос.')
