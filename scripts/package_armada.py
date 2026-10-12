"""Build an Armada plugin without any private HelixSR network or shader payload."""
from pathlib import Path
import hashlib,json,zipfile
root=Path(__file__).resolve().parents[1]
version=json.loads((root/'package.json').read_text())['version']
out=root.parent/f'HelixSR-Decky-Armada-{version}.zip'
names=['main.py','armada_main.py','plugin.json','package.json','LICENSE','README.md','ARMADA_INSTALL.md','RELEASE_STATUS.md',
       'THIRD_PARTY_NOTICES.md','bin/wave_probe.exe','bin/wave_probe.cpp','bin/README.md','dist/index.js']
names += [p.relative_to(root).as_posix() for p in (root/'py_modules').glob('*.py')]
names += ['licenses/'+n for n in ('CC-BY-4.0.txt','COPYING.MinGW-w64-runtime.txt','cpython-3.11.17-LICENSE.txt','cpython-3.11.17-PROVENANCE.json','decky-api-LGPL-2.1.txt','font-awesome-free-5-LICENSE.txt','react-icons-LICENSE.txt')]
names += [p.relative_to(root).as_posix() for p in (root/'licenses/decky-api-1.1.3-source').rglob('*') if p.is_file()]
for name in names:
 p=root/name
 if p.is_symlink() or not p.is_file():raise SystemExit('Missing or unsafe file: '+name)
 if p.suffix.lower() in ('.spv','.pak','.bin','.dll'):raise SystemExit('Private payload cannot enter plugin: '+name)
 if p.suffix.lower()=='.exe' and name!='bin/wave_probe.exe':raise SystemExit('Unexpected executable')
if hashlib.sha256((root/'bin/wave_probe.exe').read_bytes()).hexdigest()!='d96c97b0b280722f72c86d62f2b8ce43c49019318077c2a268b69a82acc4135d':raise SystemExit('Probe changed')
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
 for name in sorted(set(names)):z.write(root/name,'HelixSR-Decky-Armada/'+name)
with zipfile.ZipFile(out) as z:
 if z.testzip() is not None:raise SystemExit('ZIP integrity failure')
 if set(z.namelist())!={'HelixSR-Decky-Armada/'+name for name in names}:raise SystemExit('ZIP allowlist failure')
receipt={'path':str(out),'size':out.stat().st_size,'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'files':sorted(names),'private_payload_included':False}
out.with_suffix('.zip.sha256').write_text(receipt['sha256']+'  '+out.name+'\n')
out.with_suffix('.manifest.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({k:v for k,v in receipt.items() if k!='files'}))
