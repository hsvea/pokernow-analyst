"""Separate Windows helper; runs from a staging directory outside the install."""
import ctypes
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from updates import verify_archive


class AppLock:
    def __init__(self, data):
        self.path = Path(data) / 'application.lock'
        self.stream = None

    def acquire(self, timeout=0):
        import msvcrt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open('a+b')
        self.stream.write(b'0')
        self.stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self.stream.close()
                    self.stream = None
                    raise RuntimeError('Приложение ещё открыто. Закрой все его окна и повтори обновление.')
                time.sleep(0.25)

    def close(self):
        if self.stream:
            self.stream.close()
            self.stream = None


def move_retry(source, target, timeout=15):
    deadline = time.monotonic() + timeout
    while True:
        try:
            Path(source).rename(target)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def backup_data(data, target):
    target.mkdir()
    db = data / 'history.sqlite3'
    if db.exists():
        source = sqlite3.connect(str(db))
        dest = sqlite3.connect(str(target / db.name))
        try:
            source.backup(dest)
        finally:
            dest.close()
            source.close()
    config = data / 'config.json'
    if config.exists():
        shutil.copy2(config, target / config.name)


def replace_components(root, stage, backup):
    """Journal each move so partial replacement can also be rolled back."""
    moved, installed = [], []
    try:
        for name in ('app', 'pokernow_overlay_v2', 'bundle.json'):
            if (root / name).exists():
                move_retry(root / name, backup / name)
                moved.append(name)
            move_retry(stage / name, root / name)
            installed.append(name)
    except Exception:
        restore_components(root, backup, moved, installed)
        raise
    return moved, installed


def restore_components(root, backup, moved, installed):
    # Preserve failed new files for diagnosis instead of deleting user files.
    failed = backup / 'failed-new'
    failed.mkdir(exist_ok=True)
    for name in reversed(installed):
        move_retry(root / name, failed / name)
    for name in reversed(moved):
        move_retry(backup / name, root / name)


def run(job_path):
    job_path = Path(job_path).resolve()
    job = json.loads(job_path.read_text(encoding='utf-8'))
    root = Path(job['root']).resolve()
    expected = (Path(os.environ['LOCALAPPDATA']) / 'PokerNowAnalystApp').resolve()
    if root != expected or root.is_symlink():
        raise ValueError('Обновление разрешено только в стабильной папке установки')
    data = Path(os.environ['APPDATA']) / 'PokerNowAnalyst'
    archive = job_path.parent / 'release.zip'
    verify_archive(archive, job['release'])
    stage = job_path.parent / 'staged'
    stage.mkdir()
    with zipfile.ZipFile(archive) as z:
        z.extractall(stage)
    # Wait for the exact parent process; never terminate the user's old app.
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, job['pid'])
    if handle:
        try:
            if kernel.WaitForSingleObject(handle, 60000) != 0:
                raise RuntimeError('Приложение не завершилось за 60 секунд')
        finally:
            kernel.CloseHandle(handle)
    lock = AppLock(data).acquire(20)
    try:
        for name in ('app', 'pokernow_overlay_v2', 'bundle.json'):
            if (root / name).is_symlink() or (hasattr(root / name, 'is_junction') and (root / name).is_junction()):
                raise ValueError('Ссылки в папке установки не поддерживаются')
        backup = root / 'backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + job_path.parent.name)
        backup.mkdir(parents=True)
        backup_data(data, backup / 'userdata')
        moved, installed = replace_components(root, stage, backup)
    finally:
        lock.close()
    ready = job_path.parent / 'ready'
    env = os.environ.copy()
    env['POKERNOW_UPDATE_READY'] = str(ready)
    child = None
    try:
        child = subprocess.Popen([str(root / 'app' / 'PokerNowAnalyst.exe')], cwd=root, env=env)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if ready.exists():
                (job_path.parent / 'result.txt').write_text('OK', encoding='utf-8')
                ctypes.windll.user32.MessageBoxW(0, 'Приложение обновлено. В opera://extensions нажми Reload у PokerNow Overlay, затем обнови вкладку стола.', 'PokerNow Analyst', 0)
                return
            if child.poll() is not None:
                break
            time.sleep(0.25)
        raise RuntimeError('Новая версия не подтвердила запуск')
    except Exception:
        if child and child.poll() is None:
            child.terminate()
            child.wait(timeout=15)
        lock = AppLock(data).acquire(20)
        try:
            restore_components(root, backup, moved, installed)
        finally:
            lock.close()
        subprocess.Popen([str(root / 'app' / 'PokerNowAnalyst.exe')], cwd=root)
        raise


if __name__ == '__main__':
    try:
        run(sys.argv[1])
    except Exception as exc:
        if len(sys.argv) > 1:
            Path(sys.argv[1]).with_name('error.txt').write_text(str(exc), encoding='utf-8')
        ctypes.windll.user32.MessageBoxW(0, 'Обновление не завершено: ' + str(exc), 'PokerNow Analyst', 0x10)
        sys.exit(1)
