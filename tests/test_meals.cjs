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
