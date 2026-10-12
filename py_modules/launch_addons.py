"""A narrow receipt for PRAGMATA's independently installed combined launcher."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat

from library import safe_root
from manager import Manager, atomic_json

APPID = '3357650'
WRAPPER = '/usr/libexec/armada/armada-game-launch'
PYTHON = '/usr/bin/python3'
HELPER_NAME = 'pragmata-combined-launch.py'
HELPER_DIRECTORY = 'Combined-Helix-LSFG-20261012'
HELPER_SHA256 = 'f08628ec276495e8402f69651a1314bc1ab50b57dc36c280d5f2f3fa32d0c205'
RECORD_NAME = 'launch-addon.json'
MAX_HELPER_BYTES = 1 << 20
MAX_RECORD_BYTES = 4096
ASSIGNMENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')


def eligible(game):
    return game.get('source') == 'Steam' and str(game.get('appid')) == APPID


def helper_path(game):
    root = safe_root(game['folder'])
    return root.parent / (root.name + ' Mod Files') / HELPER_DIRECTORY / HELPER_NAME


def record_path(companion):
    return Path(companion) / 'records' / RECORD_NAME


def _tokens(value):
    if not isinstance(value, str) or len(value) > 16384 or re.search(r'[\x00-\x1f\x7f$`\\]', value):
        raise ValueError('Combined launch options need literal review')
    try:
        tokens = shlex.split(value, posix=True)
    except ValueError as exc:
        raise ValueError('Combined launch options have invalid quoting') from exc
    if any(re.search(r'[;&|<>()*?\[\]{}#!~]', token) for token in tokens):
        raise ValueError('Combined launch options contain shell syntax')
    return tokens


def recognized(game, actual_owned_after):
    """Recognize intent only; do not read or execute the helper on disable."""
    if not eligible(game):
        return None
    tokens = _tokens(actual_owned_after)
    if "'ENABLE_GAMESCOPE_WSI=" in actual_owned_after or '"ENABLE_GAMESCOPE_WSI=' in actual_owned_after:
        raise ValueError('Combined launcher WSI assignment must be a leading literal assignment')
    leading = []
    for token in tokens:
        if not ASSIGNMENT.match(token):
            break
        leading.append(token)
    expected = str(helper_path(game))
    literal_root = Path(game['folder'])
    literal = str(literal_root.parent / (literal_root.name + ' Mod Files') /
                  HELPER_DIRECTORY / HELPER_NAME)
    allowed_helpers = {expected, literal}
    wsi = [(i, token) for i, token in enumerate(tokens) if token.startswith('ENABLE_GAMESCOPE_WSI=')]
    if wsi and (len(wsi) != 1 or wsi[0][1] != 'ENABLE_GAMESCOPE_WSI=0'
                or wsi[0][0] >= len(leading)):
        raise ValueError('Combined launcher requires one leading ENABLE_GAMESCOPE_WSI=0')
    wrappers = [i for i, token in enumerate(tokens) if token == WRAPPER]
    if len(wrappers) > 1:
        raise ValueError('Duplicate Armada wrappers need manual review')
    occurrences = [i for i, token in enumerate(tokens) if token == PYTHON]
    if not occurrences:
        if any(token in allowed_helpers for token in tokens):
            raise ValueError('Combined launcher helper lacks the pinned Python interpreter')
        return None
    if (len(occurrences) != 1 or occurrences[0] + 2 >= len(tokens)
            or tokens[occurrences[0] + 1] not in allowed_helpers
            or tokens[occurrences[0] + 2] != WRAPPER or len(wrappers) != 1):
        raise ValueError('Unrecognized Python launcher; review it manually')
    if not wsi:
        raise ValueError('Combined launcher requires one leading ENABLE_GAMESCOPE_WSI=0')
    if tokens.count('%command%') != 1:
        raise ValueError('Combined launcher requires one Steam command')
    return {'schema': 1, 'game_folder': str(safe_root(game['folder'])),
            'helper': expected, 'sha256': HELPER_SHA256, 'wsi': '0'}


def _validate_record(game, record):
    if (not isinstance(record, dict)
            or set(record) != {'schema', 'game_folder', 'helper', 'sha256', 'wsi'}
            or type(record['schema']) is not int or record['schema'] != 1
            or record['game_folder'] != str(safe_root(game['folder']))
            or record['helper'] != str(helper_path(game))
            or record['sha256'] != HELPER_SHA256 or record['wsi'] != '0'):
        raise ValueError('Combined launcher receipt changed; review it manually')
    return record


def read_record(companion, game):
    if not eligible(game):
        return None
    path = record_path(companion)
    if Manager._symlink_in_path(path):
        raise ValueError('Combined launcher receipt path is a symlink')
    if not path.exists():
        return None
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_RECORD_BYTES:
            raise ValueError('Unsafe combined launcher receipt')
        raw = stream.read(MAX_RECORD_BYTES + 1)
    if len(raw) > MAX_RECORD_BYTES:
        raise ValueError('Combined launcher receipt too large')
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate combined launcher receipt key')
                result[key] = value
            return result
        record = json.loads(raw, object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid combined launcher receipt') from exc
    return _validate_record(game, record)


def verified_addon(companion, game):
    record = read_record(companion, game)
    if record is None:
        return None
    path = Path(record['helper'])
    if Manager._symlink_in_path(path):
        raise ValueError('Combined launcher helper path is a symlink')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    try:
        with os.fdopen(os.open(path, flags), 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or not 0 < info.st_size <= MAX_HELPER_BYTES):
                raise ValueError('Unsafe combined launcher helper')
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1 << 16), b''):
                digest.update(chunk)
    except FileNotFoundError as exc:
        raise ValueError('Combined launcher helper is missing') from exc
    if digest.hexdigest() != HELPER_SHA256:
        raise ValueError('Combined launcher helper changed')
    return {'helper': str(path), 'sha256': HELPER_SHA256,
            'environment': {'ENABLE_GAMESCOPE_WSI': '0'}}


def write_record(companion, game, record):
    path = record_path(companion)
    if Manager._symlink_in_path(path.parent) or path.is_symlink():
        raise ValueError('Combined launcher receipt path is a symlink')
    if record is None:
        if path.exists():
            flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
            with os.fdopen(os.open(path, flags), 'rb') as stream:
                info = os.fstat(stream.fileno())
                live = path.lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or info.st_size > MAX_RECORD_BYTES
                        or (info.st_dev, info.st_ino) != (live.st_dev, live.st_ino)):
                    raise ValueError('Unsafe combined launcher receipt')
            path.unlink()
        return
    _validate_record(game, record)
    atomic_json(path, record)
