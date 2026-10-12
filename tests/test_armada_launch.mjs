import test from 'node:test';
import assert from 'node:assert/strict';
import {armadaOptions,restoreArmadaOptions} from '../src/armadaLaunch.ts';
import {proxyOptions} from '../src/launchOptions.ts';
const env={PROTON_USE_ARM64:'1',VKD3D_SHADER_OVERRIDE:'Z:/var/home/armada/Game Mod Files/HelixSR-Decky-Armada/packages/v762/shader-override'};
const addon={helper:'/var/home/armada/.local/share/Steam/steamapps/common/PRAGMATA Mod Files/Combined-Helix-LSFG-20261012/pragmata-combined-launch.py',sha256:'f08628ec276495e8402f69651a1314bc1ab50b57dc36c280d5f2f3fa32d0c205',environment:{ENABLE_GAMESCOPE_WSI:'0'}};
test('empty and argument-only options retain a separate Steam command',()=>{
  assert.ok(armadaOptions('',env,false).endsWith('%command%'));
  assert.ok(armadaOptions('--launcher-skip',env,false).endsWith('%command% --launcher-skip'));
});
test('literal wrappers and unrelated environment survive',()=>{
  const before='MESA_VK_WSI_PRESENT_MODE=mailbox /usr/libexec/armada/armada-game-launch %command% --launcher-skip';
  const after=armadaOptions(before,env,false);assert.ok(after.includes('MESA_VK_WSI_PRESENT_MODE=mailbox /usr/libexec/armada/armada-game-launch /usr/bin/env '));
  assert.ok(after.endsWith('%command% --launcher-skip'));
  assert.equal(armadaOptions(after,env,false),after);
  assert.equal(restoreArmadaOptions(after,{before,after}),before);
});
test('OptiScaler override is merged and then restored exactly',()=>{
  const before='WINEDLLOVERRIDES="version=n,b" %command%';
  const after=armadaOptions(before,env,true,proxyOptions);assert.ok(after.includes('version=n,b;dxgi=n,b'));
  assert.equal(restoreArmadaOptions(after,{before,after}),before);
});
test('conflicting or executable shell options fail closed',()=>{
  for(const before of ["PROTON_USE_ARM64=0 %command%","VKD3D_SHADER_OVERRIDE='Z:/other' %command%",'%command% && evil','X=$(evil) %command%','%command% %command%','"%command%"'])
    assert.throws(()=>armadaOptions(before,env,false));
  assert.throws(()=>restoreArmadaOptions('edited',{before:'',after:'owned'}));
});

test('combined helper survives re-enable while current user options are retained',()=>{
  const original='/usr/libexec/armada/armada-game-launch %command%';
  const combined=armadaOptions(original,env,false,undefined,addon);
  assert.equal(restoreArmadaOptions(combined,{before:original,after:combined}),original);
  const current='MANGOHUD=1 '+original+' --new-user-argument';
  const reenabled=armadaOptions(current,env,false,undefined,addon);
  assert.ok(reenabled.includes(`MANGOHUD=1 /usr/bin/python3 '${addon.helper}' /usr/libexec/armada/armada-game-launch`));
  assert.ok(reenabled.includes('ENABLE_GAMESCOPE_WSI=0'));
  assert.ok(reenabled.endsWith('%command% --new-user-argument'));
  assert.equal(armadaOptions(reenabled,env,false,undefined,addon),reenabled);
  assert.equal(restoreArmadaOptions(reenabled,{before:current,after:reenabled}),current);
});

test('combined helper conflicts and misplaced wrappers are refused',()=>{
  const wrapper='/usr/libexec/armada/armada-game-launch';
  for(const current of [
    `ENABLE_GAMESCOPE_WSI=1 ${wrapper} %command%`,
    `ENABLE_GAMESCOPE_WSI=0 ENABLE_GAMESCOPE_WSI=0 ${wrapper} %command%`,
    `${wrapper} %command% ENABLE_GAMESCOPE_WSI=0`,
    `${wrapper} ${wrapper} %command%`,
    '%command%',
    `/usr/bin/python3 '/other/pragmata-combined-launch.py' ${wrapper} %command%`,
    `/usr/bin/python3 '${addon.helper}' %command% ${wrapper}`,
    `/usr/bin/python3 '/other/helper.py' ${wrapper} %command%`,
  ])assert.throws(()=>armadaOptions(current,env,false,undefined,addon));
  for(const invalid of [{...addon,sha256:'0'.repeat(64)},{...addon,helper:'/other/pragmata-combined-launch.py'},{...addon,environment:{ENABLE_GAMESCOPE_WSI:'1'}}])
    assert.throws(()=>armadaOptions(`${wrapper} %command%`,env,false,undefined,invalid));
});
