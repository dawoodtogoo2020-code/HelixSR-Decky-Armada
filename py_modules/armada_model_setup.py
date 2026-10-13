"""Build the pinned Model E/V762 package locally from public upstream inputs.

Never installs into a game, downloads private dumps, or uploads model material.
The user's explicit terms acknowledgement is required before any acquisition.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
import uuid

from armada_manager import PINNED, SOURCE_ALLOWED, _host_eligible
from armada_setup_io import safe_path, fetch_asset, extract_zip, extract_tar, extractor_available
from armada_capture_bootstrap import bootstrap
from host_environment import host_environment
from manager import (DLL, NETWORK, PACKAGE_FILES, AMD_FG, atomic_json, load_json,
                     sha, active_processes, pe_info)
from model_variants import verify_recipe, verify_outputs
from operation_lock import operation_lock

PROBE_SHA = 'a6f2765a4b759893dc411b5c36916319ca8450ecc1f44a08049686e1db482bf5'
TERMS_REV = 'armada-public-model-e-v762-1'
NVIDIA_TERMS = 'https://github.com/NVIDIA/DLSS/blob/v310.7.0/LICENSE.txt'
HELIX_TERMS = 'https://github.com/lonewolf0622/HelixSR/blob/v1.8.0/LICENSE'
ASSET_PINS = {
    'upstream': '7041d4bee121cc33c24660902c9f09481ed15644fe2ff5a458071337e0cda848',
    'python': '95c01982c9fcb9d95b0acfdb5eb8a6e0099dd11edf062314a474228d93f2b765',
    'numpy': 'f2618db89be1b4e05f7a1a847a9c1c0abd63e63a1607d892dd54668dd92faf87',
    'dxc': 'a1dfb116ba3eeae6a1582291b53a8e7bf65ad760676bd3194685c8f7367cd241',
    'dlss': 'be6e434a94ca32499515eb62ca0e6c274526055d568d0426e4c652dcdfb6ee6e',
}
ASSET_SIZES = {'upstream': 56617399, 'python': 52330698, 'numpy': 14018462,
               'dxc': 41625275, 'dlss': 58977904}
ASSET_URLS = {
    'upstream': 'https://github.com/lonewolf0622/HelixSR/releases/download/v1.8.0/HelixSR-1.8.0.zip',
    'python': 'https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.12.15%2B20261003-aarch64-unknown-linux-gnu-install_only.tar.gz',
    'numpy': 'https://files.pythonhosted.org/packages/f8/35/8c80729f1ff76b3921d5c9487c7ac3de9b2a103b1cd05e905b3090513510/numpy-2.2.6-cp312-cp312-manylinux_2_17_aarch64.manylinux2014_aarch64.whl',
    'dxc': 'https://github.com/microsoft/DirectXShaderCompiler/releases/download/v1.9.2607/dxc_2026_07_29.zip',
    'dlss': 'https://raw.githubusercontent.com/NVIDIA/DLSS/v310.7.0/lib/Windows_x86_64/rel/nvngx_dlss.dll',
}


def public_assets(plugin):
    path = safe_path(Path(plugin) / 'model_setup/assets.json')
    if not path.is_file() or path.stat().st_size > 16384:
        raise ValueError('Public setup manifest is missing or too large')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or set(value) != set(ASSET_PINS):
        raise ValueError('Public setup manifest changed')
    for name, item in value.items():
        expected = {'url': ASSET_URLS[name], 'size': ASSET_SIZES[name], 'sha256': ASSET_PINS[name]}
        if item != expected or type(item.get('size')) is not int:
            raise ValueError('Public setup asset pin changed: ' + name)
    return value


def clean_message(error):
    text = str(error).splitlines()[0] if str(error) else 'Model setup failed'
    text = re.sub(r'https?://\S+', '[source]', text)
    text = re.sub(r'(?:[A-Za-z]:[\\/]|/)[^\s,;]+', '[local file]', text)
    return ''.join(c for c in text if ord(c) >= 32)[:300]


def native_command(path):
    return '/proc/self/root' + str(path)


def windows_path(path):
    """Match the original capture helper's bounded Windows path contract."""
    text = 'Z:' + str(path)
    if len(text.encode('utf-16-le')) // 2 > 240 or not str(path).startswith('/'):
        raise ValueError('The game companion path is too long for model setup; use a shorter Steam library path')
    for part in str(path).split('/')[1:]:
        if (not part or part.endswith(('.', ' ')) or any(ord(c) < 32 or c in ':"<>|?*\\' for c in part)
                or re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I)):
            raise ValueError('The game companion path is incompatible with the Windows model tools')
    return text


