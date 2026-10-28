"""Hash-pinned direct FSR management for the PRAGMATA HelixSR 2.0 build."""
import hashlib
import re
from pathlib import Path

PROVIDER = '33647875141293ebae0df8b79a18902a953b4f2b18fe5fe6980d73e1c4879ec7'
STOCK = '3eab9a448db1ca09d5aba17d11df5b789649c11d60f1281f4be97bd007ac7d6d'
DLL = 'amd_fidelityfx_upscaler_dx12.dll'
ORIGINAL = 'amd_fidelityfx_upscaler_dx12.original.dll'
DEFAULT_INI = (b'[Upscaling]\nInt8=on\nNetworkResolution=fast\n'
               b'[Compatibility]\nWaveSize=auto\n[Log]\nEnabled=true\n'
               b'[ModelE]\nUseReactiveMask=false\n')
RULES = {'int8': ('Upscaling', 'Int8', {'auto', 'on', 'off'}),
         'networkresolution': ('Upscaling', 'NetworkResolution', {'fast', 'full'}),
         'wavesize': ('Compatibility', 'WaveSize', {'auto', '32', '64'}),
         'usereactivemask': ('ModelE', 'UseReactiveMask', {'true', 'false'})}


def edit_ini(raw, options):
    """Return edited UTF-8 bytes, preserving unrelated lines and comments."""
    if not isinstance(options, dict) or not options:
        raise ValueError('Select at least one setting')
    normalized = {}
    for key, value in options.items():
        name = str(key).lower()
        if name not in RULES or name in normalized or not isinstance(value, (str, bool)):
            raise ValueError('Unsupported or duplicate setting')
        val = str(value).lower()
        if val not in RULES[name][2]:
            raise ValueError('Invalid value for ' + str(key))
        normalized[name] = val
    text = raw.decode('utf-8-sig')
    bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    lines = text.splitlines(keepends=True)
    newline = '\r\n' if '\r\n' in text else '\n'
    sections, found = {}, {}
    current = None
    section_re = re.compile(r'^\s*\[([^\]]+)\]\s*(?:[;#].*)?(?:\r?\n)?$')
    key_re = re.compile(r'^(\s*)([^=;#\s]+)(\s*=\s*)(.*?)(\r?\n)?$')
    relevant_sections = {x[0].lower() for x in RULES.values()}
    for i, line in enumerate(lines):
        section = section_re.match(line)
        if section:
            current = section.group(1).strip().lower()
            if current in relevant_sections:
                if current in sections:
                    raise ValueError('Duplicate relevant INI section')
                sections[current] = i
            continue
        key = key_re.match(line)
        if key:
            name = key.group(2).lower()
            if name in RULES and current == RULES[name][0].lower():
                if name in found:
                    raise ValueError('Duplicate relevant INI key')
                found[name] = i
    for name, value in normalized.items():
        if name in found:
            i = found[name]
            match = key_re.match(lines[i])
            old = match.group(4)
            comment = re.search(r'(\s+[;#].*)$', old)
            lines[i] = match.group(1) + match.group(2) + match.group(3) + value + (comment.group(1) if comment else '') + (match.group(5) or '')
    for name, value in normalized.items():
        if name in found:
            continue
        section, key, _ = RULES[name]
        section_lower = section.lower()
        # Re-scan after insertion so indexes stay correct.
        indices = [i for i, line in enumerate(lines) if (m := section_re.match(line)) and m.group(1).strip().lower() == section_lower]
        if indices:
            start = indices[0] + 1
            end = next((i for i in range(start, len(lines)) if section_re.match(lines[i])), len(lines))
            if end and not lines[end - 1].endswith(('\n', '\r')):
                lines[end - 1] += newline
            lines.insert(end, key + '=' + value + newline)
        else:
            if lines and not lines[-1].endswith(('\n', '\r')):
                lines[-1] += newline
            lines.extend(['[' + section + ']' + newline, key + '=' + value + newline])
    return bom + ''.join(lines).encode('utf-8')


