"""Build a Windows-only binary bundle; source is distributed by GitHub tags."""
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from release_config import VERSION, ASSET_NAME, REPOSITORY
from updates import verify_archive


def main():
    if sys.platform != 'win32':
        raise SystemExit('Build on Windows')
    root = Path(__file__).resolve().parent
    output = root / 'release'
    output.mkdir(exist_ok=True)
    for script, name, windowed in [('app.py', 'PokerNowAnalyst', True), ('updater.py', 'PokerNowUpdater', True)]:
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
                        '--windowed' if windowed else '--console', '--name', name, script], cwd=root, check=True)
    archive = output / ASSET_NAME
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in ('PokerNowAnalyst', 'PokerNowUpdater'):
            z.write(root / 'dist' / (name + '.exe'), 'app/' + name + '.exe')
        for p in (root / 'pokernow_overlay_v2').rglob('*'):
            if p.is_file():
                if p.name == 'manifest.json':
                    manifest = json.loads(p.read_text(encoding='utf-8'))
                    manifest['version'] = VERSION
                    z.writestr('pokernow_overlay_v2/manifest.json', json.dumps(manifest, indent=2))
                else:
                    z.write(p, p.relative_to(root).as_posix())
        z.writestr('bundle.json', json.dumps({'schema': 1, 'version': VERSION}))
    info = {'version': VERSION, 'size': archive.stat().st_size,
            'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
            'url': f'https://github.com/{REPOSITORY}/releases/download/v{VERSION}/{ASSET_NAME}'}
    verify_archive(archive, info)
    (output / 'manifest.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    shutil.copy2(root / 'DELIVERY_RU.md', output)
    print(archive)


if __name__ == '__main__':
    main()
