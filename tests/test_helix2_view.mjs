import test from 'node:test';
import assert from 'node:assert/strict';
import {availableActions,changedOptions} from '../src/helix2View.ts';

test('unknown, busy and blocked states expose no mutation actions',()=>{
  assert.deepEqual(availableActions(),[]);
  const state={running:true,can_modify:true,actions:['enable','settings']};
  assert.deepEqual(availableActions(state),[]);
  assert.deepEqual(availableActions({...state,running:false,can_modify:false}),[]);
  assert.deepEqual(availableActions({...state,running:false,actions:['recover','arbitrary']}),['recover']);
});
test('only changed supported settings enter the mutation payload',()=>{
  assert.deepEqual(changedOptions({Int8:'on',WaveSize:'auto'},{Int8:'on',WaveSize:'64',unsafe:'yes'}),{WaveSize:'64'});
  assert.deepEqual(changedOptions({Int8:'on'},{}),{});
});
