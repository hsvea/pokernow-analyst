"""Offline strategy-quality and independent LP benchmark tab."""
from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from gto_solver import cards,parse_range
from multistreet_solver import solve_multistreet
from exact_reference import solve_reference_lp


class QualityTab(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent)
        self.app=app
        self.last=None
        self._build()

    def label(self,container,text,size=10,color='#cbdbea',bold=False):
        return tk.Label(container,text=text,bg='#0c1420',fg=color,anchor='w',justify='left',
                        font=('Segoe UI',size,'bold' if bold else 'normal'))

    def field(self,parent,label,var,width=12):
        f=ttk.Frame(parent);f.pack(side='left',padx=(0,13))
        self.label(f,label,9).pack(anchor='w')
        ttk.Entry(f,textvariable=var,width=width).pack(anchor='w',pady=(3,0))

    def _build(self):
        self.label(self,'GTO QUALITY · NashConv + LP benchmark',17,'#7ae4d9',True).pack(anchor='w',pady=(10,5))
        self.label(self,'Анализ ЗАВЕРШЁННОЙ или смоделированной раздачи: независимая проверка ограниченной HU-игры на ривере.\n'
                   'NashConv измеряется точным best-response перебором; LP решает маленькую игру без CFR.',10,'#b0cad9').pack(anchor='w',pady=(0,10))
        self.label(self,'Это НЕ full NLHE GTO. LP-эталон требует SciPy и максимум 2 точные комбинации у каждого игрока, 1 размер ставки.',10,'#f4cb92').pack(anchor='w',pady=(0,8))
        row=ttk.Frame(self);row.pack(fill='x',pady=(0,8))
        self.board=tk.StringVar(value='2h 3h 5d 8s Jc')
        self.pot=tk.StringVar(value='100')
        self.stack=tk.StringVar(value='150')
        self.size=tk.StringVar(value='50')
        self.raise_factor=tk.StringVar(value='2.5')
        self.iters=tk.StringVar(value='2500')
        for label,var,width in [('Борд (5 карт)',self.board,17),('Банк',self.pot,8),('Эфф. стек',self.stack,10),
                                ('Ставка %',self.size,10),('Рейз ×',self.raise_factor,8),('CFR+ итерации',self.iters,12)]:
            self.field(row,label,var,width)
        rr=ttk.Frame(self);rr.pack(fill='x',pady=(0,9))
        self.a=tk.StringVar(value='AsKs,7c7d')
        self.b=tk.StringVar(value='AcQc,6c6d')
        for text,var in [('Руки A (вне позиции)',self.a),('Руки B (в позиции)',self.b)]:
            f=ttk.Frame(rr);f.pack(side='left',fill='x',expand=True,padx=(0,15))
            self.label(f,text,10,'#8cebd7',True).pack(anchor='w')
            ttk.Entry(f,textvariable=var).pack(fill='x',pady=(3,0))
        toolbar=ttk.Frame(self);toolbar.pack(fill='x',pady=(0,10))
        self.button=ttk.Button(toolbar,text='Проверить NashConv и сравнить с LP',command=self.start)
        self.button.pack(side='left')
        ttk.Button(toolbar,text='Экспорт отчёта JSON',command=self.export).pack(side='right')
        self.status=tk.StringVar(value='Готов к офлайн-проверке. Не подключается к живому столу.')
        tk.Label(self,textvariable=self.status,bg='#0c1420',fg='#a6cfda',anchor='w').pack(fill='x',pady=(0,9))
        self.output=self.app.textbox(self,height=25,readonly=True)
        self.output.pack(fill='both',expand=True)
        self.app.set_text(self.output,
            'Метрики качества стратегии для ограниченного дерева решений:\n\n'
            '• Profile EV: ожидаемые фишки при стратегии двух игроков.\n'
            '• BR A / BR B: EV при наилучшем ответе только одного игрока.\n'
            '• NashConv = BR A − BR B; ниже — лучше.\n'
            '• Exploitability = NashConv / 2 для этой двухсторонней нулевой суммы.\n'
            '• LP reference: точная минимаксная стоимость крошечной матричной игры.\n'
            '• LP duality gap: погрешность независимого оптимизатора.\n\n'
            'Измерение производится по ВСЕМ допустимым комбинациям из введённых диапазонов '
            'и ВСЕМ веткам ставок; будущих карт на ривере нет.')

    def start(self):
        try:
            board=cards(self.board.get(),5)
            ra=parse_range(self.a.get(),board);rb=parse_range(self.b.get(),board)
            if len(ra)>2 or len(rb)>2:
                raise ValueError('Для независимого LP-эталона укажи до 2 конкретных комбинаций в каждом диапазоне')
            pct=float(self.size.get());
            if not 0<pct<=300:raise ValueError('Сайзинг 1–300%')
            args=dict(board_text=self.board.get(),pot=float(self.pot.get()),stack=float(self.stack.get()),
                      a_range=self.a.get(),b_range=self.b.get(),river_sizes=self.size.get(),
                      raise_factor=float(self.raise_factor.get()),iterations=int(self.iters.get()))
        except (ValueError,TypeError) as exc:
            messagebox.showwarning('Ошибка ввода',str(exc));return
        pot_value=float(self.pot.get())
        stack_value=float(self.stack.get())
        raise_value=float(self.raise_factor.get())
        self.button.configure(state='disabled')
        self.status.set('Идёт обучение CFR+, точная проверка BR и LP-оптимизация…')
        def worker():
            try:
                solved=solve_multistreet(**args)
                try:
                    ref=solve_reference_lp(board,pot_value,stack_value,
                        solved.sizes['R'],raise_value,list(ra),list(rb),list(ra.values()),list(rb.values()))
                    ref_error=None
                except (RuntimeError,ImportError) as exc:
                    ref=None
                    ref_error=str(exc)
                self.app.events.put(('quality_ready',(solved,ref,ref_error)))
            except Exception as exc:
                self.app.events.put(('quality_ready',(None,None,str(exc))))
        threading.Thread(target=worker,daemon=True).start()

    def show_result(self,data):
        solved,ref,error=data
        self.button.configure(state='normal')
        if solved is None:
            self.status.set('Проверка завершилась с ошибкой: '+str(error))
            self.app.set_text(self.output,str(error))
            return
        meta=solved.metadata
        ev=meta['profile_ev_exact'];br_a=meta['br_a_exact'];br_b=meta['br_b_exact']
        gap=meta['nashconv'];lp=ref.equilibrium_ev if ref else None
        self.last={'strategy_input':{'board':list(solved.board),'pot':solved.pot,'stack':solved.stack,
                  'range_A':self.a.get(),'range_B':self.b.get(),'river_sizes':self.size.get(),
                  'raise_factor':solved.raise_factor,'iterations':solved.iterations},
                   'profile_ev':ev,'br_a_ev':br_a,'br_b_ev':br_b,'nashconv':gap,
                   'exploitability':meta['exploitability'],
                   'nashconv_pct_pot':meta['nashconv_pot_pct'],
                   'reference_lp_ev':lp,'reference_lp_gap':ref.duality_gap if ref else None,
                   'reference_matrix':[ref.rows,ref.cols] if ref else None,
                   'absolute_ev_diff_from_reference':abs(ev-lp) if ref else None,
                   'note':'Only for this small river abstraction, not full Holdem'}
        inside=(br_b-1e-6 <= lp <= br_a+1e-6) if ref else None
        self.status.set(('LP-эталон вычислен · NashConv измерен · ' +
                        ('все границы согласованы' if inside else 'НЕСОГЛАСОВАННОСТЬ: см. отчёт'))
                        if ref else 'NashConv измерен; LP-эталон недоступен: '+str(error))
        self.app.set_text(self.output, '\n'.join([
            f"Board {' '.join(solved.board)} | Pot {solved.pot:g} | Stack {solved.stack:g} | Size {self.size.get()}%",
            f"Допустимых пар рук: {solved.pairs} | CFR+ итераций: {solved.iterations}",
            '',
            f'Profile EV A (точный перебор):   {ev:.6f}',
            f'BR A (наилучший ответ):           {br_a:.6f}',
            f'BR B (наилучший ответ):           {br_b:.6f}',
            f'NashConv (чем ниже, тем лучше):   {gap:.6f}  ({meta["nashconv_pot_pct"]:.3f}% банка)',
            f'Exploitability (gap / 2):         {meta["exploitability"]:.6f}',
            f'Инфосетов без обученной стратегии: {meta["missing_eval_infosets"]}',
            '',
            'НЕЗАВИСИМЫЙ LP-ЭТАЛОН (SciPy HiGHS, нормальная форма игры):',
            (f'Равновесный EV A:                 {lp:.6f}' if ref else 'LP: '+str(error)),
            (f'LP duality gap:                   {ref.duality_gap:.9g}' if ref else ''),
            (f'Матрица чистых стратегий:         {ref.rows} × {ref.cols}' if ref else ''),
            (f'Отклонение профиля от эталона:    {abs(ev-lp):.6f}' if ref else ''),
            (f'Проверка BR B ≤ LP ≤ BR A:         {"PASS" if inside else "FAIL"}' if ref else ''),
            '',
            'Важно: gap точный для полученной стратегии ограниченной игры на РИВЕРЕ; '
            'это не гарантирует ничего о флопе/тёрне, рейзах поверх рейзов, рейке, '
            'разных размерах ставок или полноценном NLHE.',
        ]))

    def export(self):
        if not self.last:
            messagebox.showinfo('Экспорт','Сначала проведи проверку.');return
        path=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json')],
                                           initialfile='gto_quality_lp_reference.json')
        if not path:return
        try:Path(path).write_text(json.dumps(self.last,indent=2,ensure_ascii=False),encoding='utf-8')
        except OSError as exc:messagebox.showerror('Экспорт',str(exc));return
        self.status.set('Отчёт сохранён: '+path)
