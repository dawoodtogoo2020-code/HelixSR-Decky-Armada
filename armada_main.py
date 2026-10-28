"""Decky RPC surface for pinned Adreno HelixSR 2.0 and legacy V762 routes."""
import asyncio,json,re,shlex,sys
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
import decky
sys.path.insert(0,str(Path(__file__).parent/'py_modules'))
from armada_manager import ArmadaManager,PINNED,SOURCE_ALLOWED
from armada_host import ArmadaHost
from manager import sha,active_processes
from launch_receipts import LaunchReceipts
from library import discover
from helix2_manager import Helix2Manager

def verifies_options(actual,expected,addon=None):
    if not isinstance(actual,str) or len(actual)>16384 or any(x in actual for x in ('$','`','\x00','\n','\r','\\')):return False
    try:tokens=shlex.split(actual)
    except ValueError:return False
    leading={}
    for token in tokens:
        if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*=',token):break
        key,value=token.split('=',1)
        if key in leading:return False
        leading[key]=value
    if not all(leading.get(k)==v for k,v in expected.items()) or tokens.count('%command%')!=1:return False
    if addon is not None:
        wrapper='/usr/libexec/armada/armada-game-launch'
        if (leading.get('ENABLE_GAMESCOPE_WSI')!='0' or tokens.count('ENABLE_GAMESCOPE_WSI=0')!=1
                or any(t.startswith('ENABLE_GAMESCOPE_WSI=') and t!='ENABLE_GAMESCOPE_WSI=0' for t in tokens)
                or tokens.count(wrapper)!=1 or tokens.count(addon['helper'])!=1):return False
        at=tokens.index(wrapper)
        if at<2 or tokens[at-2:at]!=['/usr/bin/python3',addon['helper']]:return False
    if '/usr/libexec/armada/armada-game-launch' in tokens:
        at=tokens.index('%command%')
        return at>=3 and tokens[at-3:at]==['/usr/bin/env']+[k+'='+expected[k] for k in ('PROTON_USE_ARM64','VKD3D_SHADER_OVERRIDE')]
    return True

