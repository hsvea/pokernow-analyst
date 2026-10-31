"""Bounded HTTPS downloads and strict validation of the public GitHub channel."""
import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from release_config import ASSET_NAME

MAX_ZIP = 250 * 1024 * 1024
MAX_EXPANDED = 750 * 1024 * 1024


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value):
        raise ValueError('Некорректная версия')
    return tuple(map(int, value.split('.')))


def validate_url(url):
    p = urlsplit(url)
    if (p.scheme != 'https' or p.hostname not in {'api.github.com', 'github.com', 'release-assets.githubusercontent.com'}
            or p.username or p.password or p.port not in (None, 443)):
        raise ValueError('Недопустимый адрес загрузки')


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit, destination=None):
    validate_url(url)
    request = Request(url, headers={'User-Agent': 'PokerNowAnalyst-Updater', 'Accept': 'application/vnd.github+json' if url.startswith('https://api.github.com/') else 'application/octet-stream'})
    chunks, total = [], 0
    output = None
    try:
        with build_opener(SafeRedirect()).open(request, timeout=30) as response:
            if destination:
                output = Path(destination).open('xb')
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ValueError('Превышен допустимый размер загрузки')
                if output:
                    output.write(chunk)
                else:
                    chunks.append(chunk)
        return b''.join(chunks)
    finally:
        if output:
            output.close()


def release_info(data, repository, current):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Канал GitHub ещё не настроен')
    tag = data.get('tag_name', '')
    new = tag.removeprefix('v')
    if data.get('draft') or data.get('prerelease') or version(new) <= version(current):
        return None
    assets = [a for a in data.get('assets', []) if a.get('name') == ASSET_NAME]
    if len(assets) != 1:
        raise ValueError('В релизе отсутствует единственный Windows ZIP')
    asset = assets[0]
    digest = asset.get('digest') or ''
    expected = f'https://github.com/{repository}/releases/download/{tag}/{ASSET_NAME}'
    if asset.get('browser_download_url') != expected or asset.get('state') != 'uploaded':
        raise ValueError('Некорректный файл релиза')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest) or not 0 < asset.get('size', 0) <= MAX_ZIP:
        raise ValueError('Нет SHA-256 или неверный размер релиза')
    return {'version': new, 'url': expected, 'sha256': digest[7:], 'size': asset['size']}


def check(repository, current):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Канал GitHub ещё не настроен')
    data = json.loads(fetch(f'https://api.github.com/repos/{repository}/releases/latest', 1024 * 1024))
    return release_info(data, repository, current)


def verify_archive(archive, info):
    archive = Path(archive)
    if archive.stat().st_size != info['size'] or archive.stat().st_size > MAX_ZIP:
        raise ValueError('Размер ZIP не совпадает с релизом')
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != info['sha256']:
            raise ValueError('SHA-256 ZIP не совпадает с релизом')
    with zipfile.ZipFile(archive) as z:
        names, size = set(), 0
        for entry in z.infolist():
            name = entry.filename
            path = PurePosixPath(name)
            mode = entry.external_attr >> 16
            if (not name or '\\' in name or any(c in name for c in ':<>"|?*') or path.is_absolute()
                    or any(not p or p in {'..', '.'} or p.endswith((' ', '.')) or re.match(r'(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', p) for p in name.rstrip('/').split('/'))
                    or stat.S_ISLNK(mode) or entry.flag_bits & 1):
                raise ValueError('Небезопасная структура ZIP')
            if name.casefold() in names:
                raise ValueError('Повторяющееся имя в ZIP')
            names.add(name.casefold())
            size += entry.file_size
            if size > MAX_EXPANDED or len(names) > 10000:
                raise ValueError('Слишком большой распакованный ZIP')
            if path.parts[0] not in {'app', 'pokernow_overlay_v2', 'bundle.json'}:
                raise ValueError('Неизвестный компонент ZIP')
        required = {'app/pokernowanalyst.exe', 'app/pokernowupdater.exe', 'pokernow_overlay_v2/manifest.json', 'bundle.json'}
        if not required <= names:
            raise ValueError('Неполный Windows-комплект')
        if z.getinfo('bundle.json').file_size > 4096:
            raise ValueError('Слишком большой манифест')
        bundle = json.loads(z.read('bundle.json'))
        if bundle != {'schema': 1, 'version': info['version']}:
            raise ValueError('Версия внутри ZIP не совпадает с релизом')
        if z.getinfo('pokernow_overlay_v2/manifest.json').file_size > 65536:
            raise ValueError('Слишком большой манифест расширения')
        if json.loads(z.read('pokernow_overlay_v2/manifest.json')).get('version') != info['version']:
            raise ValueError('Версия расширения не совпадает с приложением')
        if z.testzip():
            raise ValueError('Повреждён ZIP')


def download(info, directory):
    archive = Path(directory) / 'release.zip'
    fetch(info['url'], info['size'], archive)
    verify_archive(archive, info)
    return archive
