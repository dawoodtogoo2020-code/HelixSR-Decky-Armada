"""Private, hash-pinned V762 backend for eligible Armada ARM64 games.

No V762 bytes are included here. A caller registers its own local source.
"""
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import time
import uuid

from manager import (Manager, DLL, NETWORK, AMD_FG, PACKAGE_FILES, atomic_json,
                     checked_path, durable_copy, load_json, pe_info, sha, active_processes)
from model_variants import package_selection
from operation_lock import operation_lock
from library import safe_root
from launch_addons import recognized, verified_addon, write_record

VERSION = '1.8.0'
BACKEND = 'armada-v762-wave64'
OVERRIDES = {
    '1ad412dd861a9c17.spv': 'd19f08f4e640b9a0c96aad642f38c9f9c4692260b8a011a13539bcf00305c60c',
    '22397a04d7ae4cf4.spv': 'dfb461345ef35baab4db991357e42a0598ddd74667e174d3551e1b67074f6584',
    '649a6778b026d390.spv': '9e603999c401a39fd2a467df92eb36331c4dfb3d1a0f626045abfabf161887f1',
    '6883f2d69d8704f2.spv': '9c762a6f464d48e7d6aa1a0429809ba32149030cbac5e7906bd3d5cd12e51baa',
}
PINNED = {
    DLL: '95e31d2ccf60d3016971c6697d677001598b5888e6ec9f0d033ed0d9daab9e18',
    'helixsr_kernels.pak': '3fd81431b1403bbcc338a518f19df18fd567396a1400a727281584f190246589',
    'helixsr_weights.bin': '762adfde720035f7ac43910846e0ce6826c239bcd41f863196f77c547ae57153',
    'helixsr.ini': 'fe04c76c14b6d76dccf10826a8453210a3866c94d07faaff86fe068672bd9bd5',
    **{'shader-override/' + n: h for n, h in OVERRIDES.items()},
}
SOURCE_ALLOWED = set(PINNED) | set(PACKAGE_FILES) | {'amd-fsr/' + AMD_FG}


def _host_eligible(probe=None):
    """Require explicit wave64 evidence; architecture alone is insufficient."""
    facts = probe() if probe else {}
    if not isinstance(facts, dict):
        return False
    native_arch = facts.get('native_arch')
    arm64 = (platform.machine().lower() in ('aarch64', 'arm64')
             or isinstance(native_arch, str) and native_arch.lower() in ('aarch64', 'arm64'))
    return (platform.system() == 'Linux' and arm64 and facts.get('subgroup_min') == 64
            and facts.get('subgroup_max') == 64 and facts.get('vkd3d') is True)


def _strict_file(root, name, expected):
    relative = PurePosixPath(name)
    if (not name or relative.is_absolute() or '..' in relative.parts or '.' in relative.parts
            or relative.as_posix() != name or '\\' in name or ':' in name):
        raise ValueError('Unsafe V762 manifest name')
    p = root.joinpath(*relative.parts)
    if Manager._symlink_in_path(p) or not p.is_file() or p.stat().st_nlink != 1:
        raise ValueError('Missing or unsafe V762 file: ' + name)
    if sha(p) != expected:
        raise ValueError('V762 hash mismatch: ' + name)
    return p


