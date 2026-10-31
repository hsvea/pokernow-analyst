import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from tkinter import messagebox, ttk, filedialog
import release_config
import updates


class UpdateUI:
    def __init__(self, app, parent, data):
        self.app, self.data = app, data
        self.busy, self.offer = False, None
        self.button = ttk.Button(parent, text='Проверить обновления', command=self.check)
        self.button.pack(anchor='w', pady=5)
        self.install_button = ttk.Button(parent, text='Установить обновление', command=self.install)
        ttk.Button(parent,text='Установить скачанный ZIP',command=self.install_zip).pack(anchor='w',pady=5)
        app.after(3000, lambda: self.check(automatic=True))

    def check(self, automatic=False):
        if self.busy:
            return
        self.busy = True
        self.button.configure(state='disabled')
        def worker():
            try:
                result = updates.check(release_config.REPOSITORY, release_config.VERSION)
                self.app.events.put(('update', ('checked', result, automatic)))
            except Exception as exc:
                self.app.events.put(('update', ('error', str(exc), automatic)))
        threading.Thread(target=worker, daemon=True).start()

    def handle(self, event):
        kind, result, automatic = event
        self.busy = False
        self.button.configure(state='normal')
        if kind == 'checked':
            self.offer = result
            if result:
                self.button.configure(text='Доступна версия ' + result['version'])
                self.install_button.pack(anchor='w', pady=5)
                self.app.footer_var.set('Доступно обновление ' + result['version'] + ' · вкладка «Подключение и безопасность»')
            elif not automatic:
                messagebox.showinfo('Обновления', 'Установлена актуальная версия.')
        elif kind == 'error':
            if not automatic:
                messagebox.showerror('Обновления', result)
        elif kind == 'downloaded':
            try:
                subprocess.Popen([str(Path(result).parent / 'PokerNowUpdater.exe'), result], cwd=Path(result).parent)
                self.app.shutdown()
                return True
            except Exception as exc:
                messagebox.showerror('Обновления', str(exc))

    def install_zip(self):
        if not self.offer:
            messagebox.showinfo('ZIP', 'Сначала проверю актуальный релиз на GitHub. Затем повтори выбор ZIP. Его SHA-256 должен совпасть с опубликованным релизом.')
            self.check()
            return
        path=filedialog.askopenfilename(filetypes=[('Windows release','*.zip')])
        if path:
            self.install(local_archive=path)

    def install(self, local_archive=None):
        if self.busy or not self.offer:
            return
        root = Path(sys.executable).resolve().parent.parent
        if not getattr(sys, 'frozen', False) or root != (Path(os.environ['LOCALAPPDATA']) / 'PokerNowAnalystApp').resolve():
            messagebox.showinfo('Установка', 'Для автообновлений установи Windows-комплект в %LOCALAPPDATA%\\PokerNowAnalystApp. Инструкция — DELIVERY_RU.md.')
            return
        if not messagebox.askyesno('Обновление', 'Скачать и установить версию ' + self.offer['version'] + '? Приложение закроется и перезапустится. После обновления перезагрузи расширение в Opera.'):
            return
        self.busy = True
        self.button.configure(state='disabled')
        offer = dict(self.offer)
        def worker():
            try:
                staging = self.data / 'updates'
                staging.mkdir(exist_ok=True)
                directory = Path(tempfile.mkdtemp(prefix='update-', dir=staging))
                if local_archive:
                    shutil.copy2(local_archive,directory/'release.zip')
                    updates.verify_archive(directory/'release.zip',offer)
                else:
                    updates.download(offer, directory)
                shutil.copy2(root / 'app' / 'PokerNowUpdater.exe', directory / 'PokerNowUpdater.exe')
                job = directory / 'job.json'
                job.write_text(json.dumps({'root': str(root), 'pid': os.getpid(), 'release': offer}), encoding='utf-8')
                self.app.events.put(('update', ('downloaded', str(job), False)))
            except Exception as exc:
                self.app.events.put(('update', ('error', str(exc), False)))
        threading.Thread(target=worker, daemon=True).start()
