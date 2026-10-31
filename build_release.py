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
    for script, name, windowed in [('app.py', 'PokerNowAnalyst', True), ('updater.py', 'PokerNowUpdater', True), ('installer.py','PokerNowSetup',True)]:
        extras = (['--collect-all','openai_codex','--collect-all','codex_cli_bin',
                   '--copy-metadata','openai-codex','--copy-metadata','openai-codex-cli-bin'] if script=='app.py' else [])
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
                        '--windowed' if windowed else '--console', '--name', name, *extras, script], cwd=root, check=True)
    # No account access or inference: ensure the frozen SDK can locate its CLI.
    check_file=root/'build/sdk-selftest.json'
    check_file.unlink(missing_ok=True)
    subprocess.run([str(root/'dist/PokerNowAnalyst.exe'),'--self-test',str(check_file)],check=True,timeout=120)
    if json.loads(check_file.read_text(encoding='utf-8'))['version'] != VERSION:
        raise RuntimeError('Frozen app self-test version mismatch')
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
    shutil.copy2(root / 'dist/PokerNowSetup.exe', output / 'PokerNowSetup.exe')
    print(archive)


if __name__ == '__main__':
    main()
