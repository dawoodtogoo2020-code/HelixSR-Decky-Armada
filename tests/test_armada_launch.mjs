import test from 'node:test';
import assert from 'node:assert/strict';
import {armadaOptions,restoreArmadaOptions} from '../src/armadaLaunch.ts';
import {proxyOptions} from '../src/launchOptions.ts';
const env={PROTON_USE_ARM64:'1',VKD3D_SHADER_OVERRIDE:'Z:/var/home/armada/Game Mod Files/HelixSR-Decky-Armada/packages/v762/shader-override'};
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
