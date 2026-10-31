"""Offline multi-street abstract CFR+ study tab. Never touches live controls."""
from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from gto_solver import cards, completed_river_boards
from multistreet_solver import solve_multistreet, parse_street_sizes, audit_saved_multistreet
from benchmark_training import run_benchmark
from benchmark_v8 import compare_private_sampling
from benchmark_v9 import compare_coverage


class MultiStreetTab(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent)
        self.app=app
        self.last=None
        self.last_args=None
        self._build()

    def label(self,parent,text,size=10,color='#c9d9e7',bold=False):
        return tk.Label(parent,text=text,bg='#0c1420',fg=color,anchor='w',justify='left',
                        font=('Segoe UI',size,'bold' if bold else 'normal'))

    def entry(self,parent,name,var,width=10):
        f=ttk.Frame(parent)
        f.pack(side='left',padx=(0,13))
        self.label(f,name,9).pack(anchor='w')
        ttk.Entry(f,textvariable=var,width=width).pack(anchor='w',pady=(3,0))

    def _build(self):
        self.label(self,'MULTISTREET · FLOP → TURN → RIVER · CFR+ v8',17,'#7ae4d9',True).pack(anchor='w',pady=(9,3))
        self.label(self,'ОФФЛАЙН учебная игра HU: на каждой улице CHECK / BET (1–2 сайзинга), FOLD / CALL / один RAISE. '
                   'Карты следующих улиц открываются по очереди; после колла раздача продолжается.',10,'#adcede').pack(anchor='w')
        self.label(self, 'НЕ полный NLHE GTO: нет 3-бетов/4-бетов и мультипотов. Для флопа и тёрна '
                   'NashConv доступен через отдельный полный аудит небольших задач; сходимость не гарантирована.' ,9,'#dfbf86').pack(anchor='w',pady=(2,10))
        row=ttk.Frame(self);row.pack(fill='x',pady=(0,8))
        self.board=tk.StringVar(value='Ah 7d 2c')
        self.pot=tk.StringVar(value='100')
        self.stack=tk.StringVar(value='200')
        self.fsize=tk.StringVar(value='50')
        self.tsize=tk.StringVar(value='75')
        self.rsize=tk.StringVar(value='75')
        self.raise_factor=tk.StringVar(value='2.5')
        self.iterations=tk.StringVar(value='1500')
        self.inspect=tk.StringVar(value='')
        for n,v,w in [('Борд 3–5 карт',self.board,17),('Банк',self.pot,7),('Эфф. стек',self.stack,9),
                      ('Флоп BET %',self.fsize,10),('Тёрн BET %',self.tsize,10),
                      ('Ривер BET %',self.rsize,10),('Рейз ×',self.raise_factor,6),('Итераций',self.iterations,8)]:
            self.entry(row,n,v,w)
        rr=ttk.Frame(self);rr.pack(fill='x',pady=(0,8))
        self.a=tk.StringVar(value='AsKs,AcKc,QcQd,JcJd')
        self.b=tk.StringVar(value='KsQs,KcQc,9h9s,ThTd')
        for title,value in [('Диапазон A · вне позиции',self.a),('Диапазон B · в позиции',self.b)]:
            f=ttk.Frame(rr);f.pack(side='left',fill='x',expand=True,padx=(0,10))
            self.label(f,title,10,'#99e5d4',True).pack(anchor='w')
            ttk.Entry(f,textvariable=value).pack(fill='x',pady=(4,0))
        irow=ttk.Frame(self);irow.pack(fill='x',pady=(0,8))
        self.entry(irow,'Следующие открытые карты для разбора конкретной линии (НЕ влияют на обучение)',self.inspect,14)
        self.label(irow,'Например 9s Kd на флопе, Kd на тёрне; пусто = демонстрационные карты',9,'#8eafba').pack(side='left',pady=(20,0))
        config=ttk.Frame(self);config.pack(fill='x',pady=(0,8))
        self.averaging=tk.StringVar(value='linear')
        self.chance_sampling=tk.StringVar(value='stratified')
        self.exact_river=tk.StringVar(value='auto')
        self.private_sampling=tk.StringVar(value='systematic')
        for name,var,values,width in [
            ('Усреднение CFR+',self.averaging,('linear','uniform'),12),
            ('Выбор будущих карт',self.chance_sampling,('stratified','random'),14),
            ('Пары рук',self.private_sampling,('systematic','balanced','random','paired'),13),
            ('Ривер: перебор рук',self.exact_river,('auto','never','always'),12),
        ]:
            frame=ttk.Frame(config);frame.pack(side='left',padx=(0,16))
            self.label(frame,name,9).pack(anchor='w')
            ttk.Combobox(frame,textvariable=var,values=values,width=width,state='readonly').pack(anchor='w',pady=(3,0))
        self.label(config,'systematic = равномернее по рукам; paired = все пары/эпоха (до 16).',9,'#8eafba').pack(side='left',padx=8)
        tools=ttk.Frame(self); tools.pack(fill='x',pady=(0,6))
        self.compute=ttk.Button(tools,text='Рассчитать 3 улицы (офлайн)',command=self.start)
        self.compute.pack(side='left')
        self.audit_button=ttk.Button(tools,text='Аудит NashConv · всё дерево',command=self.audit, state='disabled')
        self.audit_button.pack(side='left',padx=(10,0))
        self.benchmark_button=ttk.Button(tools,text='Сравнить с v6 · график NashConv',
                                        command=self.benchmark, state='disabled')
        self.benchmark_button.pack(side='left',padx=(10,0))
        self.compare_v8_button=ttk.Button(tools,text='Сравнить v7 / v8 · NashConv',command=self.benchmark_v8,state='disabled')
        self.compare_v8_button.pack(side='left',padx=(10,0))
        ttk.Button(tools,text='Борд из завершённой CSV',command=self.load_completed_board).pack(side='left',padx=10)
        ttk.Button(tools,text='Объяснить результат через AI',command=self.explain).pack(side='right')
        ttk.Button(tools,text='Экспорт JSON',command=self.export_json).pack(side='right',padx=(0,8))
        self.coverage_button=ttk.Button(self,text='Покрытие v8 / v9',command=self.benchmark_v9)
        self.coverage_button.pack(anchor='w',pady=4)
        self.status=tk.StringVar(value='Расчёт автономен: не читает текущие игровые кнопки и не управляет столом.')
        tk.Label(self,textvariable=self.status,bg='#0c1420',fg='#a6cfda',anchor='w',justify='left',
                 wraplength=1260,font=('Segoe UI',10)).pack(fill='x',pady=(0,9))
        content=ttk.Frame(self);content.pack(fill='both',expand=True)
        left=ttk.Frame(content);left.pack(side='left',fill='both',expand=True,padx=(0,8))
        self.label(left,'A · частоты действий на начальной улице',11,'#88ecd1',True).pack(anchor='w',pady=(0,5))
        self.table=ttk.Treeview(left,columns=('class','combos','check','bet1','bet2'),show='headings',height=14)
        for col,heading,width in [('class','Рука',80),('combos','Комбо',66),('check','CHECK',80),('bet1','BET 1',95),('bet2','BET 2',95)]:
            self.table.heading(col,text=heading)
            self.table.column(col,width=width,anchor='center')
        sc=ttk.Scrollbar(left,orient='vertical',command=self.table.yview)
        self.table.configure(yscrollcommand=sc.set)
        self.table.pack(side='left',fill='both',expand=True)
        sc.pack(side='right',fill='y')
        right=ttk.Frame(content);right.pack(side='right',fill='both',expand=True,padx=(8,0))
        self.label(right,'EV · пройденные улицы · диапазоны после BET–CALL',11,'#88ecd1',True).pack(anchor='w',pady=(0,5))
        self.report=self.app.textbox(right,height=21,readonly=True)
        self.report.pack(fill='both',expand=True)
        self.app.set_text(self.report,'Введи исходный борд, диапазоны и банк/стеки.\n\n'
                          'Для флопа движок моделирует действия на флопе, тёрне и ривере; для тёрна — '
                          'тёрн и ривер. При выборе ставки и колла модель обновляет условные диапазоны '
                          'с учётом частот действий и блокеров.\n\n'
                          'Чем больше сайзингов, тем дольше сходимость и выше расход памяти.')

    def start(self):
        try:
            board=cards(self.board.get())
            if len(board) not in (3,4,5):raise ValueError('Требуется 3, 4 или 5 карт')
            parse_street_sizes(self.fsize.get(),self.tsize.get(),self.rsize.get())
            args=dict(board_text=self.board.get(),pot=float(self.pot.get()),stack=float(self.stack.get()),
                      a_range=self.a.get(),b_range=self.b.get(),flop_sizes=self.fsize.get(),
                      turn_sizes=self.tsize.get(),river_sizes=self.rsize.get(),
                      raise_factor=float(self.raise_factor.get()),iterations=int(self.iterations.get()),
                      inspect_runout=self.inspect.get(),averaging=self.averaging.get(),
                      chance_sampling=self.chance_sampling.get(),exact_river=self.exact_river.get(),private_sampling=self.private_sampling.get())
        except (TypeError,ValueError) as exc:
            messagebox.showwarning('Ошибка ввода',str(exc));return
        self.compute.configure(state='disabled')
        self.audit_button.configure(state='disabled')
        self.benchmark_button.configure(state='disabled')
        self.compare_v8_button.configure(state='disabled')
        self.last_args=args
        self.last=None
        self.status.set('Выполняется многоуличная симуляция и расчёт CFR+ (экспериментальный)…')
        def work():
            try:self.app.events.put(('multistreet_ready',(solve_multistreet(**args),None)))
            except Exception as exc:self.app.events.put(('multistreet_ready',(None,str(exc))))
        threading.Thread(target=work,daemon=True).start()

    def show_result(self,payload):
        self.compute.configure(state='normal')
        result,error=payload
        if error:
            self.status.set('Расчёт не завершён: '+error)
            return
        self.last=result
        self.audit_button.configure(state='normal')
        self.benchmark_button.configure(state='normal')
        self.compare_v8_button.configure(state='normal')
        self.status.set(f'{len(result.board)} карт в начале · A: {result.n_a} комбо · B: {result.n_b} комбо · '
                        f'{result.pairs} допустимых пар · {result.iterations:,} итераций · ' +
                        ('River NashConv рассчитан' if result.metadata['nashconv'] is not None else
                         'многоуличная стратегия не сертифицирована'))
        old=self.table.get_children()
        if old:self.table.delete(*old)
        for row in result.root_strategies:
            values=list(row['actions'].values())
            self.table.insert('',tk.END,values=(row['class'],row['combos'],
                *( [f'{v:.1f}%' for v in values]+['—']*3)[:3]))
        labels={'F':'Флоп','T':'Тёрн','R':'Ривер'}
        report=[f"Начальный борд: {' '.join(result.board)}  ·  банк {result.pot:g} · стек {result.stack:g}",
                f"Средний EV при обучении A: {result.mean_ev:.2f} фишки (не EV итоговой стратегии).",
                f"Итераций: {result.iterations:,}; обновлений миров: {result.metadata['world_updates']:,}; "
                f"метод: {result.metadata['method']}.",
                f"Усреднение: {result.metadata['averaging']}; карты: {result.metadata['chance_sampling']}; пары: {result.metadata['private_sampling']}.",
                ('River exact NashConv: %.4f (%.3f%% банка), exploitability %.4f; BR A: %.3f, BR B: %.3f; непокрытые инфосеты: %d' %
                 (result.metadata['nashconv'],result.metadata['nashconv_pot_pct'],
                  result.metadata['exploitability'],result.metadata['br_a_exact'],
                  result.metadata['br_b_exact'],result.metadata['missing_eval_infosets']))
                 if result.metadata['nashconv'] is not None else
                 'Многоуличный NashConv ещё не измерен. Нажми «Аудит NashConv · всё дерево» для небольшой задачи.',
                '', 'Покрытие приватных пар: ' + str(result.metadata['pair_coverage']['visited']) + '/' + str(result.pairs),
                'Покрытый вес диапазона: %.2f%%; ESS по весам: %.1f (%.1f%% миров).' % (
                    result.metadata['pair_coverage']['target_mass_pct'], result.metadata['pair_coverage']['ess'],
                    result.metadata['pair_coverage']['ess_pct']),
                'Покрытие и ESS не доказывают равновесие; balanced не гарантирует улучшения NashConv.',
                '', 'Информационные узлы по улицам:']
        for street in ('F','T','R'):
            if street in result.public_nodes:
                report.append(f"  {labels[street]}: {result.public_nodes[street]:,}")
        if result.flop_b_responses:
            report += ['','B · ответ на первую ставку A:']
            for resp in result.flop_b_responses:
                report.append(f"  {resp['size']}: " + ', '.join(f'{a} {p:.1f}%' for a,p in resp['actions'].items()))
            report += ['','Условный диапазон после линии A BET → B CALL:']
            for name,item in result.posterior.items():
                report.append(f'  {item["line"]} (вес линии {item["joint_weight"]*100:.2f}%):')
                report.append('    A: '+', '.join(f'{r["class"]} {r["probability_pct"]:.0f}%' for r in item['A'][:8]))
                report.append('    B: '+', '.join(f'{r["class"]} {r["probability_pct"]:.0f}%' for r in item['B'][:8]))
        if result.example_path:
            report += ['', 'Пошаговое обновление условных диапазонов по выбранному ранауту:']
            for step in result.example_path:
                report.append(f"  {step['board']}: {step['line']} (P линии {step['prob_pct']:.1f}%)")
                report.append('    A: '+', '.join(f'{x["class"]} {x["probability_pct"]:.0f}%' for x in step['A'][:6]))
                report.append('    B: '+', '.join(f'{x["class"]} {x["probability_pct"]:.0f}%' for x in step['B'][:6]))
                report.append(f"    Покрытие обученных узлов A/B: {step['node_coverage_a_pct']:.0f}% / {step['node_coverage_b_pct']:.0f}%")
            report.append('  Важно: неизвестные обучению узлы используют равномерный запасной выбор. Низкое покрытие = низкая надёжность.')
        report += ['', 'Ограничения: heads-up; не более 2 BET-сайзингов на улицу; только один рейз;',
                   'нет 3-бета/мультипотов; текущие диапазоны заданы вручную и не являются картами противника.',
                   'Выборка шансов и стратегий ограничена. Для оценки качества сравнивай с эталонным солвером.']
        self.app.set_text(self.report,'\n'.join(report))
        self.app.multistreet_context={
            'type':'posthand_offline_multistreet_abstraction',
            'board':list(result.board),'pot':result.pot,'stack':result.stack,
            'bet_sizes':result.sizes,'iterations':result.iterations,
            'training_ev_a':result.mean_ev,'root_strategies':result.root_strategies[:30],
            'responses':result.flop_b_responses,'posterior_after_bet_call':result.posterior,
            'sequential_range_updates':result.example_path,
            'node_counts':result.public_nodes,'limitations':result.metadata}

    def benchmark_v9(self):
        if self.last is None or self.last_args is None:
            messagebox.showinfo('Покрытие', 'Сначала выполни расчёт.')
            return
        last, args = self.last, dict(self.last_args)
        self.coverage_button.configure(state='disabled')
        self.status.set('Сравнение покрытия systematic / balanced, одинаковое число миров…')
        def work():
            try:
                payload = (last, compare_coverage(args, iterations=min(650,last.iterations)), None)
            except Exception as exc:
                payload = (last, None, str(exc))
            self.app.events.put(('multistreet_v9_ready', payload))
        threading.Thread(target=work,daemon=True).start()

    def show_v9(self, payload):
        last, report, error = payload
        self.coverage_button.configure(state='normal')
        if error:
            self.status.set(error)
        elif last is self.last:
            self.last.metadata['v9_coverage_comparison'] = report
            lines = ['\nПОКРЫТИЕ v8 / v9 (не оценка равновесия)']
            for r in report['results']:
                lines.append(f"{r['mode']} seed={r['seed']}: {r['visited']}/{r['eligible']} пар, вес {r['target_mass_pct']:.2f}%, ESS {r['ess_pct']:.1f}%, миров {r['world_updates']}")
            self.app.set_text(self.report,self.report.get('1.0','end-1c')+'\n'.join(lines))
            self.status.set('Сравнение покрытия сохранено в JSON результата.')

    def benchmark_v8(self):
        if self.last is None or self.last_args is None:
            return
        if len(self.last.board)==5:
            messagebox.showinfo('v8','На ривере используется другой, точный перебор пар. Сравнивай флоп/тёрн.')
            return
        self.compare_v8_button.configure(state='disabled')
        self.status.set('Сравнение v7 и v8 по 3 seed, равное число миров, точный аудит…')
        last=self.last
        args=dict(self.last_args)
        def work():
            try:
                report=compare_private_sampling(args,iterations=min(650,last.iterations))
                payload=(last,report,None)
            except Exception as exc:
                payload=(last,None,str(exc))
            self.app.events.put(('multistreet_v8_benchmark_ready',payload))
        threading.Thread(target=work,daemon=True).start()

    def show_v8_benchmark(self,payload):
        last,report,error=payload
        if last is not self.last:
            return
        self.compare_v8_button.configure(state='normal')
        if error:
            self.status.set('Сравнение v8 не выполнено: '+error)
            return
        self.last.metadata['v8_comparison']=report
        lines=['','='*65,'СТРАТИФИКАЦИЯ ПАР РУК · v7 vs v8',
               'При одинаковом числе миров (итерации на обеих сторонах равны):']
        for item in report['results']:
            lines.append(f"  seed={item['seed']}: v7 {item['v7_random']['nashconv']:.3f} | v8 {item['v8_systematic']['nashconv']:.3f}; "
                         f"необучено v7/v8: {item['v7_random']['missing_infosets']}/{item['v8_systematic']['missing_infosets']}")
        lines.append(f"Средний NashConv: v7={report['mean_nashconv_v7']:.3f} | v8={report['mean_nashconv_v8']:.3f}; "
                     f"снижение {report['mean_reduction_pct']}% (отрицательное число = ухудшение).")
        lines.append('Это маленький контрольный тест, не гарантия улучшений на иных диапазонах.')
        self.app.set_text(self.report,self.report.get('1.0','end-1c')+'\n'+'\n'.join(lines))
        self.status.set('Аудит v7/v8 выполнен. Результаты войдут в экспорт JSON.')

    def benchmark(self):
        """Compare actual BR gaps at 3 budgets without touching the live table."""
        if self.last is None or self.last_args is None:
            messagebox.showinfo('Сравнение','Сначала рассчитай стратегию.');return
        tested=self.last
        kwargs=dict(self.last_args)
        n=min(int(tested.iterations),3000)
        checkpoints=tuple(sorted(set((max(200,n//4),max(200,n//2),n))))
        self.benchmark_button.configure(state='disabled')
        self.status.set('Офлайн: сравнение двух методов по точному NashConv. Для больших диапазонов есть лимит.')
        def work():
            try:
                report=run_benchmark(kwargs,checkpoints,include_lp=(len(tested.board)==5))
                payload=(tested,report,None)
            except Exception as exc:
                payload=(tested,None,str(exc))
            self.app.events.put(('multistreet_benchmark_ready',payload))
        threading.Thread(target=work,daemon=True).start()

    def show_benchmark(self,payload):
        old,report,error=payload
        if old is not self.last:return
        self.benchmark_button.configure(state='normal')
        if error:
            self.status.set('Сравнение не выполнено: '+error)
            self.app.set_text(self.report,self.report.get('1.0','end-1c') +
                              '\n\nСРАВНЕНИЕ НЕ ВЫПОЛНЕНО: '+error)
            return
        self.last.metadata['convergence_benchmark']=report
        summary=['','='*58,'СРАВНЕНИЕ ОБУЧЕНИЯ · ТОЧНЫЙ NashConv','Итерации | v6 baseline | v7 | изменение | обработано миров v6/v7']
        for r in report['comparison']:
            pct=r['nashconv_reduction_pct']
            change=('снижение %.1f%%'%pct if pct is not None and pct>=0 else
                    'рост %.1f%%'%(-pct) if pct is not None else 'н/д')
            summary.append(f"{r['iterations']:,} | {r['baseline_nashconv']:.4f} | {r['v7_nashconv']:.4f} | "
                           f"{change} | {r['baseline_world_updates']:,}/{r['v7_world_updates']:,}")
        if report['lp_reference'] and report['lp_reference'].get('equilibrium_ev') is not None:
            lp=report['lp_reference']
            summary.append(f"LP-эталон EV: {lp['equilibrium_ev']:.6f}, "
                           f"разность EV v7: {lp['v7_last_ev_abs_error']:.6f}")
        summary.extend(['Внимание: один seed, одинаковые итерации, но разное число миров на ривере.',
                        'Ни один отдельный тест не доказывает сходимость для любого диапазона.',
                        'Подробности сохраняются через «Экспорт JSON».'])
        self.app.set_text(self.report,self.report.get('1.0','end-1c')+'\n'+'\n'.join(summary))
        self.status.set('Сравнение завершено: '+', '.join(f"{r['iterations']} эпох" for r in report['comparison']))
        self.show_convergence_chart(report)

    def show_convergence_chart(self,report):
        """Native Tk canvas curve — no extra plotting dependencies."""
        win=tk.Toplevel(self)
        win.title('PokerNow Analyst · NashConv по эпохам · ограниченная HU-модель')
        win.configure(bg='#0c1420')
        win.geometry('830x480')
        canvas=tk.Canvas(win,width=800,height=380,bg='#0c1420',highlightthickness=0)
        canvas.pack(fill='both',expand=True,padx=15,pady=12)
        series=[('v6 baseline',report['modes']['v6_like_baseline'],'#f0b26c'),
                ('v7 improved',report['modes']['v7_improved'],'#78e4ce')]
        pts=[p for _,xs,_ in series for p in xs]
        x0,y0,x1,y1=80,32,740,330
        ymax=max(1.,max(p['nashconv'] for p in pts)*1.12)
        xmax=max(p['iterations'] for p in pts)
        canvas.create_line(x0,y0,x0,y1,x1,y1,fill='#839aa6',width=2)
        for t in range(5):
            y=y1-(y1-y0)*t/4
            canvas.create_line(x0,y,x1,y,fill='#1c3540',dash=(4,5))
            canvas.create_text(x0-10,y,text=f'{ymax*t/4:.2f}',fill='#b3ccd3',anchor='e',font=('Segoe UI',10))
        for n in report['checkpoints']:
            x=x0+(x1-x0)*n/xmax
            canvas.create_text(x,y1+16,text=f'{n:,}',fill='#b3ccd3',font=('Segoe UI',10))
        canvas.create_text((x0+x1)/2,y1+39,text='Эпохи обучения',fill='#d0e4e8',font=('Segoe UI',10))
        canvas.create_text(18,15,text='NashConv (фишки)',anchor='nw',fill='#d0e4e8',font=('Segoe UI',10))
        for i,(name,values,color) in enumerate(series):
            coords=[]
            for point in values:
                x=x0+(x1-x0)*point['iterations']/xmax
                y=y1-(y1-y0)*point['nashconv']/ymax
                coords.extend([x,y])
                canvas.create_oval(x-4,y-4,x+4,y+4,fill=color,outline=color)
            if len(coords)>=4:canvas.create_line(*coords,fill=color,width=3)
            canvas.create_line(540+i*105,18,565+i*105,18,fill=color,width=3)
            canvas.create_text(571+i*105,18,text=name,anchor='w',fill=color,font=('Segoe UI',9))
        self.label(win,'Два метода · одинаковые диапазоны и seed · world_updates могут различаться. '
                   'Меньше NashConv = лучше только внутри выбранной ограниченной игры.',9,'#aacad3').pack(padx=15,pady=(0,15))

    def audit(self):
        if self.last is None:
            messagebox.showinfo('Аудит', 'Сначала рассчитай CFR+ стратегию.')
            return
        tested=self.last
        self.audit_button.configure(state='disabled')
        self.status.set('Точный перебор полной колоды и best response для обоих игроков…')
        def work():
            try:
                diagnostic=audit_saved_multistreet(tested)
                payload=(tested,diagnostic,None)
            except Exception as exc:
                payload=(tested,None,str(exc))
            self.app.events.put(('multistreet_audit_ready',payload))
        threading.Thread(target=work,daemon=True).start()

    def show_audit(self,payload):
        old,diag,error=payload
        if old is not self.last:
            return  # a newer training result replaced this one
        self.audit_button.configure(state='normal')
        if error:
            self.status.set('Аудит не завершён: '+error)
            self.app.set_text(self.report,self.report.get('1.0','end-1c') +
                '\n\nАУДИТ НЕ ПРОВЕДЁН: '+error+'\nМногоуличный NashConv остаётся неизвестным.')
            return
        data=asdict(diag)
        self.last.metadata.update({
            'multistreet_audit':data,
            'nashconv':diag.nashconv,
            'exploitability':diag.exploitability,
            'profile_ev_exact':diag.profile_ev,
            'br_a_exact':diag.br_a_ev,
            'br_b_exact':diag.br_b_ev,
            'nashconv_pot_pct':diag.nashconv_pot_pct,
            'missing_eval_infosets':diag.missing_infosets,
            'quality_scope':'exact_br_bounded_multistreet_full_52_card_deck',
        })
        self.last.status='Exact best responses measured for this bounded abstract tree'
        self.status.set('Точный многоуличный аудит завершён; NashConv %.4f, %s миров; неизвестных инфосетов %s' %
                        (diag.nashconv,f'{diag.worlds:,}',f'{diag.missing_infosets:,}'))
        lines=['', '='*58,'ТОЧНЫЙ АУДИТ МНОГОУЛИЧНОГО ДЕРЕВА',
              f'Версия игры: {diag.model}; колода: {diag.chance_scope}',
              f'EV профиля A: {diag.profile_ev:.5f}',
              f'Лучший ответ A: {diag.br_a_ev:.5f}; лучший ответ B: {diag.br_b_ev:.5f}',
              f'NashConv = {diag.nashconv:.5f} фишки ({diag.nashconv_pot_pct:.3f}% банка)',
              f'Exploitability = {diag.exploitability:.5f} фишки',
              f'Допустимых миров: {diag.worlds:,}; посещений состояний: {diag.visited_world_states:,}',
              f'Необученных информационных множеств (равномерный fallback): {diag.missing_infosets:,}',
              '', 'Внимание: проверено ВСЁ заданное ограниченное дерево, не полный NLHE.',
              'Большое число fallback-узлов указывает на недостаточное покрытие обучением.',
              'Низкий NashConv только для тех диапазонов и разрешённых ставок, которые заданы.']
        self.app.set_text(self.report,self.report.get('1.0','end-1c')+'\n'+'\n'.join(lines))
        if self.app.multistreet_context is not None:
            self.app.multistreet_context['exact_bounded_audit']=data
            self.app.multistreet_context['limitations']=self.last.metadata

    def load_completed_board(self):
        path=filedialog.askopenfilename(filetypes=[('PokerNow CSV','*.csv *.txt'),('Все файлы','*.*')])
        if not path:return
        try:
            found=completed_river_boards(Path(path).read_text(encoding='utf-8-sig'))
        except (UnicodeError,OSError) as exc:
            messagebox.showerror('CSV',str(exc));return
        if not found:
            messagebox.showwarning('CSV','Нет завершённых раздач с полным бордом.');return
        self.board.set(' '.join(found[-1][:3]))
        self.status.set('Загружен флоп из завершённой раздачи. Диапазоны/банк/стеки задай вручную.')

    def export_json(self):
        if not self.last:
            messagebox.showinfo('Экспорт','Сначала выполни расчёт.');return
        path=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json')],
                                          initialfile='pokernow_multistreet_study.json')
        if not path:return
        try:Path(path).write_text(json.dumps(asdict(self.last),ensure_ascii=False,indent=2),encoding='utf-8')
        except OSError as exc:messagebox.showerror('Файл',str(exc));return
        self.status.set('Экспортирован результат: '+path)

    def explain(self):
        if not self.last:
            messagebox.showinfo('AI','Сначала выполни расчёт.');return
        self.app.question.delete('1.0',tk.END)
        self.app.question.insert('1.0','Объясни учебный многоуличный расчёт завершённой раздачи. '
            'Разбери обновление диапазонов после BET/CALL, условность EV и ограничение по одному рейзу. '
            'Метод обучения, NashConv и проверка сходимости описаны в контексте; не называй это полным GTO.')
        self.app.notebook.select(self.app.agent_tab)
        self.app.set_text(self.app.answer,'Офлайн-результат добавлен в контекст. Для отправки в AI API требуется явное подтверждение.')