class Helix2Manager:
    """Manage the known PRAGMATA direct installation with separate records."""
    def __init__(self, manager):
        self.manager = manager
        self._hash_cache = {}

    def _hash(self, path, fresh=False):
        path = Path(path)
        if self.manager._symlink_in_path(path) or not path.is_file():
            raise ValueError('Missing or unsafe file: ' + str(path))
        st = path.stat()
        if st.st_nlink != 1:
            raise ValueError('Hard-linked file: ' + str(path))
        key = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
        if not fresh and key in self._hash_cache:
            return self._hash_cache[key]
        h = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
        after = path.stat()
        if key != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('File changed while hashing')
        self._hash_cache[key] = h.hexdigest()
        if len(self._hash_cache) > 128:
            self._hash_cache.pop(next(iter(self._hash_cache)))
        return h.hexdigest()

    @staticmethod
    def _write_chunk(stream, chunk):
        if stream.write(chunk) != len(chunk):
            raise OSError('Short write while staging replacement')

    def _atomic_replace(self, target, *, source=None, content=None, expected=None):
        import os, stat, tempfile
        from manager import sync_directory
        target = Path(target)
        if (source is None) == (content is None):
            raise ValueError('Exactly one replacement source is required')
        if self.manager._symlink_in_path(target) or (target.exists() and (not target.is_file() or target.stat().st_nlink != 1)):
            raise ValueError('Unsafe replacement target')
        mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
        if source is not None:
            source = Path(source)
            digest = self._hash(source, fresh=True)
            if expected is not None and digest != expected:
                raise ValueError('Replacement source changed')
            expected = digest
            if mode is None:
                mode = stat.S_IMODE(source.stat().st_mode)
        else:
            expected = hashlib.sha256(content).hexdigest()
        fd, temp_name = tempfile.mkstemp(prefix='.helix2-', suffix='.tmp', dir=str(target.parent))
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, 'wb') as out:
                if source is None:
                    self._write_chunk(out, content)
                else:
                    with source.open('rb') as inp:
                        for chunk in iter(lambda: inp.read(1024 * 1024), b''):
                            self._write_chunk(out, chunk)
                out.flush()
                if mode is not None:
                    os.chmod(temp, mode)
                os.fsync(out.fileno())
            if self._hash(temp, fresh=True) != expected:
                raise ValueError('Staged replacement hash mismatch')
            os.replace(temp, target)
            sync_directory(target.parent)
        finally:
            temp.unlink(missing_ok=True)

    def _pending_status(self, gid):
        import json
        from manager import active_processes
        game, root, target = self._game(gid)
        c = self._companion(root)
        tx, journal = c / 'transaction', c / 'transaction' / 'journal.json'
        if not tx.exists():
            return None
        if self.manager._symlink_in_path(tx) or self.manager._symlink_in_path(journal) or not journal.is_file() or journal.stat().st_nlink != 1:
            raise ValueError('Transaction journal is missing or unsafe; manual review required')
        data = json.loads(journal.read_text(encoding='utf-8'))
        ordered_paths = [str(p) for p in (target, target.with_name(ORIGINAL), target.parent / 'helixsr.ini', c / 'install.json')]
        paths = set(ordered_paths)
        if (data.get('state') not in ('prepared', 'committed') or
                not isinstance(data.get('before'), dict) or set(data['before']) != paths or
                not isinstance(data.get('allowed'), dict) or set(data['allowed']) != paths or
                (data['state'] == 'committed' and (not isinstance(data.get('after'), dict) or set(data['after']) != paths))):
            raise ValueError('Transaction journal is invalid; manual review required')
        def valid_digest(value):
            return value is None or isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None
        for i, path in enumerate(ordered_paths):
            entry, choices = data['before'][path], data['allowed'][path]
            if (not isinstance(entry, dict) or entry.get('snapshot') != str(i) or
                    not valid_digest(entry.get('sha256')) or not isinstance(choices, list) or
                    entry.get('sha256') not in choices or not all(valid_digest(x) for x in choices) or
                    (data['state'] == 'committed' and not valid_digest(data['after'][path]))):
                raise ValueError('Transaction journal is invalid; manual review required')
        running = bool(active_processes(root, game.get('appid', '')))
        return {'backend': 'helixsr-2.0-direct', 'state': 'blocked', 'available': False,
                'running': running, 'can_modify': not running, 'actions': [] if running else ['recover'],
                'managed': False, 'options': {}, 'mutation_available': not running,
                'reason': 'Interrupted transaction requires recovery'}

    def _game(self, gid):
        game = self.manager.get_game(gid)
        if str(game.get('appid', '')) != '3357650':
            raise ValueError('Only PRAGMATA is supported')
        root = Path(game['folder'])
        if self.manager._symlink_in_path(root) or not root.is_dir():
            raise ValueError('Unsafe game directory')
        target = root / DLL
        if not target.is_file():
            raise ValueError('Expected the direct FSR target in the game root')
        if self.manager._symlink_in_path(target.parent):
            raise ValueError('Unsafe target directory')
        return game, root, target

    def _companion(self, root):
        path = root.parent / (root.name + ' Mod Files') / 'HelixSR-Decky-Adreno-2'
        if self.manager._symlink_in_path(path):
            raise ValueError('Unsafe companion path')
        return path

    def _source_file(self, fresh=True):
        import json
        cfg = Path(self.manager.settings) / 'helix2-source.json'
        if self.manager._symlink_in_path(cfg) or not cfg.is_file() or cfg.stat().st_nlink != 1:
            raise ValueError('Register the local 2.0 source first')
        source = Path(json.loads(cfg.read_text(encoding='utf-8'))['source']) / DLL
        if self._hash(source, fresh=fresh) != PROVIDER:
            raise ValueError('Registered provider changed')
        return source

    def _source_ini(self, fresh=True):
        import json
        cfg = Path(self.manager.settings) / 'helix2-source.json'
        root = self._source_file(fresh=fresh).parent
        saved = json.loads(cfg.read_text(encoding='utf-8'))
        source = Path(saved.get('ini_source', str(root / 'helixsr.ini')))
        permitted = (root / 'helixsr.ini', Path(self.manager.settings) / 'helix2-default.ini')
        if source not in permitted or self.manager._symlink_in_path(source) or not source.is_file() or source.stat().st_nlink != 1:
            raise ValueError('Registered source INI path is unsafe')
        if source.stat().st_size > 1024 * 1024 or self._hash(source, fresh=fresh) != saved.get('ini_sha256'):
            raise ValueError('Registered source INI changed')
        edit_ini(source.read_bytes(), {'Int8': 'auto'})
        return source

    def register_source(self, path):
        from manager import atomic_json
        root = Path(path)
        if not root.is_absolute() or self.manager._symlink_in_path(root) or not root.is_dir():
            raise ValueError('Source must be a real absolute directory')
        if self._hash(root / DLL, fresh=True) != PROVIDER:
            raise ValueError('Provider hash does not match the pinned 2.0 build')
        ini = root / 'helixsr.ini'
        if self.manager._symlink_in_path(ini):
            raise ValueError('Source INI is unsafe')
        if not ini.exists():
            ini = Path(self.manager.settings) / 'helix2-default.ini'
            if self.manager._symlink_in_path(ini):
                raise ValueError('Default INI is unsafe')
            if not ini.exists():
                self._atomic_replace(ini, content=DEFAULT_INI)
            elif not ini.is_file() or ini.stat().st_nlink != 1 or ini.read_bytes() != DEFAULT_INI:
                raise ValueError('Existing default INI differs; inspect it before registration')
        if not ini.is_file() or ini.stat().st_nlink != 1 or ini.stat().st_size > 1024 * 1024:
            raise ValueError('Source INI is unsafe')
        edit_ini(ini.read_bytes(), {'Int8': 'auto'})
        ini_hash = self._hash(ini, fresh=True)
        cfg = Path(self.manager.settings) / 'helix2-source.json'
        if self.manager._symlink_in_path(cfg) or (cfg.exists() and cfg.stat().st_nlink != 1):
            raise ValueError('Unsafe source registration file')
        atomic_json(cfg, {'source': str(root), 'ini_source': str(ini), 'ini_sha256': ini_hash})
        return self.source_status()

    def source_status(self):
        try:
            source = self._source_file(fresh=False)
            self._source_ini(fresh=False)
            return {'ready': True, 'source': str(source.parent)}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {'ready': False, 'reason': str(exc)}

    def _state(self, gid, fresh=True):
        import json
        game, root, target = self._game(gid)
        c = self._companion(root)
        rec = c / 'install.json'
        if (c / 'transaction').exists():
            raise ValueError('Incomplete transaction requires manual recovery')
        if self.manager._symlink_in_path(rec) or (rec.exists() and rec.stat().st_nlink != 1):
            raise ValueError('Unsafe receipt')
        receipt = json.loads(rec.read_text(encoding='utf-8')) if rec.exists() else None
        original, ini = target.with_name(ORIGINAL), target.parent / 'helixsr.ini'
        for path in (target, original, ini):
            if self.manager._symlink_in_path(path):
                raise ValueError('Unsafe file path')
            if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
                raise ValueError('Unsafe or hard-linked file')
        if any((target.parent / n).exists() for n in ('helixsr_weights.bin', 'helixsr_kernels.pak')):
            raise ValueError('Legacy network files are present')
        current = self._hash(target, fresh=fresh)
        original_hash = self._hash(original, fresh=fresh) if original.exists() else None
        if current not in (STOCK, PROVIDER) or original_hash not in (None, STOCK):
            raise ValueError('Unknown provider or original identity')
        if current == PROVIDER and original_hash != STOCK:
            raise ValueError('Recognized stock original is required')
        if receipt and original_hash != STOCK:
            raise ValueError('Managed installation requires the recognized original')
        if receipt and (receipt.get('target') != str(target) or receipt.get('version') != 1):
            raise ValueError('Unexpected receipt')
        return game, root, target, original, ini, c, rec, receipt, current, original_hash

    def status(self, gid):
        from manager import active_processes
        import configparser
        try:
            pending = self._pending_status(gid)
            if pending is not None:
                return pending
            game, root, target, _, ini, _, _, receipt, current, original = self._state(gid, fresh=False)
            running = bool(active_processes(root, game.get('appid', '')))
            options = {}
            if ini.exists():
                if ini.stat().st_size > 1024 * 1024:
                    raise ValueError('INI is too large')
                raw = ini.read_bytes()
                # Check all relevant sections and keys for duplicates.
                edit_ini(raw, {'Int8': 'auto'})
                parser = configparser.ConfigParser(interpolation=None, strict=True, inline_comment_prefixes=(';', '#'))
                parser.read_string(raw.decode('utf-8-sig'))
                for _, (section, name, _) in RULES.items():
                    options[name] = parser.get(section, name, fallback=None)
            enabled = current == PROVIDER
            actions = ([] if running else
                       (['disable', 'remove', 'settings'] if receipt and enabled else
                        ['enable', 'remove'] if receipt else
                        ['adopt'] if enabled else ['install']))
            return {'backend': 'helixsr-2.0-direct', 'state': 'helix2' if enabled else 'stock',
                    'available': enabled, 'managed': bool(receipt), 'enabled': enabled,
                    'running': running, 'can_modify': not running, 'actions': actions, 'options': options,
                    'target': str(target), 'provider_sha256': current,
                    'original_sha256': original, 'ini_exists': ini.exists(), 'mutation_available': True}
        except (OSError, ValueError, KeyError, TypeError, configparser.Error, UnicodeError) as exc:
            return {'backend': 'helixsr-2.0-direct', 'state': 'blocked', 'available': False,
                    'managed': False, 'running': False, 'can_modify': False, 'actions': [], 'options': {},
                    'mutation_available': False, 'reason': str(exc)}

    def _plan(self, gid, action, options):
        from manager import active_processes
        state = self._state(gid)
        game, root, target, original, ini, c, rec, receipt, current, original_hash = state
        if active_processes(root, game.get('appid', '')):
            raise ValueError('Close the game first')
        if action not in ('adopt', 'install', 'enable', 'disable', 'remove', 'settings'):
            raise ValueError('Unknown action')
        if action == 'adopt' and (receipt or current != PROVIDER):
            raise ValueError('Adoption requires an unmanaged recognized installation')
        if action == 'install' and (receipt or current != STOCK):
            raise ValueError('Installation requires unmodified stock and no original backup')
        if action in ('enable', 'disable', 'remove', 'settings') and not receipt:
            raise ValueError('Adopt or install first')
        if action == 'enable' and current != STOCK:
            raise ValueError('Already enabled')
        if action in ('disable', 'settings') and current != PROVIDER:
            raise ValueError('HelixSR is not enabled')
        if action in ('install', 'enable'):
            self._source_file()
        if action == 'install' and not ini.exists():
            self._source_ini()
        if action == 'settings':
            if not ini.is_file():
                raise ValueError('helixsr.ini is missing')
            edit_ini(ini.read_bytes(), options)
        if action != 'settings' and options:
            raise ValueError('Options are only accepted for settings')
        paths = (target, original, ini, rec)
        hashes = {str(p): self._hash(p, fresh=True) if p.exists() else None for p in paths}
        return state, hashes

    def preview(self, gid, action, options=None):
        import uuid, time
        state, hashes = self._plan(gid, action, options)
        if not hasattr(self, '_previews'):
            self._previews = {}
        token = uuid.uuid4().hex
        self._previews[token] = (gid, action, options, hashes, time.time() + 120)
        details = {
            'adopt': ['Record ownership of the recognized installation; keep its current provider and settings'],
            'install': ['Install the verified local 2.0 provider and retain original FSR for switching back'],
            'enable': ['Switch from original FSR to the verified local HelixSR 2.0 provider'],
            'disable': ['Switch to the verified original FSR provider; retain HelixSR settings'],
            'remove': ['Restore original FSR and remove the management record; retain the INI and original provider'],
            'settings': [key + ' = ' + str(value) for key, value in (options or {}).items()],
        }
        return {'token': token, 'action': action, 'game': state[0].get('name'),
                'target': str(state[2]), 'files': list(hashes), 'changes': details[action],
                'summary': action.capitalize() + ' HelixSR 2.0', 'expires_in': 120}

    def execute(self, token):
        import time, json, os, shutil
        from operation_lock import operation_lock
        from manager import atomic_json, durable_copy
        if not hasattr(self, '_previews') or token not in self._previews:
            raise ValueError('Preview expired or unknown')
        gid, action, options, expected, expires = self._previews.pop(token)
        if time.time() > expires:
            raise ValueError('Preview expired')
        game, root, _ = self._game(gid)
        with operation_lock(self.manager.companion(game)):
            state, hashes = self._plan(gid, action, options)
            if hashes != expected:
                raise ValueError('Files changed since preview')
            game, root, target, original, ini, c, rec, receipt, current, _ = state
            c.mkdir(parents=True, exist_ok=True)
            tx = c / 'transaction'
            tx.mkdir()
            try:
                before = {}
                for i, path in enumerate((target, original, ini, rec)):
                    digest = hashes[str(path)]
                    if digest is not None:
                        durable_copy(path, tx / str(i))
                        if self._hash(tx / str(i), fresh=True) != digest:
                            raise ValueError('Snapshot mismatch')
                    before[str(path)] = {'sha256': digest, 'snapshot': str(i)}
                next_receipt = {'version': 1, 'target': str(target), 'adopted': action == 'adopt' or bool(receipt and receipt.get('adopted'))}
                receipt_bytes = (json.dumps(next_receipt, indent=2) + '\n').encode('utf-8')
                allowed = {path: [entry['sha256']] for path, entry in before.items()}
                allowed[str(target)].extend([STOCK, PROVIDER])
                allowed[str(original)].append(STOCK)
                if action == 'settings':
                    allowed[str(ini)].append(hashlib.sha256(edit_ini(ini.read_bytes(), options)).hexdigest())
                if action == 'install' and not ini.exists():
                    allowed[str(ini)].append(self._hash(self._source_ini(), fresh=True))
                allowed[str(rec)].append(None if action == 'remove' else hashlib.sha256(receipt_bytes).hexdigest())
                atomic_json(tx / 'journal.json', {'state': 'prepared', 'before': before, 'allowed': allowed, 'action': action})
                if action == 'install':
                    if not original.exists():
                        self._atomic_replace(original, source=target, expected=STOCK)
                    self._atomic_replace(target, source=self._source_file(), expected=PROVIDER)
                    if not ini.exists():
                        self._atomic_replace(ini, source=self._source_ini(), expected=allowed[str(ini)][-1])
                elif action == 'enable':
                    self._atomic_replace(target, source=self._source_file(), expected=PROVIDER)
                elif action in ('disable', 'remove') and current == PROVIDER:
                    self._atomic_replace(target, source=original, expected=STOCK)
                elif action == 'settings':
                    self._atomic_replace(ini, content=edit_ini(ini.read_bytes(), options))
                if action == 'remove':
                    rec.unlink(missing_ok=True)
                else:
                    atomic_json(rec, next_receipt)
                expected_dll = PROVIDER if action in ('install', 'enable', 'adopt', 'settings') else STOCK
                if self._hash(target, fresh=True) != expected_dll:
                    raise ValueError('Post-write provider verification failed')
                atomic_json(tx / 'journal.json', {'state': 'committed', 'before': before, 'allowed': allowed, 'after': {str(p): self._hash(p, fresh=True) if p.exists() else None for p in (target, original, ini, rec)}, 'action': action})
                shutil.rmtree(tx)
                return self.status(gid)
            except BaseException:
                # Roll back only when a full prepared journal exists. If rollback
                # cannot complete, retain the journal and fail closed.
                journal = tx / 'journal.json'
                if journal.exists():
                    try:
                        if json.loads(journal.read_text(encoding='utf-8')).get('state') == 'committed':
                            raise ValueError('Committed transaction requires finalization')
                        for path_str, entry in before.items():
                            path = Path(path_str)
                            if self.manager._symlink_in_path(path) or (path.exists() and (not path.is_file() or path.stat().st_nlink != 1)):
                                raise ValueError('Unsafe rollback path')
                            actual = self._hash(path, fresh=True) if path.exists() else None
                            if actual not in allowed[path_str]:
                                raise ValueError('Rollback conflict: ' + path_str)
                            if entry['sha256'] is not None and self._hash(tx / entry['snapshot'], fresh=True) != entry['sha256']:
                                raise ValueError('Snapshot damaged')
                        for path_str, entry in before.items():
                            path = Path(path_str)
                            if entry['sha256'] is None:
                                path.unlink(missing_ok=True)
                                from manager import sync_directory
                                sync_directory(path.parent)
                            else:
                                snapshot = tx / entry['snapshot']
                                if self._hash(snapshot, fresh=True) != entry['sha256']:
                                    raise ValueError('Snapshot damaged')
                                self._atomic_replace(path, source=snapshot, expected=entry['sha256'])
                        shutil.rmtree(tx)
                    except BaseException:
                        pass
                else:
                    shutil.rmtree(tx, ignore_errors=True)
                raise

    def recover(self, gid):
        """Recover a prepared transaction, or finalize a verified commit."""
        import json, shutil
        from manager import active_processes
        from operation_lock import operation_lock
        game, root, target = self._game(gid)
        with operation_lock(self.manager.companion(game)):
            if active_processes(root, game.get('appid', '')):
                raise ValueError('Close the game first')
            c = self._companion(root)
            tx = c / 'transaction'
            journal = tx / 'journal.json'
            if self.manager._symlink_in_path(tx) or self.manager._symlink_in_path(journal) or not journal.is_file() or journal.stat().st_nlink != 1:
                raise ValueError('Transaction journal missing or unsafe; manual review required')
            data = json.loads(journal.read_text(encoding='utf-8'))
            paths = [target, target.with_name(ORIGINAL), target.parent / 'helixsr.ini', c / 'install.json']
            expected_paths = {str(p) for p in paths}
            before, allowed = data.get('before'), data.get('allowed')
            if not isinstance(before, dict) or not isinstance(allowed, dict) or set(before) != expected_paths or set(allowed) != expected_paths:
                raise ValueError('Invalid transaction journal paths')
            committed = data.get('state') == 'committed'
            if data.get('state') not in ('prepared', 'committed'):
                raise ValueError('Unknown transaction state')
            after = data.get('after')
            if committed and (not isinstance(after, dict) or set(after) != expected_paths):
                raise ValueError('Invalid committed transaction')
            for i, path in enumerate(paths):
                entry = before[str(path)]
                if not isinstance(entry, dict) or entry.get('snapshot') != str(i):
                    raise ValueError('Invalid snapshot identity')
                digest = entry.get('sha256')
                choices = allowed[str(path)]
                if not isinstance(choices, list) or digest not in choices:
                    raise ValueError('Invalid transaction allowed hashes')
                if self.manager._symlink_in_path(path) or (path.exists() and (not path.is_file() or path.stat().st_nlink != 1)):
                    raise ValueError('Unsafe recovery path')
                actual = self._hash(path, fresh=True) if path.exists() else None
                if (committed and actual != after[str(path)]) or (not committed and actual not in choices):
                    raise ValueError('Recovery conflict: ' + str(path))
                if not committed and digest is not None:
                    snapshot = tx / str(i)
                    if self._hash(snapshot, fresh=True) != digest:
                        raise ValueError('Transaction snapshot damaged')
            if not committed:
                for path in paths:
                    entry = before[str(path)]
                    if entry['sha256'] is None:
                        path.unlink(missing_ok=True)
                        from manager import sync_directory
                        sync_directory(path.parent)
                    else:
                        self._atomic_replace(path, source=tx / entry['snapshot'], expected=entry['sha256'])
            shutil.rmtree(tx)
            return self.status(gid)
