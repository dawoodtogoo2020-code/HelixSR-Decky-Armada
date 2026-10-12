import test from 'node:test';
import assert from 'node:assert/strict';
import {createArmadaClient} from '../src/armadaClient.ts';
import {armadaOptions} from '../src/armadaLaunch.ts';
const env={PROTON_USE_ARM64:'1',VKD3D_SHADER_OVERRIDE:'Z:/var/home/armada/Game Mod Files/HelixSR-Decky-Armada/packages/v762/shader-override'};
const addon={helper:'/var/home/armada/.local/share/Steam/steamapps/common/PRAGMATA Mod Files/Combined-Helix-LSFG-20261012/pragmata-combined-launch.py',sha256:'f08628ec276495e8402f69651a1314bc1ab50b57dc36c280d5f2f3fa32d0c205',environment:{ENABLE_GAMESCOPE_WSI:'0'}};
const game=(patch={})=>({id:'10',appid:'10',name:'Synthetic',folder:'/games/Synthetic',route:'direct',compatibility:'candidate',reasons:[],managed:true,enabled:false,legacy:false,dx12_detected:true,...patch});
const preview={token:'review-token',action:'enable',name:'Synthetic',warning:'',files:[],launch_environment:env};
const change=(action='enable',patch={})=>({game:game(),selection:{dx12:true},action,preview:{...preview,...patch}});
function fixture({options='%command%',receipt=null,status=game(),readback,hook}={}){
  const events=[];let current=options;let unregisters=0;
  const rpc=async(method,...args)=>{
    events.push([method,...args]);
    if(hook){const value=await hook(method,args);if(value!==undefined)return value;}
    if(method==='armada_status')return status;
    if(method==='owned_launch_options')return receipt;
    if(method==='armada_preview')return {...preview,action:'armada-adopt'};
    if(method==='prepare_launch_options')return {nonce:'nonce-1'};
    if(method==='armada_execute')return {message:'Files changed'};
    return null;
  };
  const steam={RegisterForAppDetails(id,cb){events.push(['read',id]);cb({strLaunchOptions:current});return {unregister(){unregisters++;}};},SetAppLaunchOptions(id,value){events.push(['write',id,value]);current=readback===undefined?value:readback;}};
  return {client:createArmadaClient(rpc,steam,20),events,get options(){return current;},get unregisters(){return unregisters;}};
}
test('read waits for a string, unregisters once and handles synchronous callbacks',async()=>{
  let count=0;
  const client=createArmadaClient(async()=>null,{RegisterForAppDetails(id,cb){cb({});cb({strLaunchOptions:2});cb({strLaunchOptions:'ok'});cb({strLaunchOptions:'late'});return {unregister(){count++;}};},SetAppLaunchOptions(){assert.fail('unexpected write');}},20);
  assert.equal(await client.readLaunchOptions(10),'ok');assert.equal(count,1);
});
test('read timeout unregisters exactly once',async()=>{
  let count=0;
  const client=createArmadaClient(async()=>null,{RegisterForAppDetails(){return {unregister(){count++;}};},SetAppLaunchOptions(){}},5);
  await assert.rejects(client.readLaunchOptions(10),/Steam did not return/);assert.equal(count,1);
});
test('invalid app IDs reject before RPC or Steam actions',async()=>{
  for(const appid of ['', '0','-1','1.5','4294967296','9007199254740993']){
    const f=fixture();await assert.rejects(f.client.prepareAction(game({appid}),{dx12:true},'enable'),/valid Steam/);assert.deepEqual(f.events,[]);
  }
  const f=fixture();await assert.rejects(f.client.readLaunchOptions(0),/valid Steam/);assert.deepEqual(f.events,[]);
});
test('synchronous operation lock rejects overlapping prepare, apply and repair',async()=>{
  let release;const gate=new Promise(resolve=>{release=resolve;});
  const f=fixture({hook:async method=>{if(method==='armada_preview'){await gate;return preview;}}});
  const first=f.client.prepareAction(game(),{dx12:true},'enable');
  await assert.rejects(f.client.prepareAction(game(),{dx12:true},'enable'),/in progress/);
  await assert.rejects(f.client.applyPreview(change()),/in progress/);
  await assert.rejects(f.client.repairLaunch(game()),/in progress/);
  release();await first;assert.equal(f.events.length,1);
});
test('adopt prepares before preview and retains original public action',async()=>{
  const f=fixture();const prepared=await f.client.prepareAction(game({legacy:true,managed:false}),{dx12:true},'adopt');
  assert.deepEqual(f.events.map(e=>e[0]),['armada_prepare','armada_preview']);assert.equal(prepared.action,'adopt');assert.equal(prepared.preview.action,'armada-adopt');
  await f.client.applyPreview(prepared);assert.ok(f.events.some(e=>e[0]==='prepare_launch_options'));
});
test('enable merges fresh unrelated options and pinned addon, verifies before execution',async()=>{
  const before='MANGOHUD=1 /usr/libexec/armada/armada-game-launch %command% --user-argument';
  const f=fixture({options:before});await f.client.applyPreview(change('enable',{launch_addon:addon}));
  assert.ok(f.options.includes('MANGOHUD=1'));assert.ok(f.options.includes(addon.helper));assert.ok(f.options.endsWith('%command% --user-argument'));
  assert.equal(f.events[0][0],'armada_status');
  assert.ok(f.events.findIndex(e=>e[0]==='finalize_launch_options')<f.events.findIndex(e=>e[0]==='armada_execute'));
  assert.deepEqual(f.events.find(e=>e[0]==='armada_execute'),['armada_execute','review-token',f.options]);
});
test('fresh running state refuses file and launch actions',async()=>{
  for(const action of ['enable','disable','remove','recover']){
    const f=fixture({status:game({installation_status:{running:true}})});
    await assert.rejects(f.client.applyPreview(change(action)),/Close the game/);assert.deepEqual(f.events.map(e=>e[0]),['armada_status']);
  }
});
test('wrong Steam readback preserves pending receipt and never executes files',async()=>{
  const f=fixture({readback:'unexpected'});await assert.rejects(f.client.applyPreview(change()),/pending receipt/);
  assert.ok(f.events.some(e=>e[0]==='prepare_launch_options'));assert.equal(f.events.some(e=>e[0]==='finalize_launch_options'||e[0]==='armada_execute'),false);
});
test('unchanged options skip receipt preparation and Steam writes',async()=>{
  const options=armadaOptions('%command%',env,false);const f=fixture({options});await f.client.applyPreview(change());
  assert.equal(f.events.some(e=>e[0]==='prepare_launch_options'||e[0]==='write'),false);assert.ok(f.events.some(e=>e[0]==='armada_execute'));
});
test('disable captures addon before execution and restores afterwards; remove restores afterwards',async()=>{
  const before='MANGOHUD=1 %command%';const after=armadaOptions(before,env,false);
  for(const action of ['disable','remove']){
    const f=fixture({options:after,receipt:{before,after}});await f.client.applyPreview(change(action));
    assert.equal(f.options,before);const execute=f.events.findIndex(e=>e[0]==='armada_execute');const write=f.events.findIndex(e=>e[0]==='write');assert.ok(execute<write);
    if(action==='disable')assert.ok(f.events.findIndex(e=>e[0]==='remember_launch_addon')<execute);
  }
});
test('recover makes no Steam reads/writes; missing restore receipt preserves user options',async()=>{
  const recovery=fixture();await recovery.client.applyPreview(change('recover'));assert.deepEqual(recovery.events.map(e=>e[0]),['armada_status','armada_execute']);
  const f=fixture({options:'MANGOHUD=1 %command%'});const result=await f.client.applyPreview(change('remove'));
  assert.equal(f.options,'MANGOHUD=1 %command%');assert.match(result.message,/no owned launch receipt/);assert.equal(f.events.some(e=>e[0]==='write'),false);
});
test('pending repair resumes only exact before/after with fresh verified readback',async()=>{
  const pending={before:'%command%',after:armadaOptions('%command%',env,false),restore:false,nonce:'pending-nonce'};
  for(const options of [pending.before,pending.after]){
    const f=fixture({options,receipt:{before:pending.before,after:pending.after,pending}});await f.client.repairLaunch(game());
    assert.equal(f.options,pending.after);assert.deepEqual(f.events.find(e=>e[0]==='finalize_launch_options'),['finalize_launch_options','10','pending-nonce',pending.after]);
    assert.equal(f.events.filter(e=>e[0]==='read').length,2);assert.equal(f.events.some(e=>e[0]==='prepare_launch_options'||e[0]==='armada_execute'),false);
  }
  const f=fixture({options:'edited',receipt:{before:pending.before,after:pending.after,pending}});
  await assert.rejects(f.client.repairLaunch(game()),/do not match/);assert.equal(f.events.some(e=>e[0]==='write'||e[0]==='finalize_launch_options'),false);
});
test('pending direction mismatch blocks apply and active enabled restore is refused',async()=>{
  const pending={before:'%command%',after:'original',restore:true,nonce:'pending-nonce'};
  const f=fixture({receipt:{before:'original',after:'%command%',pending}});
  await assert.rejects(f.client.applyPreview(change()),/interrupted/);assert.equal(f.events.some(e=>e[0]==='write'||e[0]==='armada_execute'),false);
  for(const receipt of [{before:'original',after:'%command%'},{before:'original',after:'%command%',pending}]){
    const active=fixture({receipt,status:game({enabled:true})});await assert.rejects(active.client.repairLaunch(game()),/Use original first/);assert.equal(active.events.some(e=>e[0]==='write'||e[0]==='finalize_launch_options'),false);
  }
});
test('repair refuses pending readback mismatch without finalizing',async()=>{
  const pending={before:'%command%',after:armadaOptions('%command%',env,false),restore:false,nonce:'pending-nonce'};
  const f=fixture({receipt:{before:pending.before,after:pending.after,pending},readback:'changed'});
  await assert.rejects(f.client.repairLaunch(game()),/pending receipt/);assert.equal(f.events.some(e=>e[0]==='finalize_launch_options'),false);
});