class ArmadaManager(Manager):
    def guard_newer_runtime(self, game):
        root=Path(game['folder'])
        provider=root/'amd_fidelityfx_upscaler_dx12.dll'
        companion=root.with_name(root.name+' Mod Files')/'HelixSR-Decky-Adreno-2'
        if companion.exists() or (provider.is_file() and sha(provider)=='33647875141293ebae0df8b79a18902a953b4f2b18fe5fe6980d73e1c4879ec7'):
            raise ValueError('HelixSR 2.0 uses the Adreno controls. Legacy V762 actions cannot change this installation.')

    def __init__(self, home, settings, host_probe=None):
        self.private_settings = Path(settings)
        self.host_probe = host_probe
        super().__init__(home, self.private_settings / 'armada',
                         host_eligible=lambda: _host_eligible(self.host_probe))
        self.host_reason = 'Armada V762 requires Linux ARM64 and verified 64-lane VKD3D support'
        self.source_config = self.private_settings / 'armada-v762.json'

    def companion(self, game):
        """Keep the private fork's receipts and packages away from upstream."""
        upstream = super().companion(game)
        armada = upstream.with_name('HelixSR-Decky-Armada')
        if armada.is_symlink() or self._symlink_in_path(armada.parent):
            raise ValueError('Armada companion directory cannot be a symlink')
        return armada

    def assess(self, game, detailed=True, executable=None):
        data = super().assess(game, detailed=detailed, executable=executable)
        rec = self.record(game)
        data['backend'] = BACKEND
        # Discovery is evidence, not confirmation from a title or folder name.
        # Keep every record in the backend so an excluded game can still restore.
        data['dx12_detected'] = self._dx12_detected(data)
        if str(game.get('appid', '')) == '292030':
            data['gameplay_warning'] = (
                'Witcher 3 has unresolved flashing textures with V762. '
                'Original FSR was clean in the matched test; Helix gameplay still needs visual testing.')
        if rec.get('backend') == BACKEND:
            data['installed_version'] = rec.get('version')
            data['installed_model'] = 'HelixSR Model E'
            data['installed_variant'] = 'helixsr-model-e'
            data['adopted'] = bool(rec.get('adopted'))
        return data

    @staticmethod
    def _dx12_detected(data):
        if data.get('renderer_unsupported'):
            return False
        main = data.get('main_exe')
        if main:
            info = pe_info(Path(main))
            if info['arch'] == 'x64' and info['dx12']:
                return True
        if any(choice.get('dx12') is True for choice in data.get('executable_choices', [])):
            # Choices have already passed the scanned x64 Windows PE check.
            return True
        if data.get('route') == 'direct':
            targets = data.get('targets', [])
            if targets:
                info = [pe_info(Path(target)) for target in targets if Path(target).is_file()]
                return len(info) == len(targets) and all(
                    item['arch'] == 'x64' and item['ffx'] for item in info)
        return False

    def record_metadata(self, game, data, action):
        return {'backend': BACKEND, 'model': 'helixsr-model-e'}

    def check_update(self, force=False):
        return {'backend': BACKEND, 'upstream_updates_disabled': True, 'version': VERSION}

    def preview_latest(self, *args, **kwargs):
        raise ValueError('Ordinary upstream update cannot replace pinned Armada V762')

    def execute_latest(self, *args, **kwargs):
        raise ValueError('Ordinary upstream update cannot replace pinned Armada V762')

    def start_job(self, *args, **kwargs):
        raise ValueError('Ordinary upstream preparation is disabled for Armada V762')

    def prepare(self, *args, **kwargs):
        raise ValueError('Use prepare_private with registered V762 bytes')

    def source_status(self):
        cfg = load_json(self.source_config)
        try:
            root, files = self._validated_source(cfg)
            return {'ready': True, 'source': str(root), 'files': sorted(files), 'backend': BACKEND}
        except (OSError, ValueError, TypeError) as error:
            return {'ready': False, 'reason': str(error), 'backend': BACKEND}

    def register_source(self, source, files, original=None):
        """Register local private files after checking every byte and extra file."""
        config = {'source': source, 'files': files}
        if original is not None:
            config['original'] = original
        new_root, new_files = self._validated_source(config)
        if original is None:
            prior = load_json(self.source_config)
            try:
                old_root, old_files = self._validated_source(prior)
            except (OSError, ValueError, TypeError):
                pass
            else:
                if old_root.resolve() == new_root.resolve() and old_files == new_files:
                    if isinstance(prior.get('original'), dict):
                        config['original'] = prior['original']
        atomic_json(self.source_config, config)
        return self.source_status()

    def _validated_source(self, cfg):
        if not isinstance(cfg, dict) or not isinstance(cfg.get('source'), str):
            raise ValueError('Register a private local V762 source')
        root = Path(cfg['source'])
        if not root.is_absolute() or self._symlink_in_path(root) or not root.is_dir():
            raise ValueError('Private V762 source must be a real absolute directory')
        files = cfg.get('files')
        if not isinstance(files, dict) or not set(PINNED).issubset(files) or not set(files).issubset(SOURCE_ALLOWED):
            raise ValueError('V762 manifest has missing or unknown files')
        if (set(PACKAGE_FILES) - set(NETWORK) - {DLL}) & set(files):
            if not set(PACKAGE_FILES).issubset(files):
                raise ValueError('OptiScaler source must have every required payload')
        for name, expected in files.items():
            if not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected):
                raise ValueError('Invalid V762 SHA256: ' + name)
            if name in PINNED and expected != PINNED[name]:
                raise ValueError('V762 pinned hash differs: ' + name)
            _strict_file(root, name, expected)
        actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() or p.is_symlink()}
        if actual != set(files):
            raise ValueError('V762 source contains missing, unlisted or symlinked files')
        if pe_info(root / DLL)['arch'] != 'x64' or not pe_info(root / DLL)['ffx']:
            raise ValueError('V762 provider is not an x64 FidelityFX API')
        return root, files

    def package(self, game, route=None, release=None, variant_id=None, selection=None, installed=None):
        rec = load_json(self.companion(game) / 'records/armada-package.json')
        if not rec or rec.get('backend') != BACKEND or rec.get('version') != VERSION:
            return None
        path = Path(rec.get('path', ''))
        if (not path.is_absolute() or path != self.companion(game) / 'packages/v762'
                or self._symlink_in_path(path) or not path.is_dir()):
            return None
        if selection and package_selection(rec) != selection:
            return None
        if installed and installed.get('package_selection') and package_selection(rec) != installed['package_selection']:
            return None
        return (tuple(map(int, VERSION.split('.'))), path, rec) if self._verify_package_payloads((None, path, rec), route) else None

    def _verify_package_payloads(self, package, route=None):
        if package is None:
            return False
        _, root, rec = package
        files = rec.get('files', {})
        required = set(PINNED)
        if route == 'optiscaler':
            required |= set(PACKAGE_FILES)
        if (not isinstance(files, dict) or not required.issubset(files)
                or not set(files).issubset(SOURCE_ALLOWED)
                or any(files.get(name) != expected for name, expected in PINNED.items())):
            return False
        try:
            actual = {p.relative_to(root).as_posix() for p in root.rglob('*')
                      if p.is_file() or p.is_symlink()}
            if actual != set(files):
                return False
            return all(_strict_file(root, n, h) for n, h in files.items()) and pe_info(root / DLL)['ffx']
        except (OSError, ValueError, TypeError):
            return False

    def prepare_private(self, gid, executable=None):
        game = self.get_game(gid)
        data = self.assess(game, executable=executable)
        if data['compatibility'] != 'candidate':
            raise ValueError('; '.join(data['reasons']))
        root, files = self._validated_source(load_json(self.source_config))
        if data['route'] == 'optiscaler' and not set(PACKAGE_FILES).issubset(files):
            raise ValueError('Private source lacks complete OptiScaler payload')
        with operation_lock(self.companion(game)):
            destination = self.companion(game) / 'packages/v762'
            if destination.exists():
                existing = self.package(game, data['route'])
                if existing and existing[2]['files'] == files:
                    return {'ready': True, 'reused': True, 'path': str(destination)}
                raise ValueError('Existing private package differs; review and remove it manually')
            if shutil.disk_usage(game['folder']).free < sum((root / n).stat().st_size for n in files) * 2 + (128 << 20):
                raise ValueError('Insufficient same-drive space for V762 staging')
            try:
                for n, expected in files.items():
                    durable_copy(_strict_file(root, n, expected), destination / n, expected)
                record = {'backend': BACKEND, 'version': VERSION, 'path': str(destination),
                          'files': files, 'prepared_at': time.time(), 'model': 'helixsr-model-e'}
                if not self._verify_package_payloads((None, destination, record), data['route']):
                    raise ValueError('Staged V762 payload failed verification')
                atomic_json(self.companion(game) / 'records/armada-package.json', record)
            except BaseException:
                shutil.rmtree(destination, ignore_errors=True)
                raise
            return {'ready': True, 'reused': False, 'path': str(destination)}

    def planned_paths(self, game, data, action, package=None):
        paths = super().planned_paths(game, data, action, package)
        root = Path(game['folder'])
        if data['route'] == 'direct':
            for target in map(Path, data['targets']):
                rel = str((target.parent / 'helixsr.ini').relative_to(root))
                if rel not in paths:
                    paths.append(rel)
        elif data['route'] == 'optiscaler' and data.get('target'):
            rel = str((Path(data['target']) / 'HelixSR/helixsr.ini').relative_to(root))
            if rel not in paths:
                paths.append(rel)
        return paths

    def install_payload(self, game, data, rec, package):
        if data['route'] == 'optiscaler':
            super().install_payload(game, data, rec, package)
            self.copy_atomic(package[1] / 'helixsr.ini', Path(rec['target']) / 'HelixSR/helixsr.ini',
                             package[2]['files']['helixsr.ini'])
            return
        root = Path(game['folder'])
        source, files = package[1], package[2]['files']
        for target in map(Path, rec['targets']):
            rel = str(target.relative_to(root))
            original = self.companion(game) / 'originals' / rel
            if not original.is_file() or sha(original) != rec['baseline'][rel]:
                raise ValueError('Verified genuine FSR original unavailable')
            self.copy_atomic(original, target.with_name(target.stem + '.original.dll'))
            for name in (DLL, *NETWORK, 'helixsr.ini'):
                destination = target if name == DLL else target.parent / name
                self.copy_atomic(source / name, destination, files[name])
            self.write_managed_json(target.parent / 'helixsr-install.json',
                                    {'owner': 'HelixSR Decky Armada', 'backend': BACKEND,
                                     'model': 'helixsr-model-e', 'version': VERSION})

    def launch_environment(self, game):
        package = self.package(game)
        if not package:
            raise ValueError('Verified private package unavailable')
        path = package[1] / 'shader-override'
        # Proton maps the host root to Z:. Forward slashes are literal in Steam
        # launch options and avoid shell backslash interpretation.
        return {'VKD3D_SHADER_OVERRIDE': 'Z:' + path.as_posix(), 'PROTON_USE_ARM64': '1'}

    def remember_launch_addon(self, gid, actual_owned_after):
        """Remember only PRAGMATA's recognized helper intent, never Steam options."""
        game = self.get_game(gid)
        if not self.record(game).get('enabled'):
            raise ValueError('Enable this managed game before capturing a launch addon')
        with operation_lock(self.companion(game)):
            addon = recognized(game, actual_owned_after)
            write_record(self.companion(game), game, addon)
            return {'remembered': addon is not None}

    def launch_addon(self, game):
        return verified_addon(self.companion(game), game)

    def _verify_launch_addon_preview(self, game, preview):
        if preview.get('action') not in ('install', 'update', 'enable', 'armada-adopt'):
            return
        if 'launch_addon' not in preview or self.launch_addon(game) != preview['launch_addon']:
            raise ValueError('Combined launcher changed since preview; review it again')

    def status(self, gid):
        game = self.get_game(gid)
        data = self.assess_safe(game)
        rec = self.record(game)
        data['backend'] = BACKEND
        data['adopted'] = rec.get('backend') == BACKEND and rec.get('adopted', False)
        data['source_status'] = self.source_status()
        try:
            data['launch_environment'] = self.launch_environment(game)
        except ValueError:
            data['launch_environment'] = None
        return data

    def preview(self, gid, action, dx12_confirmed=False, executable=None):
        self.guard_newer_runtime(self.get_game(gid))
        if action == 'adopt':
            result = self._preview_adopt(gid)
        else:
            result = super().preview(gid, action, dx12_confirmed, executable)
        result['backend'] = BACKEND
        if action in ('install', 'update', 'enable', 'adopt'):
            game = self.get_game(gid)
            try:
                addon = self.launch_addon(game)
            except BaseException:
                self.previews.pop(result['token'], None)
                raise
            self.previews[result['token']]['launch_addon'] = addon
            result['launch_addon'] = addon
        if action in ('install', 'update', 'enable'):
            result['launch_environment'] = self.launch_environment(self.get_game(gid))
        return result

    def _execute_reviewed(self, game, preview):
        self._verify_launch_addon_preview(game, preview)
        result = super()._execute_reviewed(game, preview)
        if preview['action'] == 'remove':
            write_record(self.companion(game), game, None)
        return result

    def execute(self, token, launch_environment_verified=False):
        preview=self.previews.get(token)
        if preview:self.guard_newer_runtime(self.get_game(preview['game']))
        preview = self.previews.get(token)
        if preview and preview.get('action') == 'armada-adopt':
            if launch_environment_verified is not True:
                raise ValueError('Verify and sync the effective V762 launch environment before adoption')
            return self._execute_adopt(token)
        result = super().execute(token)
        result['backend'] = BACKEND
        return result

    def _preview_adopt(self, gid):
        game = self.get_game(gid)
        if self.record(game):
            raise ValueError('Game is already managed')
        data = self.assess(game)
        if data['compatibility'] != 'candidate' or data['route'] != 'direct':
            raise ValueError('; '.join(data['reasons']) or 'Only direct V762 can be adopted')
        package = self.package(game, 'direct')
        if not package:
            raise ValueError('Prepare the exact private V762 package first')
        cfg = load_json(self.source_config)
        _, source_files = self._validated_source(cfg)
        if source_files != package[2]['files']:
            raise ValueError('Private V762 source changed since staging')
        original = self._original_for_game(game, cfg)
        path = Path(original.get('path', '')) if isinstance(original, dict) else Path('')
        digest = original.get('sha256') if isinstance(original, dict) else None
        if (not path.is_absolute() or not isinstance(digest, str)
                or not re.fullmatch('[a-f0-9]{64}', digest)
                or self._symlink_in_path(path) or not path.is_file() or sha(path) != digest
                or pe_info(path)['arch'] != 'x64' or not pe_info(path)['ffx'] or pe_info(path)['helix']):
            raise ValueError('Independently verified genuine FSR original is required for adoption')
        for target in map(Path, data['targets']):
            if sha(target) != PINNED[DLL]:
                raise ValueError('Current provider is not the pinned V762 provider')
            for n in NETWORK + ('helixsr.ini',):
                if sha(target.parent / n) != PINNED[n]:
                    raise ValueError('Current V762 file differs: ' + n)
        token = uuid.uuid4().hex
        self.previews[token] = {'game': gid, 'action': 'armada-adopt', 'expires': time.time()+120,
                                'fingerprint': self.fingerprint(game, data), 'original': original}
        return {'token': token, 'action': 'adopt', 'backend': BACKEND, 'name': game['name'],
                'files': self.planned_paths(game, data, 'observe'), 'launch_environment': self.launch_environment(game),
                'launch_environment_sync_required': True,
                'warning': 'Verify effective V762 launch environment, then adopt current bytes and this game\'s genuine FSR original.'}

    def _original_for_game(self, game, cfg):
        original = cfg.get('original', {})
        if not isinstance(original, dict) or not isinstance(original.get('game_folder'), str):
            raise ValueError('Genuine original must be bound to this game folder')
        bound = Path(original['game_folder'])
        if not bound.is_absolute() or safe_root(bound) != safe_root(game['folder']):
            raise ValueError('Genuine original belongs to a different game folder')
        return original

    def _execute_adopt(self, token):
        preview = self.previews.pop(token, None)
        if not preview or time.time() > preview['expires']:
            raise ValueError('Adoption preview expired')
        game = self.get_game(preview['game'])
        with operation_lock(self.companion(game)):
            self._verify_launch_addon_preview(game, preview)
            data = self.assess(game)
            if (active_processes(game['folder'], game.get('appid', '')) or self.record(game)
                    or data['compatibility'] != 'candidate'):
                raise ValueError('Game state or ownership changed since adoption preview')
            if self.fingerprint(game, data) != preview['fingerprint']:
                raise ValueError('Game changed since adoption preview')
            cfg = load_json(self.source_config)
            _, source_files = self._validated_source(cfg)
            if self._original_for_game(game, cfg) != preview['original']:
                raise ValueError('Genuine original binding changed')
            package = self.package(game, 'direct')
            if not package or package[2]['files'] != source_files:
                raise ValueError('Staged V762 package changed since adoption preview')
            # Repeat source proof just before committing any ownership record.
            original = preview['original']
            src = Path(original['path'])
            if self._symlink_in_path(src) or sha(src) != original['sha256']:
                raise ValueError('Genuine original changed')
            root = Path(game['folder'])
            paths = self.planned_paths(game, data, 'observe')
            baseline, current = {}, {}
            for rel in paths:
                p = checked_path(root, rel)
                current[rel] = sha(p) if p.is_file() else None
                baseline[rel] = None
            for target in map(Path, data['targets']):
                rel = str(target.relative_to(root))
                baseline[rel] = original['sha256']
                durable_copy(src, self.companion(game) / 'originals' / rel, original['sha256'])
            record = {'backend': BACKEND, 'adopted': True, 'route': 'direct', 'target': data['target'],
                      'targets': data['targets'], 'baseline': baseline, 'current': current,
                      'enabled': True, 'version': VERSION, 'package_selection': package_selection(package[2]),
                      'game_build': game.get('build'), 'updated_at': time.time()}
            # The originals copy above may be large. Revalidate the private
            # source, staged overrides, and original once more at commit time.
            _, final_source_files = self._validated_source(load_json(self.source_config))
            final_package = self.package(game, 'direct')
            if (final_source_files != source_files or not final_package
                    or final_package[2]['files'] != source_files
                    or self._original_for_game(game, load_json(self.source_config)) != original
                    or sha(src) != original['sha256']):
                raise ValueError('V762 source, package or original changed before adoption commit')
            if any((sha(checked_path(root, rel)) if checked_path(root, rel).is_file() else None) != digest
                   for rel, digest in current.items()):
                raise ValueError('Game files changed before adoption commit')
            atomic_json(self.record_path(game), record)
            return {'message': 'Verified V762 installation adopted', 'backend': BACKEND,
                    'enabled': True, 'version': VERSION, 'launch_environment': self.launch_environment(game)}
