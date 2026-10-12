"""Read-only D3D12 capability proof through the installed Proton ARM64 runtime."""
import hashlib,json,os,signal,subprocess,time
from pathlib import Path
from host_environment import host_environment

PROBE_SHA='d96c97b0b280722f72c86d62f2b8ce43c49019318077c2a268b69a82acc4135d'
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

class ArmadaHost:
    def __init__(self,home,settings,plugin):
        self.home,self.settings,self.plugin=map(Path,(home,settings,plugin))
        self.facts={}
    def snapshot(self):return dict(self.facts)
    def refresh(self):
        steam=(self.home/'.local/share/Steam').resolve()
        runtime=steam/'steamapps/common/Proton Experimental (ARM64)'
        probe=self.plugin/'bin/wave_probe.exe'
        record=self.settings/'armada-capabilities.json'
        if not probe.is_file() or digest(probe)!=PROBE_SHA:
            self.facts={'reason':'Capability probe missing or changed'};return self.snapshot()
        if not (runtime/'proton').is_file() or not (runtime/'files/bin-arm64/wineserver').is_file():
            self.facts={'reason':'Install Proton Experimental (ARM64) in Steam'};return self.snapshot()
        native_root='/proc/self/root'
        native_arch=subprocess.run([native_root+'/usr/bin/uname','-m'],env=host_environment(),capture_output=True,text=True,timeout=5).stdout.strip()
        if native_arch not in ('aarch64','arm64'):
            self.facts={'native_arch':native_arch,'reason':'A native ARM64 host is required'};return self.snapshot()
        stamp={'native_arch':native_arch,'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
               'runtime':str(runtime),'proton_sha256':digest(runtime/'proton'),
               'os_release_sha256':digest('/etc/os-release'),'probe_sha256':PROBE_SHA,
               'driver_sha256':digest('/usr/lib64/libvulkan_freedreno.so')}
        runtime_files=[p for name in ('d3d12.dll','d3d12core.dll','wine','wineserver') for p in (runtime/'files').rglob(name) if p.is_file()]
        stamp['runtime_files']={str(p.relative_to(runtime)):digest(p) for p in sorted(set(runtime_files))}
        try:
            cached=json.loads(record.read_text())
            if cached.get('stamp')==stamp and cached.get('facts',{}).get('vkd3d') is True:
                self.facts=cached['facts'];return self.snapshot()
        except (OSError,ValueError):pass
        folder=self.settings/'armada-probe';folder.mkdir(parents=True,exist_ok=True)
        data=folder/'compatdata-arm64-v1';data.mkdir(exist_ok=True)
        (data/'pfx').mkdir(exist_ok=True)
        # Armada's ARM64 runtime has no default prefix template. Proton creates
        # drive_c but expects this directory before it adds the C: and Z: links.
        (data/'pfx/dosdevices').mkdir(exist_ok=True)
        output=folder/'wave-facts.json'
        if output.exists():output.unlink()
        log=folder/'vkd3d.log'
        if log.exists():log.unlink()
        env={k:v for k,v in host_environment().items() if not k.startswith(('WINE','PROTON_','DXVK_','VKD3D_','STEAM_COMPAT_','Steam','HELIXSR_','MANGOHUD'))
             and k not in ('LD_PRELOAD','VK_ICD_FILENAMES','VK_DRIVER_FILES','VK_INSTANCE_LAYERS','VK_LAYER_PATH')}
        env.update(WINEDEBUG='-all',DISPLAY=':1',PROTON_USE_ARM64='1',PROTON_LOG='0',
            WINEPREFIX=str(data/'pfx'),WINESERVER=str(runtime/'files/bin-arm64/wineserver'),
            STEAM_COMPAT_DATA_PATH=str(data),STEAM_COMPAT_CLIENT_INSTALL_PATH=str(steam),
            SteamAppId='0',SteamGameId='0',STEAM_COMPAT_APP_ID='0',VKD3D_FILTER_DEVICE_NAME='Adreno',
            VKD3D_DEBUG='info',VKD3D_LOG_FILE=str(log))
        child=None
        try:
            child=subprocess.Popen([native_root+'/usr/bin/python3',str(runtime/'proton'),'run',str(probe),'Z:'+output.as_posix()],env=env,cwd=folder,
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
            stdout,stderr=child.communicate(timeout=60)
            result=json.loads(output.read_text()) if output.is_file() else {}
            evidence=log.read_text(errors='replace') if log.is_file() else ''
            is_vkd3d='vkd3d-proton' in evidence.lower()
            ok=child.returncode==0 and result.get('ok') is True and result.get('vendor_id')==0x5143 and is_vkd3d
            self.facts={'native_arch':native_arch,'subgroup_min':result.get('wave_min'),'subgroup_max':result.get('wave_max'),
                'vkd3d':bool(ok),'native16':result.get('native16'),'device':result.get('description'),
                'reason':result.get('reason') if ok else result.get('stage') or 'Capability or vkd3d proof failed',
                'observed_at':time.time(),'probe_exit_code':child.returncode}
            if not ok:self.facts['diagnostic']=stderr.decode(errors='replace')[-1200:]
            record.write_text(json.dumps({'stamp':stamp,'facts':self.facts},indent=2))
        except Exception as exc:
            if child and child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=5)
            self.facts={'reason':'Capability query failed: '+str(exc)}
        finally:
            try:subprocess.run([str(runtime/'files/bin-arm64/wineserver'),'-k'],env=env,capture_output=True,timeout=10)
            except (OSError,subprocess.TimeoutExpired):pass
        return self.snapshot()
