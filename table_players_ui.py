"""Current seated players, joined to imported statistics by stable identity."""
import time
import sqlite3
import tkinter as tk
from tkinter import ttk
from profiles import player_key, snapshot_profiles


def table_rows(snapshot, profiles, in_hand=False):
    result, seen = [], set()
    for p in (snapshot or {}).get('players', []):
        key, name = player_key(p)
        if not name or key in seen:
            continue
        seen.add(key)
        inactive = p.get('folded') or any(word in str(p.get('status','')).lower() for word in ('away','offline','in next hand','sitting out'))
        if in_hand and inactive:
            continue
        result.append({'key':key, 'name':name, 'player':p, 'profile':profiles.get(key)})
    return result


class TablePlayersTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.rows = app, {}
        self.last_render = 0
        self.in_hand = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='Ожидание подключения оверлея')
        ttk.Label(self,textvariable=self.status,wraplength=950).pack(anchor='w',pady=(12,5))
        self.source = tk.StringVar(value='Со стола')
        source = ttk.Combobox(self,textvariable=self.source,values=('Со стола','Полные руки (LOG / CSV)'),state='readonly',width=30)
        source.pack(anchor='w',pady=5);source.bind('<<ComboboxSelected>>',self.change_source)
        self.basis = tk.StringVar()
        ttk.Label(self,textvariable=self.basis,wraplength=1050).pack(anchor='w',pady=5)
        ttk.Checkbutton(self,text='Только в раздаче (по видимому статусу)',variable=self.in_hand,command=lambda:self.refresh(force=True)).pack(anchor='w',pady=5)
        frame=ttk.Frame(self);frame.pack(fill='both',expand=True)
        columns=('name','stack','state','hands','vpip','pfr','threebet','f3bet','af','sample','live_seen','live_actions')
        action_columns=tuple('live_'+k for k in ('call','raise','bet','check','fold','chips'))
        self.tree=ttk.Treeview(frame,columns=columns+action_columns,show='headings',selectmode='browse',height=10)
        for col,title,width in zip(columns,('Игрок','Стек','Статус','Рук','VPIP','PFR','3-bet','Fold vs 3-bet','AF','Выборка','Набл. рук*','Действий*'),(150,70,140,60,65,65,65,100,60,130,90,90)):
            self.tree.heading(col,text=title);self.tree.column(col,width=width,minwidth=50,anchor='w' if col in ('name','state','sample') else 'center')
        for col,title in zip(action_columns,('Call','Raise','Bet','Check','Fold','Ставка ↑*')):
            self.tree.heading(col,text=title);self.tree.column(col,width=72,minwidth=50,anchor='center')
        vertical=ttk.Scrollbar(frame,command=self.tree.yview);vertical.pack(side='right',fill='y')
        horizontal=ttk.Scrollbar(self,orient='horizontal',command=self.tree.xview);horizontal.pack(fill='x')
        self.tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set);self.tree.pack(fill='both',expand=True)
        self.tree.bind('<<TreeviewSelect>>',self.select)
        self.detail=app.textbox(self,height=7,readonly=True);self.detail.pack(fill='x',pady=8)
        self.open_button=ttk.Button(self,text='Открыть профиль и редактирование заметки',command=self.open_profile,state='disabled');self.open_button.pack(anchor='w',pady=5)
        self.change_source()

    def change_source(self,_event=None):
        live=self.source.get()=='Со стола'
        columns=('name','stack','state','live_seen','live_actions','live_call','live_raise','live_bet','live_check','live_fold','live_chips') if live else ('name','stack','state','hands','vpip','pfr','threebet','f3bet','af','sample')
        self.tree.configure(displaycolumns=columns)
        self.basis.set('Наблюдения без LOG. Набл. рук* — частичные наблюдения, не полные истории. Ставка ↑* — изменение без распознанного действия. Возможны пропуски.' if live else 'Полные руки из LOG / CSV. «—» означает отсутствие рук или возможностей для показателя, а не 0%.')
        self.basis.set(self.basis.get()+' Данные по всем сохранённым столам; типы игр не разделены.')
        self.select()

    def refresh(self, force=False):
        now=time.monotonic()
        if not force and now-self.last_render<1:
            return
        self.last_render=now
        snap=self.app.live
        age=now-self.app.live_received if self.app.live_received is not None else None
        fresh=snap is not None and age is not None and age<8
        if not fresh:
            self.status.set('Нет свежих данных от оверлея. Включите передачу данных и откройте нужный стол.')
            self.tree.delete(*self.tree.get_children());self.rows={}
            self.app.set_text(self.detail,'Список скрыт, чтобы не выдавать старый состав за текущий.')
            self.open_button.configure(state='disabled');return
        try:
            profiles=snapshot_profiles(self.app.db_path,snap.get('players',[]))
        except (sqlite3.Error, ValueError):
            self.status.set('Статистика временно недоступна; повторная проверка через секунду.')
            self.tree.delete(*self.tree.get_children());self.rows={}
            self.app.set_text(self.detail,'Не удалось прочитать статистику.');self.open_button.configure(state='disabled');return
        rows=table_rows(snap,profiles,self.in_hand.get())
        self.status.set(f"Стол {snap.get('tableId','?')} · {len(rows)} игроков · обновлено {age:.0f} сек. назад · при нескольких вкладках показывается последний приславший снимок стол")
        chosen=self.tree.selection();chosen=chosen[0] if chosen else None
        existing=set(self.tree.get_children());self.rows={r['key']:r for r in rows}
        percent=lambda value:'—' if value is None else f'{value:g}%'
        for index,r in enumerate(rows):
            p=r['player'];s=r['profile'] or {};h=s.get('hands',0)
            values=(r['name']+(' ★' if p.get('isMe') else ''),p.get('stack') if p.get('stack') is not None else '—',p.get('status') or ('Fold' if p.get('folded') else 'За столом'),h,
                    percent(s.get('vpip')),percent(s.get('pfr')),percent(s.get('threebet')),percent(s.get('f3bet')),s.get('af') if s.get('af') is not None else '—','Нет рук' if not h else 'Малая (<50 рук)' if h<50 else f'{h} рук')
            values += (s.get('live',{}).get('seen',0),s.get('live',{}).get('actions',0))
            values += tuple(s.get('live',{}).get(k,0) for k in ('call','raise','bet','check','fold','chips'))
            if r['key'] in existing:self.tree.item(r['key'],values=values);existing.remove(r['key'])
            else:self.tree.insert('',index,iid=r['key'],values=values)
            self.tree.move(r['key'],'',index)
        for key in existing:self.tree.delete(key)
        if chosen in self.rows:self.tree.selection_set(chosen)
        self.select()

    def select(self,_event=None):
        selection=self.tree.selection();r=self.rows.get(selection[0]) if selection else None
        self.open_button.configure(state='normal' if r else 'disabled')
        if not r:self.app.set_text(self.detail,'Выберите игрока: замеченные действия, история имён и заметки.');return
        p=r['profile'] or {};op=p.get('opportunities',{})
        text=f"{r['name']} · {'PokerNow ID' if r['key'].startswith('p:') else 'Только ник — личность не подтверждена'}\n"
        text+='История ников: '+(', '.join(p.get('aliases',[])) or '—')+'\n'
        live=p.get('live',{})
        text+='Со стола*: '+', '.join(f'{k}={live.get(k,0)}' for k in ('call','raise','bet','check','fold','chips'))+'\n* Частичные наблюдения; возможны пропуски. chips — изменение ставки без распознанного действия.\n'
        text+=f"Возможностей для 3-bet: {op.get('threebet',0)} · против 3-bet: {op.get('f3bet',0)} · postflop-коллов для AF: {op.get('post_call',0)}\n"
        text+='Заметка: '+(p.get('note') or '—')+'\nМалая выборка — предупреждение; 50 рук не гарантируют надёжность выводов.'
        self.app.set_text(self.detail,text)

    def open_profile(self):
        selection=self.tree.selection()
        if not selection or selection[0] not in self.rows:return
        key=selection[0]
        self.app.refresh_table()
        if self.app.tree.exists(key):
            self.app.tree.selection_set(key);self.app.tree.see(key);self.app.select_player()
            self.app.notebook.select(self.app.dashboard_tab)
