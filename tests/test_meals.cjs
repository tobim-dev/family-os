const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('successful login followed by failed sync retries only reading and clears password', async () => {
  let operation;
  const calls = [];
  const fields = {
    form: {},
    '#cook-password': {value:'example-password',disabled:false},
    '#cook-email': {value:'example@example.org',disabled:false},
    '[type=submit]': {textContent:'Verbinden und Planung laden'}
  };
  let failSync = true;
  const context = vm.createContext({
    dialog(){}, modal:{querySelector: key=>fields[key]},
    api:async (path,body)=>{calls.push({path,body});if(path==='/meals/sync'&&failSync)throw new Error('Diagnostic test');return {connected:true};}
  });
  vm.runInContext(fs.readFileSync('static/meals.js','utf8'),context);
  context.mealSubmit = (form,fn)=>{operation=fn;};
  context.mealConnection();
  await assert.rejects(operation({email:'example@example.org',password:'example-password'}), /Anmeldung wurde bestätigt/);
  assert.equal(fields['#cook-password'].value,'');
  assert.equal(fields['#cook-password'].disabled,true);
  assert.equal(fields['[type=submit]'].textContent,'Planung erneut laden');
  failSync=false;
  await operation({});
  assert.deepEqual(calls.map(c=>c.path),['/meals/connect','/meals/sync','/meals/sync']);
});

test('failed login does not request calendar or discard credential inputs', async () => {
  let operation;
  const calls=[];
  const context=vm.createContext({dialog(){},modal:{querySelector:()=>({})},api:async path=>{calls.push(path);throw new Error('Login failed');}});
  vm.runInContext(fs.readFileSync('static/meals.js','utf8'),context);
  context.mealSubmit=(form,fn)=>{operation=fn;};
  context.mealConnection();
  await assert.rejects(operation({email:'example@example.org',password:'example'}), /Login failed/);
  assert.deepEqual(calls,['/meals/connect']);
});

function weekSwitchContext(api) {
  let counter = 0;
  const context = vm.createContext({api, crypto: {randomUUID: () => 'id-' + (++counter)}});
  vm.runInContext(fs.readFileSync('static/meals.js', 'utf8'), context);
  vm.runInContext("mealStart = '2026-10-31'; mealState = {revision: 'rev-0'};", context);
  return context;
}

test('week switch removes before adding and follows only selected recipes', () => {
  const context = weekSwitchContext(async () => ({}));
  const form = new Map([['remove', ['r1']], ['add', ['r3', 'r2']]]);
  const data = {getAll: key => form.get(key) || []};
  const plan = {remove: [{id: 'r1', name: 'Alt'}, {id: 'r4', name: 'Behalten'}], add: [{id: 'r2', name: 'B'}, {id: 'r3', name: 'C'}]};
  const steps = context.weekSwitchSteps(data, plan);
  assert.deepEqual(JSON.parse(JSON.stringify(steps)), [
    {action: 'ingredients_remove', id: 'r1', name: 'Alt'},
    {action: 'ingredients_add', id: 'r3', name: 'C'},
    {action: 'ingredients_add', id: 'r2', name: 'B'},
  ]);
});

test('week switch uses the latest revision per step and stops at the first failure', async () => {
  const calls = [];
  const context = weekSwitchContext(async (path, body) => {
    calls.push(body);
    if (calls.length === 2) throw new Error('Cookidoo-Ergebnis muss geprüft werden.');
    return {revision: 'rev-' + calls.length};
  });
  const steps = [
    {action: 'ingredients_remove', id: 'r1', name: 'Alt'},
    {action: 'ingredients_add', id: 'r2', name: 'Neu'},
    {action: 'ingredients_add', id: 'r3', name: 'Nie'},
  ];
  const result = await context.runWeekSwitch(steps);
  assert.equal(result.done, 1);
  assert.equal(result.failed.id, 'r2');
  assert.match(result.error.message, /geprüft/);
  assert.deepEqual(calls.map(c => [c.action, c.recipe_id, c.revision]), [
    ['ingredients_remove', 'r1', 'rev-0'],
    ['ingredients_add', 'r2', 'rev-1'],
  ]);
  assert.notEqual(calls[0].id, calls[1].id);
});