def restore_bytes(path, data):
    """Restore only the recorded source configuration, without losing its bytes."""
    path = safe_path(path)
    if data is None:
        path.unlink(missing_ok=True)
        return
    temp = path.with_name(path.name + '.restore-' + uuid.uuid4().hex)
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def transform_dumps(recipe, dumps, destination, cancelled, shader_ids=None):
    """Require exact previously independently validated input AND output bytes."""
    recipe, dumps, destination = map(safe_path, (recipe, dumps, destination))
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError('Override output must be a new owned directory')
    manifest = json.loads((recipe / 'manifest.json').read_text(encoding='utf-8'))
    entries = manifest.get('entries', [])
    expected_names = {name.removeprefix('shader-override/').removesuffix('.spv')
                      for name in PINNED if name.startswith('shader-override/')}
    if (manifest.get('physical_subgroup_size') != 64 or len(entries) != 4
            or any(not isinstance(e, dict) for e in entries)
            or {e.get('shader_hash') for e in entries} != expected_names):
        raise ValueError('The V762 transform recipe changed')
    selected = expected_names if shader_ids is None else set(shader_ids)
    if not selected or not selected.issubset(expected_names):
        raise ValueError('Unknown V762 capture selection')
    modules = []
    for name in ('wave32', 'split_uniform'):
        spec = importlib.util.spec_from_file_location('armada_v762_' + name, recipe / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        if spec.loader is None:
            raise ValueError('V762 transform source is unavailable')
        spec.loader.exec_module(module)
        modules.append(module)
    outputs = []
    for entry in entries:
        if entry['shader_hash'] not in selected:
            continue
        if cancelled.is_set():
            raise RuntimeError('Cancelled')
        name = entry['shader_hash'] + '.spv'
        if not re.fullmatch(r'[a-f0-9]{16}\.spv', name) or 'shader-override/' + name not in PINNED:
            raise ValueError('Unknown V762 shader identifier')
        path = safe_path(dumps / name)
        if not path.is_file() or path.stat().st_size > 8 << 20:
            raise ValueError('The runtime did not capture every required V762 shader')
        original = path.read_bytes()
        if (not re.fullmatch('[a-f0-9]{64}', str(entry.get('input_spv_sha256', '')))
                or hashlib.sha256(original).hexdigest() != entry['input_spv_sha256']):
            raise ValueError('This Proton shader conversion differs from reviewed V762; no game files changed')
        logical, wave = modules[0].transform(original)
        result, split = modules[1].run(original, logical)
        expected = PINNED['shader-override/' + name]
        if entry['output_spv_sha256'] != expected or hashlib.sha256(result).hexdigest() != expected:
            raise ValueError('Generated V762 override does not match its validated pin')
        if (type(entry.get('min_split_chains')) is not int or entry['min_split_chains'] < 0
                or split.get('split_chains', 0) < entry['min_split_chains']):
            raise ValueError('V762 subgroup transform is incomplete')
        outputs.append((name, result, wave, split))
    if cancelled.is_set():
        raise RuntimeError('Cancelled')
    destination.mkdir(mode=0o700)
    try:
        for name, data, _, _ in outputs:
            path = destination / name
            path.write_bytes(data)
            path.chmod(0o600)
    except BaseException:
        shutil.rmtree(destination)
        raise
    return {'modules': [{'name': name, 'sha256': hashlib.sha256(data).hexdigest()}
                        for name, data, _, _ in outputs],
            'matches_previously_independently_validated_bytes': True,
            'new_spirv_validator_run': False, 'gameplay_tested': False}


class ArmadaModelSetup:
    def __init__(self, manager, host, plugin, settings):
        self.manager, self.host = manager, host
        self.plugin, self.settings = map(Path, (plugin, settings))
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread = None
        self._plans = {}
        self._prefixes = []
        self.record_path = self.settings / 'armada-model-setup.json'
        safe_path(self.record_path)
        self.job = {'state': 'idle'}
        if self.record_path.is_file() and self.record_path.stat().st_size <= 65536:
            try:
                prior = load_json(self.record_path)
                if (isinstance(prior, dict) and prior.get('state') in ('running', 'completed', 'failed', 'cancelled', 'interrupted')
                        and isinstance(prior.get('id'), str) and re.fullmatch('[a-f0-9]{32}', prior['id'])
                        and isinstance(prior.get('gid'), str) and len(prior['gid']) <= 256):
                    self.job = prior
                    if prior['state'] == 'running':
                        self.job.update(state='interrupted', phase='interrupted',
                                        message='Setup was interrupted. Start it again; no installation is assumed ready.',
                                        ended_at=time.time(), result=None)
                        self._save()
            except (OSError, ValueError, TypeError):
                self.job = {'state': 'idle', 'message': 'Previous setup record needs review'}
        elif self.record_path.exists():
            self.job = {'state': 'idle', 'message': 'Previous setup record needs review'}

    def _save(self):
        safe_path(self.record_path)
        atomic_json(self.record_path, self.job)

    def status(self):
        with self._lock:
            job = copy.deepcopy(self.job)
            if self._thread and self._thread.is_alive() and job.get('state') != 'running':
                job.update(state='running', phase='cleanup', message='Finishing private setup cleanup')
            if job.get('state') == 'completed':
                source = self.manager.source_status()
                if not source.get('ready') or source.get('source') != (job.get('result') or {}).get('source'):
                    job.update(state='interrupted', result=None,
                               message='Previously prepared files are unavailable. Review the current model source.')
            return job

    def busy(self):
        with self._lock:
            return self.job.get('state') == 'running' or bool(self._thread and self._thread.is_alive())

    def _check_cancel(self):
        if self._cancel.is_set():
            raise RuntimeError('Cancelled')

    def _progress(self, phase, message):
        with self._lock:
            self._check_cancel()
            self.job.update(phase=phase, message=message)
            self._save()

    def _runtime(self):
        steam = (self.manager.home / '.local/share/Steam').resolve()
        runtime = steam / 'steamapps/common/Proton Experimental (ARM64)'
        for path in (runtime / 'proton', runtime / 'files/bin-arm64/wineserver'):
            if not path.is_file():
                raise ValueError('Install Proton Experimental (ARM64) through Steam first')
        return steam, runtime

    def _game(self, gid, executable=None):
        game = self.manager.get_game(gid)
        data = self.manager.assess_safe(game, executable=executable)
        if data['compatibility'] != 'candidate' or not data.get('dx12_detected'):
            raise ValueError('; '.join(data.get('reasons') or ['Choose an eligible DX12 game']))
        return game

    def _preflight(self, gid, executable):
        if os.name != 'posix' or os.geteuid() == 0 or not _host_eligible(self.host.snapshot):
            raise ValueError('Verified ARM64 Armada, Qualcomm wave64 and VKD3D are required')
        game = self._game(gid, executable)
        extractor_available()
        self._runtime()
        companion = safe_path(self.manager.companion(game))
        sample_work = companion / 'staging/setup-000000000000'
        for path in (sample_work / 'verified-source' / DLL, sample_work / 'capture-4/capture-report.ndjson',
                     self.plugin / 'bin/armada_model_probe.exe'):
            windows_path(path)
        ancestor = companion
        while not ancestor.exists():
            ancestor = ancestor.parent
        if shutil.disk_usage(ancestor).free < 3 << 30:
            raise ValueError('At least 3 GiB free on the game drive is required')
        if sha(safe_path(self.plugin / 'bin/armada_model_probe.exe')) != PROBE_SHA:
            raise ValueError('The model setup helper is missing or changed')
        public_assets(self.plugin)
        return game

    def plan(self, gid, executable=None):
        blockers = []
        try:
            if self.busy():
                raise ValueError('A model setup is already running')
            self._preflight(gid, executable)
            assets = public_assets(self.plugin)
            token = uuid.uuid4().hex
            with self._lock:
                self._plans = {token: {'gid': gid, 'executable': executable, 'expires': time.monotonic() + 300}}
            return {'can_start': True, 'token': token, 'model': 'HelixSR Model E / V762',
                    'download_bytes': sum(item['size'] for item in assets.values()),
                    'required_free_gib': 3, 'terms_revision': TERMS_REV,
                    'terms': [{'name': 'HelixSR licence', 'url': HELIX_TERMS},
                              {'name': 'NVIDIA DLSS 310.7.0 licence', 'url': NVIDIA_TERMS}],
                    'notice': 'Downloads official inputs and builds the model locally. Generated files stay on this device. No game files change during setup.'}
        except (OSError, ValueError, KeyError) as error:
            blockers.append(clean_message(error))
        return {'can_start': False, 'blockers': blockers}

    def start(self, token, accepted=False):
        with self._lock:
            plan = self._plans.pop(token, None)
            if self.busy() or not plan or plan['expires'] < time.monotonic():
                raise ValueError('Setup review expired or another setup is running; review it again')
            if accepted is not True:
                raise ValueError('Review and explicitly agree to the linked terms before setup')
            game = self._preflight(plan['gid'], plan['executable'])
            self._cancel = threading.Event()
            self._prefixes = []
            safe_path(self.manager.source_config)
            self._prior_source = self.manager.source_config.read_bytes() if self.manager.source_config.exists() else None
            atomic_json(safe_path(self.settings / 'armada-model-terms.json'),
                        {'terms_revision': TERMS_REV, 'assets': ASSET_PINS,
                         'terms': [HELIX_TERMS, NVIDIA_TERMS], 'acknowledged_at': time.time()})
            self.job = {'id': uuid.uuid4().hex, 'gid': plan['gid'], 'state': 'running',
                        'phase': 'starting', 'message': 'Preparing the local model setup',
                        'started_at': time.time(), 'ended_at': None, 'result': None}
            try:
                self._save()
                self._thread = threading.Thread(target=self._run, args=(game,), daemon=True)
                self._thread.start()
            except BaseException:
                self.job.update(state='failed', message='Setup could not start; review local storage permissions')
                raise
            return self.status()

    def cancel(self, job_id):
        with self._lock:
            if self.job.get('id') != job_id:
                raise ValueError('That setup job is unavailable')
            if self.job['state'] == 'running':
                self._cancel.set()
                self.job['message'] = 'Cancelling setup; existing installations will be preserved'
                self._save()
            return self.status()

    def close(self):
        self._cancel.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=60)
            if thread.is_alive():
                raise RuntimeError('Model setup cleanup is still active; wait for cancellation before unloading the plugin')

    def _process(self, command, folder, env, logfile, timeout, allowed_exit_codes=(0,)):
        self._check_cancel()
        with logfile.open('ab') as log:
            child = subprocess.Popen(command, cwd=folder, env=env, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + timeout
            try:
                while child.poll() is None:
                    self._check_cancel()
                    if time.monotonic() > deadline:
                        raise RuntimeError('Local model preparation timed out')
                    self._cancel.wait(0.3)
                if child.returncode not in allowed_exit_codes:
                    raise RuntimeError('A local model preparation tool failed; the private build log is in the game companion')
                return child.returncode
            except BaseException:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait(timeout=5)
                raise

    def _environment(self, steam, runtime, prefix):
        env = {k: v for k, v in host_environment().items()
               if not k.startswith(('WINE', 'PROTON_', 'DXVK_', 'VKD3D_', 'STEAM_COMPAT_', 'Steam', 'HELIXSR_'))
               and k not in ('LD_PRELOAD', 'VK_ICD_FILENAMES', 'VK_DRIVER_FILES', 'VK_INSTANCE_LAYERS', 'VK_LAYER_PATH', 'PYTHONPATH')}
        data = safe_path(prefix)
        if data.exists():
            raise ValueError('Setup requires a new isolated compatibility prefix')
        (data / 'pfx/dosdevices').mkdir(parents=True, exist_ok=True, mode=0o700)
        self._prefixes.append((data, runtime, steam))
        env.update(PROTON_USE_ARM64='1', PROTON_LOG='0', WINEDEBUG='-all',
                   WINESERVER=str(runtime / 'files/bin-arm64/wineserver'), WINEPREFIX=str(data / 'pfx'),
                   STEAM_COMPAT_DATA_PATH=str(data), STEAM_COMPAT_CLIENT_INSTALL_PATH=str(steam),
                   SteamAppId='0', SteamGameId='0', STEAM_COMPAT_APP_ID='0',
                   OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PYTHONUNBUFFERED='1')
        return env

    def _close_prefixes(self, work):
        failures, remaining = [], []
        for prefix, runtime, steam in self._prefixes:
            try:
                safe_path(prefix)
                if not prefix.is_relative_to(work) or not (prefix / 'pfx').is_dir():
                    raise ValueError('Unexpected setup prefix')
                env = host_environment()
                env['WINEPREFIX'] = str(prefix / 'pfx')
                env['WINESERVER'] = str(runtime / 'files/bin-arm64/wineserver')
                for command in ('-k', '-w'):
                    result = subprocess.run([native_command(runtime / 'files/bin-arm64/wineserver'), command],
                        env=env, cwd=work, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, timeout=10)
                    if result.returncode:
                        raise RuntimeError('Private setup compatibility process did not stop')
            except (OSError, ValueError, subprocess.TimeoutExpired, RuntimeError) as error:
                failures.append(clean_message(error))
                remaining.append((prefix, runtime, steam))
        self._prefixes = remaining
        return failures

    def _dependency(self, name, companion, archive=None, work=None):
        key = name + '-' + ASSET_PINS[name][:12]
        destination = safe_path(companion / 'dependencies' / key)
        receipt = safe_path(companion / 'records' / ('dependency-' + key + '.json'))
        if destination.exists():
            if not destination.is_dir() or not receipt.is_file() or receipt.stat().st_size > 4 << 20:
                raise ValueError('An installed setup dependency needs review')
            record = load_json(receipt)
            files = record.get('files') if isinstance(record, dict) else None
            if not isinstance(files, dict) or not files or record.get('asset_sha256') != ASSET_PINS[name]:
                raise ValueError('An installed setup dependency record changed')
            actual = {p.relative_to(destination).as_posix() for p in destination.rglob('*') if not p.is_dir() or p.is_symlink()}
            if actual != set(files):
                raise ValueError('An installed setup dependency contains changed or extra files')
            for relative, expected in files.items():
                self._check_cancel()
                path = safe_path(destination / relative)
                if not path.is_relative_to(destination) or not path.is_file() or sha(path) != expected:
                    raise ValueError('An installed setup dependency failed its hash check')
            return destination
        if archive is None:
            return None
        temporary = work / ('dependency-' + name)
        (extract_tar if name == 'python' else extract_zip)(archive, temporary)
        files = {}
        for path in temporary.rglob('*'):
            self._check_cancel()
            if path.is_file():
                files[path.relative_to(temporary).as_posix()] = sha(safe_path(path))
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.replace(temporary, destination)
        try:
            atomic_json(receipt, {'asset_sha256': ASSET_PINS[name], 'files': files})
        except BaseException:
            shutil.rmtree(destination)
            raise
        return destination

    def _wrapper(self, work, python, runtime, binary, name):
        script = work / (name + '.py')
        script.write_text('import os,sys\nargs=[("Z:"+a) if a.startswith("/") else a for a in sys.argv[1:]]\n'
                          + 'os.execv(' + repr('/proc/self/root/usr/bin/python3') + ', '
                          + repr(['/proc/self/root/usr/bin/python3', str(runtime / 'proton'), 'run', 'Z:' + str(binary)])
                          + '+args)\n', encoding='utf-8')
        wrapper = work / name
        wrapper.write_text('#!/usr/bin/env bash\nexec ' + shlex.quote(native_command(python)) + ' '
                           + shlex.quote(str(script)) + ' "$@"\n', encoding='utf-8')
        wrapper.chmod(0o700)
        return wrapper

    def _capture(self, source, work, steam, runtime, logfile):
        self._progress('capture', 'Generating the Adreno shader inputs in a game-free local probe')
        required = frozenset(name.removeprefix('shader-override/').removesuffix('.spv')
                             for name in PINNED if name.startswith('shader-override/'))
        overrides = safe_path(source / 'shader-override')
        overrides.mkdir(mode=0o700)
        modules = []

        def run_probe(index, ready, final):
            self._check_cancel()
            for game in self.manager.refresh()['games']:
                if active_processes(game['folder'], game.get('appid', '')):
                    raise ValueError('Close running games before the shader capture, then start setup again')
            if not _host_eligible(self.host.snapshot):
                raise ValueError('The required ARM64/wave64 runtime proof is unavailable')
            attempt = work / ('capture-' + str(index)); attempt.mkdir(mode=0o700)
            dumps = attempt / 'dumps'; dumps.mkdir(mode=0o700)
            report = attempt / 'capture-report.ndjson'
            self._progress('validate' if final else 'capture',
                           'Validating the generated overrides in a controlled local scene' if final else
                           'Capturing verified shader inputs (' + str(len(ready)) + ' of 4 prepared)')
            env = self._environment(steam, runtime, attempt / 'prefix')
            env.update(VKD3D_SHADER_DUMP_PATH='Z:' + str(dumps), VKD3D_SHADER_CACHE_PATH='0',
                       VKD3D_FILTER_DEVICE_NAME='Adreno', VKD3D_DEBUG='info', DISPLAY=':1')
            if ready:
                env['VKD3D_SHADER_OVERRIDE'] = 'Z:' + str(overrides)
            try:
                code = self._process(['/proc/self/root/usr/bin/python3', str(runtime / 'proton'), 'run',
                                      'Z:' + str(self.plugin / 'bin/armada_model_probe.exe'), 'Z:' + str(source),
                                      'Z:' + str(report)], attempt, env, logfile, 180, allowed_exit_codes=(0, 1))
            finally:
                if self._close_prefixes(work):
                    raise RuntimeError('A shader capture process did not stop safely; private staging was retained')
            safe_path(report)
            if not report.is_file() or report.stat().st_size > 16384:
                raise ValueError('The shader capture did not produce a valid bounded report')
            events = [json.loads(line) for line in report.read_text().splitlines()]
            if any(not isinstance(event, dict) for event in events):
                raise ValueError('The shader capture report is invalid')
            results = [event for event in events if event.get('event') == 'result']
            if len(results) != 1:
                raise ValueError('The shader capture result is missing or ambiguous')
            return {'exit_code': code, 'result': results[0]}

        def collect(index, missing):
            attempt = work / ('capture-' + str(index))
            found = {name for name in missing if (attempt / 'dumps' / (name + '.spv')).exists()}
            if not found:
                return set()
            self._progress('transform', 'Checking captured inputs and generating pinned V762 overrides')
            transformed = transform_dumps(self.plugin / 'model_setup/v762', attempt / 'dumps',
                                          attempt / 'transformed', self._cancel, found)
            for item in transformed['modules']:
                self._check_cancel()
                original = safe_path(attempt / 'transformed' / item['name'])
                target = safe_path(overrides / item['name'])
                os.link(original, target)  # Exclusive; never replace an earlier accepted output.
                original.unlink()
                modules.append(item)
            return found

        outcome = bootstrap(required, run_probe, collect, self._cancel)
        final = outcome['final_probe']
        if (final.get('rgb_validation_passed') is not True or type(final.get('rgb_frames_checked')) is not int
                or final['rgb_frames_checked'] != 2 or final.get('exposure') != 'unit'):
            raise ValueError('The controlled model scene failed RGB validation; no installation changed')
        return {'modules': sorted(modules, key=lambda item: item['name']),
                'matches_previously_independently_validated_bytes': True,
                'discovery_attempts': outcome['discovery_attempts'], 'analytic_unit_exposure_rgb_checked': True,
                'new_spirv_validator_run': False, 'gameplay_tested': False, 'quality_tested': False}

    def _build(self, game, work, logfile):
        assets = public_assets(self.plugin)
        steam, runtime = self._runtime()
        companion = safe_path(self.manager.companion(game))
        paths, dependencies = {}, {}
        for name, spec in assets.items():
            if name in ('python', 'numpy', 'dxc'):
                installed = self._dependency(name, companion)
                if installed:
                    dependencies[name] = installed
                    continue
            self._progress('download', 'Downloading and checking official ' + name + ' input')
            path = work / (name + '.download')
            fetch_asset(spec, path, self._cancel)
            paths[name] = path
        self._progress('dependencies', 'Preparing private native ARM64 build dependencies')
        extract_zip(paths['upstream'], work / 'upstream')
        package = work / 'upstream/HelixSR-1.8.0'
        verify_recipe(package)
        if sha(package / DLL) != PINNED[DLL]:
            raise ValueError('The upstream provider differs from pinned HelixSR 1.8.0')
        for name in ('python', 'numpy', 'dxc'):
            if name not in dependencies:
                dependencies[name] = self._dependency(name, companion, paths[name], work)
        python = safe_path(dependencies['python'] / 'python/bin/python3.12')
        if not python.is_file():
            raise ValueError('The pinned standalone Python interpreter is unavailable')
        sites = dependencies['numpy']
        env = self._environment(steam, runtime, work / 'compiler-prefix')
        env.update(PYTHONPATH=str(sites), PYTHONDONTWRITEBYTECODE='1',
                   TMPDIR=str(work / 'tmp'), TEMP=str(work / 'tmp'), TMP=str(work / 'tmp'))
        (work / 'tmp').mkdir(mode=0o700)
        self._process([native_command(python), '-c',
                       'import platform,numpy; assert platform.machine() in ("aarch64","arm64"); assert numpy.__version__=="2.2.6"'],
                      work, env, logfile, 20)
        dxc = self._wrapper(work, python, runtime, dependencies['dxc'] / 'bin/x64/dxc.exe', 'dxc-run')
        synth = self._wrapper(work, python, runtime, package / 'setup/lib/model/launch_synth.exe', 'synth-run')
        converter = package / 'setup/helixsr_setup.py'
        text = converter.read_text()
        anchor = "    synth = m / ('launch_synth.exe' if os.name == 'nt' else 'launch_synth')   # prebuilt, static"
        if text.count(anchor) != 1:
            raise ValueError('The reviewed upstream synthesis adapter no longer matches')
        converter.write_text(text.replace(anchor, '    synth = Path(os.environ["HELIXSR_ARMADA_SYNTH"])  # Armada local wrapper'), newline='\n')
        env['HELIXSR_ARMADA_SYNTH'] = str(synth)
        self._progress('build', 'Building Model E locally; no games are changed during this step')
        self._process([native_command(python), str(converter), str(package), '--dlss', str(paths['dlss']),
                       '--dxc', str(dxc), '--wave64', '--separate-files', '--yes'], work, env, logfile, 1200)
        verify_outputs(package)
        for name in (DLL, *NETWORK):
            if sha(package / name) != PINNED[name]:
                raise ValueError('The local model build does not reproduce the reviewed V762 package')
        source = work / 'verified-source'; source.mkdir(mode=0o700)
        for name in sorted(SOURCE_ALLOWED - set(n for n in SOURCE_ALLOWED if n.startswith('shader-override/'))):
            original = self.plugin / 'model_setup/helixsr.ini' if name == 'helixsr.ini' else package / name
            if original.is_file():
                target = source / name; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copyfile(safe_path(original), target); target.chmod(0o600)
        if not set(PACKAGE_FILES).issubset({p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}):
            raise ValueError('The public release lacks complete installation payloads')
        transform = self._capture(source, work, steam, runtime, logfile)
        files = {p.relative_to(source).as_posix(): sha(p) for p in source.rglob('*') if p.is_file()}
        self.manager._validated_source({'source': str(source), 'files': files})
        return source, files, transform

    def _run(self, game):
        work = None
        try:
            companion = safe_path(self.manager.companion(game))
            with operation_lock(companion):
                staging = safe_path(companion / 'staging'); staging.mkdir(parents=True, exist_ok=True, mode=0o700)
                work = staging / ('setup-' + self.job['id'][:12]); work.mkdir(mode=0o700)
                records = safe_path(companion / 'records'); records.mkdir(parents=True, exist_ok=True, mode=0o700)
                logfile = records / ('model-setup-' + self.job['id'] + '.log')
                source, files, transform = self._build(game, work, logfile)
                self._check_cancel()
                cleanup_errors = self._close_prefixes(work)
                if cleanup_errors:
                    raise RuntimeError('Setup tools did not stop safely; retained private staging needs review')
                destination = safe_path(companion / ('packages/model-e-v762-' + self.job['id'][:12]))
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with self._lock:
                    self._check_cancel()
                    config_path = safe_path(self.manager.source_config)
                    current = config_path.read_bytes() if config_path.exists() else None
                    if current != self._prior_source:
                        raise ValueError('The selected model source changed during setup; review it again')
                    if destination.exists():
                        raise ValueError('The new prepared model destination already exists')
                    os.replace(source, destination)
                    try:
                        result = {'ready': True, 'source': str(destination), 'model': 'HelixSR Model E / V762',
                                  'game_files_changed': False, 'gameplay_tested': False, 'transform': transform}
                        atomic_json(records / ('model-setup-' + self.job['id'] + '.json'),
                                    {'assets': ASSET_PINS, 'files': files, 'result': result, 'terms_revision': TERMS_REV})
                        status = self.manager.register_source(str(destination), files)
                        if status.get('ready') is not True or status.get('source') != str(destination):
                            raise ValueError('Prepared source did not pass its final registration check')
                        self.job.update(state='completed', phase='completed', message='Model verified. Review Install HelixSR to apply it to a game.',
                                        result=result, ended_at=time.time())
                        self._save()
                    except BaseException as error:
                        try:
                            restore_bytes(config_path, self._prior_source)
                        except OSError:
                            raise RuntimeError('Source activation needs review; verified files were retained') from error
                        shutil.rmtree(destination)
                        raise
        except Exception as error:
            with self._lock:
                self.job.update(state='cancelled' if self._cancel.is_set() else 'failed',
                                phase='finished', message=clean_message(error), result=None, ended_at=time.time())
                try:
                    self._save()
                except OSError:
                    self.job['record_warning'] = 'Setup status could not be saved; review local permissions and free space'
        finally:
            if work and work.exists():
                errors = self._close_prefixes(work)
                if errors:
                    with self._lock:
                        self.job['cleanup_warning'] = 'Private setup tools did not stop; staging was retained for review'
                else:
                    try:
                        # Only this job's new staging; never installed dependencies, games or global caches.
                        shutil.rmtree(work)
                    except OSError:
                        with self._lock:
                            self.job['cleanup_warning'] = 'Private setup staging could not be removed'
                with self._lock:
                    try:
                        self._save()
                    except OSError:
                        pass  # The already recorded outcome or interruption marker remains available.
