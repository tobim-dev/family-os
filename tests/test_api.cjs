const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
// Exercise the actual browser API helper without a DOM or external requests.
const source = fs.readFileSync('static/app.js','utf8');
const helper = source.slice(source.indexOf('async function api('), source.indexOf('\nfunction toast('));
function client(response){
  const context={fetch:async()=>response,state:{user:'tobi'},loginShown:false};
  context.renderLogin=()=>{context.loginShown=true;};
  vm.createContext(context);vm.runInContext(helper,context);return context;
}
test('plain-text server errors show actionable text instead of JSON parser errors',async()=>{
  const c=client(new Response('Internal Server Error',{status:500}));
  await assert.rejects(c.api('/proposals',{}),/HTTP 500.*Stand prüfen/);
});
test('structured missing-partner explanation is preserved',async()=>{
  const c=client(Response.json({detail:'Bitte zuerst Brittas Konto einrichten.'},{status:409}));
  await assert.rejects(c.api('/proposals',{}),/Brittas Konto/);
});
test('expired session returns to login even if a proxy sends HTML',async()=>{
  const c=client(new Response('<html>Unauthorized</html>',{status:401}));
  await assert.rejects(c.api('/state'),/HTTP 401/);
  assert.equal(c.state,null);assert.equal(c.loginShown,true);
});
test('valid responses remain unchanged',async()=>{
  const c=client(Response.json({id:42}));
  assert.equal((await c.api('/proposals',{})).id,42);
});