class Plugin:
    async def _io(self, func, *args, **kwargs):
        # Each call owns its worker. Exiting the context joins it, including
        # on cancellation, before the caller can release its mutation lock.
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='helixsr-rpc') as executor:
            return await loop.run_in_executor(executor, partial(func, *args, **kwargs))
    async def _main(self):
        self.lock=asyncio.Lock()
        self.stopping=False
        self.host=ArmadaHost(decky.DECKY_USER_HOME,decky.DECKY_PLUGIN_SETTINGS_DIR,Path(__file__).parent)
        self.manager=ArmadaManager(decky.DECKY_USER_HOME,decky.DECKY_PLUGIN_SETTINGS_DIR,host_probe=self.host.snapshot)
        self.helix2=Helix2Manager(self.manager)
        decky.logger.info('HelixSR Adreno ready; no Wine process or GPU probe started')
    async def _unload(self):
        self.stopping=True
        async with self.lock:pass
    async def _uninstall(self):pass
    def _h2_library(self):
        entries,warnings=discover(self.manager.home,sources={'steam'})
        # This release qualifies one exact provider/game pair. No game-tree scan.
        self.manager.entries.update({g['id']:g for g in entries})
        games=[{k:g[k] for k in ('id','name','folder','appid')} for g in entries if str(g.get('appid'))=='3357650']
        return {'games':games,'warnings':warnings,'source':self.helix2.source_status()}
    async def helix2_library(self):
        async with self.lock:return self._h2_library()
    async def helix2_status(self,gid):
        async with self.lock:return self.helix2.status(gid)
    async def helix2_register_source(self,path):
        async with self.lock:
            if self.stopping:raise ValueError('Plugin is unloading')
            return self.helix2.register_source(path)
    async def helix2_preview(self,gid,action,options=None):
        async with self.lock:
            if self.stopping:raise ValueError('Plugin is unloading')
            return self.helix2.preview(gid,action,options)
    async def helix2_execute(self,token):
        async with self.lock:
            if self.stopping:raise ValueError('Plugin is unloading')
            return self.helix2.execute(token)
    async def helix2_recover(self,gid):
        async with self.lock:
            if self.stopping:raise ValueError('Plugin is unloading')
            return self.helix2.recover(gid)
    async def library(self):
        async with self.lock:return await self._io(self.manager.refresh)
    async def armada_source_status(self):return await self._io(self.manager.source_status)
    async def armada_capabilities(self,refresh=False):
        async with self.lock:return await self._io(self.host.refresh) if refresh else self.host.snapshot()
    async def armada_register_source(self,source):
        async with self.lock:
            path=Path(source)
            if not path.is_absolute() or self.manager._symlink_in_path(path) or not path.is_dir():raise ValueError('Choose a real local V762 folder')
            files={}
            for p in path.rglob('*'):
                name=p.relative_to(path).as_posix()
                if p.is_symlink() or (not p.is_file() and not p.is_dir()):raise ValueError('Source contains an unsafe file')
                if p.is_file():
                    if name not in SOURCE_ALLOWED or p.stat().st_nlink!=1:raise ValueError('Source contains unknown or linked files')
                    files[name]=sha(p)
            if not set(PINNED).issubset(files) or not set(files).issubset(SOURCE_ALLOWED):raise ValueError('Choose the V762 payload folder, not its parent or an ordinary HelixSR release')
            return await self._io(self.manager.register_source,str(path),files)
    async def armada_prepare(self,gid,executable=None):
        async with self.lock:
            self.manager.guard_newer_runtime(self.manager.get_game(gid))
            return await self._io(self.manager.prepare_private,gid,executable)
    async def armada_status(self,gid,executable=None):
        async with self.lock:
            result=await self._io(self.manager.status,gid)
            if executable is not None:
                selected=await self._io(self.manager.assess_safe,self.manager.get_game(gid),executable=executable)
                result.update(selected)
            return result
    async def armada_preview(self,gid,action,dx12_confirmed=False,executable=None):
        async with self.lock:return await self._io(self.manager.preview,gid,action,bool(dx12_confirmed),executable)
    async def armada_execute(self,token,actual_options=None):
        async with self.lock:
            preview=self.manager.previews.get(token)
            if not preview:raise ValueError('Preview expired; review the change again')
            game=self.manager.get_game(preview['game'])
            enabling=preview['action'] in ('install','update','enable','armada-adopt')
            verified=False
            if enabling:
                expected=self.manager.launch_environment(game)
                receipt=await self._io(LaunchReceipts(self.manager.companion(game)).owned,actual_options)
                verified=bool(verifies_options(actual_options,expected,preview.get('launch_addon')) and
                    (receipt is None or (not receipt.get('pending') and receipt['after']==actual_options)))
                if not verified:raise ValueError('Save and verify the V762 Steam launch settings before changing game files')
            return await self._io(self.manager.execute,token,launch_environment_verified=verified)
    async def owned_launch_options(self,gid,actual=None):
        async with self.lock:return await self._io(LaunchReceipts(self.manager.companion(self.manager.get_game(gid))).owned,actual)
    async def remember_launch_addon(self,gid,actual_options):
        async with self.lock:
            game=self.manager.get_game(gid)
            self.manager.guard_newer_runtime(game)
            if active_processes(game['folder'],game.get('appid','')):raise ValueError('Close the game before saving the combined launcher')
            if not self.manager.record(game).get('enabled'):raise ValueError('The managed V762 installation must be enabled')
            receipt=await self._io(LaunchReceipts(self.manager.companion(game)).owned,actual_options)
            if receipt is None:return {'remembered':False}
            if receipt.get('pending') or receipt['after']!=actual_options:
                raise ValueError('Only finalized plugin-owned launch settings can save a combined launcher')
            return await self._io(self.manager.remember_launch_addon,gid,actual_options)
    async def prepare_launch_options(self,gid,before,after,restore=False):
        async with self.lock:
            game=self.manager.get_game(gid)
            self.manager.guard_newer_runtime(game)
            if active_processes(game['folder'],game.get('appid','')):raise ValueError('Close the game before changing launch settings')
            if restore and self.manager.record(game).get('enabled'):
                raise ValueError('Use the stock upscaler before restoring V762 launch settings')
            return await self._io(LaunchReceipts(self.manager.companion(game)).prepare,before,after,bool(restore))
    async def finalize_launch_options(self,gid,nonce,actual):
        async with self.lock:return await self._io(LaunchReceipts(self.manager.companion(self.manager.get_game(gid))).finalize,nonce,actual)
