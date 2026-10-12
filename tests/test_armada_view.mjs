import test from 'node:test';
import assert from 'node:assert/strict';
import {isDx12Candidate,eligibleGames,managedGames,selectInitialGame,statusArguments,viewGame} from '../src/armadaView.ts';
const game=(patch={})=>({id:'10',appid:'10',name:'Game',folder:'/games/Game',route:'direct',compatibility:'candidate',reasons:[],managed:false,enabled:false,legacy:false,dx12_detected:true,installation_status:{running:false,can_modify:true,can_restore:true},...patch});
const source={ready:true};
const selection={dx12:true};
test('only evidenced DX12 Steam candidates are eligible',()=>{
  assert.equal(isDx12Candidate(game()),true);
  for(const patch of [{dx12_detected:undefined,name:'DX12 Game'},{dx12_detected:false},{route:'rom'},{route:'linux'},{route:'native'},{route:null},{compatibility:'dx11'},{renderer_unsupported:true}])assert.equal(isDx12Candidate(game(patch)),false);
  for(const appid of [undefined,'','0','-1','1.5','NaN','4294967296','9007199254740993','1e2',' 1'])assert.equal(isDx12Candidate(game({appid})),false);
  assert.equal(isDx12Candidate(game({appid:'4294967295',route:'optiscaler'})),true);
});
test('candidate sorting is deterministic and managed recovery remains separate',()=>{
  const items=[game({id:'b',name:'Z'}),game({id:'c',name:'A'}),game({id:'a',name:'A'}),game({id:'old',dx12_detected:false,managed:true}),game({id:'recover',route:null,recovery_available:true}),game({id:'legacy',compatibility:'unknown',legacy:true})];
  assert.deepEqual(eligibleGames(items).map(g=>g.id),['a','c','b']);
  assert.deepEqual(managedGames(items).map(g=>g.id),['old','recover','legacy']);
  assert.equal(items[0].id,'b');
});
test('initial selection prioritizes preferred, running, managed and sorted candidate',()=>{
  const items=[game({id:'managed',managed:true,name:'Z'}),game({id:'running',installation_status:{running:true},name:'Y'}),game({id:'first',name:'A'})];
  assert.equal(selectInitialGame(items,'first'),'first');
  assert.equal(selectInitialGame(items,'missing'),'running');
  assert.equal(selectInitialGame(items.slice(0,1)),'managed');
  assert.equal(selectInitialGame([items[2]]),'first');
  assert.equal(selectInitialGame([game({dx12_detected:false})]),'');
});
test('status arguments accept exact scanned unmanaged proxy choice only',()=>{
  const proxy=game({route:'optiscaler',executable_choices:[{path:'/games/Game/main.exe',dx12:true}]});
  assert.deepEqual(statusArguments(proxy,'/games/Game/main.exe'),['10','/games/Game/main.exe']);
  for(const item of [game(),{...proxy,managed:true}])assert.deepEqual(statusArguments(item,'/games/Game/main.exe'),['10']);
  assert.deepEqual(statusArguments(proxy,'main.exe'),['10']);
});
test('loading and unavailable source prevent new changes',()=>{
  assert.equal(viewGame(undefined,source,selection).primary,null);
  for(const src of [undefined,{ready:false,reason:'Missing local payload'}]){
    const view=viewGame(game(),src,selection);assert.equal(view.primary.enabled,false);assert.match(view.title,/source/i);
  }
});
test('running status disables every file and launch action, even recovery',()=>{
  const view=viewGame(game({managed:true,enabled:true,recovery_available:true,installation_status:{running:true,can_restore:true}}),source,selection);
  assert.equal(view.primary.enabled,false);assert.equal(view.toggle.enabled,false);assert.equal(view.canRemove,false);assert.equal(view.canRecover,false);assert.match(view.nextStep,/Close.*refresh/);
});
test('recovery is available despite unsupported renderer and missing source',()=>{
  const view=viewGame(game({dx12_detected:false,recovery_available:true,installation_status:{running:false,can_modify:false}}),{ready:false},selection);
  assert.equal(view.primary.action,'recover');assert.equal(view.primary.enabled,true);assert.equal(view.canRecover,true);
});
test('restore controls are independent from install compatibility and source',()=>{
  const enabled=game({managed:true,enabled:true});
  for(const src of [{ready:false}]){
    const view=viewGame(enabled,src,selection);assert.equal(view.primary.action,'disable');assert.equal(view.primary.enabled,true);assert.equal(view.canRemove,true);
  }
  const loading=viewGame(enabled,undefined,selection);
  assert.equal(loading.primary.enabled,false);assert.equal(loading.toggle.enabled,false);assert.equal(loading.canRemove,false);
  const blocked=viewGame({...enabled,installation_status:{running:false,can_restore:false}},source,selection);
  assert.equal(blocked.primary.enabled,false);assert.equal(blocked.toggle.enabled,false);assert.equal(blocked.canRemove,false);
  const unavailable=viewGame({...enabled,dx12_detected:false},source,selection);
  assert.equal(unavailable.primary.action,'remove');assert.equal(unavailable.primary.enabled,true);
  const disabled=viewGame({...enabled,enabled:false,dx12_detected:false},source,selection);
  assert.equal(disabled.toggle.enabled,false);
});
test('blocking issues and modification refusal block install but preserve restore',()=>{
  const installation_status={running:false,can_modify:false,can_restore:true,issues:[{code:'fault',title:'Review files',reason:'Unexpected file',steps:['Check files.'],blocking:true}]};
  assert.equal(viewGame(game({installation_status}),source,selection).primary.enabled,false);
  const view=viewGame(game({managed:true,enabled:true,installation_status}),source,selection);
  assert.equal(view.primary.enabled,true);assert.equal(view.title,'Review files');assert.equal(view.canRemove,true);
});
test('action identity and renderer/executable requirements are explicit',()=>{
  for(const [patch,action] of [[{},'install'],[{legacy:true},'adopt'],[{managed:true},'enable'],[{managed:true,enabled:true},'disable']])assert.equal(viewGame(game(patch),source,selection).primary.action,action);
  const proxy=game({route:'optiscaler',executable_selection_needed:true,dx12_confirmation_needed:true,executable_choices:[{path:'/game/main.exe',dx12:true},{path:'/game/dx11.exe',dx12:false}]});
  assert.equal(viewGame(proxy,source,selection).needsExecutable,true);
  assert.equal(viewGame(proxy,source,{dx12:false,executable:'/game/dx11.exe'}).primary.enabled,false);
  assert.equal(viewGame(proxy,source,{dx12:true,executable:'/game/dx11.exe'}).primary.enabled,true);
  assert.equal(viewGame(proxy,source,{dx12:false,executable:'/game/main.exe'}).primary.enabled,false);
  assert.equal(viewGame(proxy,source,{dx12:true,executable:'/game/main.exe'}).primary.enabled,true);
  assert.equal(viewGame({...proxy,managed:true},source,selection).needsExecutable,false);
  assert.match(viewGame(game(),source,selection).nextStep,/AMD FSR/);
  assert.match(viewGame(proxy,source,{dx12:true,executable:'/game/main.exe'}).nextStep,/proxy/);
  assert.match(viewGame(game({gameplay_warning:'Flashing remains unresolved.'}),source,selection).detail,/Flashing remains unresolved/);
});
test('only running and executable-selection blockers keep evidenced DX12 games visible',()=>{
  const issue=code=>({code,title:code,reason:code,steps:[],blocking:true});
  for(const codes of [['game_running'],['executable_selection'],['game_running','executable_selection']]){
    const item=game({compatibility:'blocked',installation_status:{running:codes.includes('game_running'),can_modify:false,issues:codes.map(issue)}});
    assert.equal(isDx12Candidate(item),true);assert.equal(eligibleGames([item]).length,1);
    assert.equal(viewGame(item,source,selection).primary.enabled,false);
    assert.equal(isDx12Candidate({...item,dx12_detected:false}),false);
    assert.equal(isDx12Candidate({...item,renderer_unsupported:true}),false);
    assert.equal(isDx12Candidate({...item,route:'native'}),false);
  }
  for(const codes of [[],['anti_cheat'],['game_running','build_unsupported'],['executable_selection','hash_mismatch']]){
    assert.equal(isDx12Candidate(game({compatibility:'blocked',installation_status:{running:false,issues:codes.map(issue)}})),false);
  }
});
test('unknown modification and restore permissions fail closed',()=>{
  for(const installation_status of [undefined,{running:false}]){
    assert.equal(viewGame(game({installation_status}),source,selection).primary.enabled,false);
    const enabled=viewGame(game({managed:true,enabled:true,installation_status}),{ready:false},selection);
    assert.equal(enabled.primary.enabled,false);assert.equal(enabled.toggle.enabled,false);assert.equal(enabled.canRemove,false);
  }
  const dynamic=game({route:'optiscaler',executable_selection_needed:true,executable_choices:[{path:'dynamic.exe',dx12:false}]});
  assert.equal(viewGame(dynamic,source,{dx12:false,executable:'dynamic.exe'}).primary.enabled,false);
  assert.equal(viewGame(dynamic,source,{dx12:true,executable:'dynamic.exe'}).primary.enabled,true);
  assert.equal(viewGame(dynamic,source,{dx12:true,executable:'unscanned.exe'}).primary.enabled,false);
  assert.equal(viewGame({...dynamic,dx12_detected:false},source,{dx12:true,executable:'dynamic.exe'}).primary.enabled,false);
});
