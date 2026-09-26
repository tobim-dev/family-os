const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function context(user, closures, joint = false) {
  const ctx = vm.createContext({
    esc: s => String(s), names: {tobi: 'Tobi', britta: 'Britta'}, icon: () => '',
    fmt: d => d, jointMode: () => joint,
  });
  vm.runInContext(fs.readFileSync('static/closures.js', 'utf8'), ctx);
  vm.runInContext(`var state = ${JSON.stringify({user, closures})};`, ctx);
  return ctx;
}

const pending = [
  {day: '2026-10-05', kind: 'vacation', batch: 'a', state: 'pending', creator: 'tobi', note: ''},
  {day: '2026-10-06', kind: 'vacation', batch: 'a', state: 'pending', creator: 'tobi', note: ''},
  {day: '2026-10-09', kind: 'closed', batch: 'b', state: 'confirmed', creator: 'britta', note: ''},
];

test('entries are grouped per batch', () => {
  const batches = context('tobi', pending).closureBatches();
  assert.deepEqual(JSON.parse(JSON.stringify(batches.map(b => [b.batch, b.days.length]))), [['a', 2], ['b', 1]]);
});

test('only the other person confirms; the creator can withdraw; confirmed can be lifted', () => {
  const [mine, confirmed] = context('tobi', pending).closureBatches();
  const asTobi = context('tobi', pending);
  assert.match(asTobi.closureActions(mine), /withdraw/);
  assert.doesNotMatch(asTobi.closureActions(mine), /confirm/);
  const asBritta = context('britta', pending);
  assert.match(asBritta.closureActions(mine), /data-closure-action="confirm"/);
  assert.match(asBritta.closureActions(mine), /reject/);
  assert.match(asTobi.closureActions(confirmed), /lift/);
  assert.match(context('tobi', pending, true).closureActions(mine), /confirm/);  // joint mode
});

test('only confirmed days suspend assignments', () => {
  const ctx = context('tobi', pending);
  assert.equal(ctx.confirmedClosure('2026-10-05'), null);
  assert.equal(ctx.confirmedClosure('2026-10-09').kind, 'closed');
  assert.match(ctx.closureBadge('2026-10-05'), /Urlaub · offen/);
});
