"""Decky RPC surface for the pinned private V762 Armada backend."""
import asyncio,json,re,shlex,sys
from pathlib import Path
import decky
sys.path.insert(0,str(Path(__file__).parent/'py_modules'))
from armada_manager import ArmadaManager,PINNED,SOURCE_ALLOWED
from armada_host import ArmadaHost
from manager import sha,active_processes
from launch_receipts import LaunchReceipts

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
    async def _main(self):
        self.lock=asyncio.Lock()
        self.host=ArmadaHost(decky.DECKY_USER_HOME,decky.DECKY_PLUGIN_SETTINGS_DIR,Path(__file__).parent)
        await asyncio.to_thread(self.host.refresh)
        self.manager=ArmadaManager(decky.DECKY_USER_HOME,decky.DECKY_PLUGIN_SETTINGS_DIR,host_probe=self.host.snapshot)
        decky.logger.info('HelixSR Decky Armada ready; ordinary upstream updates disabled')
    async def _unload(self):pass
    async def _uninstall(self):pass
    async def library(self):
        async with self.lock:return await asyncio.to_thread(self.manager.refresh)
    async def armada_source_status(self):return await asyncio.to_thread(self.manager.source_status)
    async def armada_capabilities(self,refresh=False):
        async with self.lock:return await asyncio.to_thread(self.host.refresh) if refresh else self.host.snapshot()
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
            return await asyncio.to_thread(self.manager.register_source,str(path),files)
    async def armada_prepare(self,gid,executable=None):
        async with self.lock:return await asyncio.to_thread(self.manager.prepare_private,gid,executable)
    async def armada_status(self,gid,executable=None):
        async with self.lock:
            result=await asyncio.to_thread(self.manager.status,gid)
            if executable is not None:
                selected=await asyncio.to_thread(self.manager.assess_safe,self.manager.get_game(gid),executable=executable)
                result.update(selected)
            return result
    async def armada_preview(self,gid,action,dx12_confirmed=False,executable=None):
        async with self.lock:return await asyncio.to_thread(self.manager.preview,gid,action,bool(dx12_confirmed),executable)
    async def armada_execute(self,token,actual_options=None):
        async with self.lock:
            preview=self.manager.previews.get(token)
            if not preview:raise ValueError('Preview expired; review the change again')
            game=self.manager.get_game(preview['game'])
            enabling=preview['action'] in ('install','update','enable','armada-adopt')
            verified=False
            if enabling:
                expected=self.manager.launch_environment(game)
                receipt=await asyncio.to_thread(LaunchReceipts(self.manager.companion(game)).owned,actual_options)
                verified=bool(verifies_options(actual_options,expected,preview.get('launch_addon')) and
                    (receipt is None or (not receipt.get('pending') and receipt['after']==actual_options)))
                if not verified:raise ValueError('Save and verify the V762 Steam launch settings before changing game files')
            return await asyncio.to_thread(self.manager.execute,token,launch_environment_verified=verified)
    async def owned_launch_options(self,gid,actual=None):
        async with self.lock:return await asyncio.to_thread(LaunchReceipts(self.manager.companion(self.manager.get_game(gid))).owned,actual)
    async def remember_launch_addon(self,gid,actual_options):
        async with self.lock:
            game=self.manager.get_game(gid)
            if active_processes(game['folder'],game.get('appid','')):raise ValueError('Close the game before saving the combined launcher')
            if not self.manager.record(game).get('enabled'):raise ValueError('The managed V762 installation must be enabled')
            receipt=await asyncio.to_thread(LaunchReceipts(self.manager.companion(game)).owned,actual_options)
            if receipt is None:return {'remembered':False}
            if receipt.get('pending') or receipt['after']!=actual_options:
                raise ValueError('Only finalized plugin-owned launch settings can save a combined launcher')
            return await asyncio.to_thread(self.manager.remember_launch_addon,gid,actual_options)
    async def prepare_launch_options(self,gid,before,after,restore=False):
        async with self.lock:
            game=self.manager.get_game(gid)
            if active_processes(game['folder'],game.get('appid','')):raise ValueError('Close the game before changing launch settings')
            if restore and self.manager.record(game).get('enabled'):
                raise ValueError('Use the stock upscaler before restoring V762 launch settings')
            return await asyncio.to_thread(LaunchReceipts(self.manager.companion(game)).prepare,before,after,bool(restore))
    async def finalize_launch_options(self,gid,nonce,actual):
        async with self.lock:return await asyncio.to_thread(LaunchReceipts(self.manager.companion(self.manager.get_game(gid))).finalize,nonce,actual)
