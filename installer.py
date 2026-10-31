"""First-install helper; downloads the verified public release without credentials."""
import os
from pathlib import Path
import queue
import tempfile
import threading
import zipfile
import tkinter as tk
from tkinter import messagebox, ttk
import updates
from release_config import REPOSITORY


def install_new(stage, root):
    root.mkdir(parents=True, exist_ok=True)
    components=('app','pokernow_overlay_v2','bundle.json')
    if any((root / name).exists() for name in components):
        raise ValueError('Приложение уже установлено. Используй «Проверить обновления» в приложении.')
    moved=[]
    try:
        for name in components:
            (stage/name).rename(root/name)
            moved.append(name)
    except Exception:
        for name in reversed(moved):
            (root/name).rename(stage/name)
        raise


def main():
    window=tk.Tk()
    window.title('Установка PokerNow Analyst')
    window.geometry('570x220')
    root=Path(os.environ['LOCALAPPDATA'])/'PokerNowAnalystApp'
    status=tk.StringVar(value='Установка из официального GitHub-релиза.\n'+str(root)+'\nБаза и настройки в APPDATA сохраняются.')
    ttk.Label(window,textvariable=status,wraplength=530,padding=16).pack(fill='x')
    events=queue.Queue()
    def install():
        button.configure(state='disabled')
        status.set('Загрузка и проверка SHA-256…')
        def work():
            try:
                info=updates.check(REPOSITORY,'0.0.0')
                with tempfile.TemporaryDirectory(prefix='PokerNowInstall-',dir=root.parent) as directory:
                    directory=Path(directory)
                    archive=updates.download(info,directory)
                    stage=directory/'stage'
                    stage.mkdir()
                    with zipfile.ZipFile(archive) as z: z.extractall(stage)
                    install_new(stage,root)
                events.put((True,info['version']))
            except Exception as exc: events.put((False,str(exc)))
        threading.Thread(target=work,daemon=True).start()
    button=ttk.Button(window,text='Скачать и установить',command=install)
    button.pack(pady=8)
    def poll():
        try: ok,value=events.get_nowait()
        except queue.Empty: window.after(200,poll);return
        if ok:
            status.set('Версия '+value+' установлена.\nВ Opera загрузи распакованное расширение из:\n'+str(root/'pokernow_overlay_v2'))
            button.configure(text='Открыть папку приложения',state='normal',command=lambda:os.startfile(root/'app'))
        else:
            status.set(value)
            button.configure(state='normal')
            window.after(200,poll)
    window.after(200,poll)
    window.mainloop()


if __name__=='__main__': main()
