const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function context(user) {
  const ctx = vm.createContext({URLSearchParams, esc: s => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;')});
  vm.runInContext(fs.readFileSync('static/outlook.js', 'utf8'), ctx);
  vm.runInContext(`var state = {user: ${JSON.stringify(user)}};`, ctx);
  return ctx;
}

const block = {title: 'Lina abholen', start_local: '2027-03-29T15:45:00', end_local: '2027-03-29T17:30:00',
               start_utc: '2027-03-29T13:45:00Z', end_utc: '2027-03-29T15:30:00Z'};

test('app link uses local time, web link uses UTC, text is encoded', () => {
  const links = context('britta').outlookLinks(block);
  const app = new URL(links.app);
  assert.equal(links.app, 'ms-outlook://events/new?title=Lina%20abholen&start=2027-03-29T15:45:00&end=2027-03-29T17:30:00');
  assert.equal(app.protocol, 'ms-outlook:');
  assert.equal(app.searchParams.get('title'), 'Lina abholen');
  assert.equal(app.searchParams.get('start'), '2027-03-29T15:45:00');
  assert.equal(app.searchParams.get('end'), '2027-03-29T17:30:00');
  const web = new URL(links.web);
  assert.equal(web.host, 'outlook.office.com');
  assert.equal(web.searchParams.get('subject'), 'Lina abholen');
  assert.equal(web.searchParams.get('startdt'), '2027-03-29T13:45:00Z');
  assert.equal(web.searchParams.get('rru'), 'addevent');
  assert.equal(web.searchParams.get('path'), '/calendar/action/compose');
  assert.doesNotMatch(links.web, /\+/);
  assert.equal([...web.searchParams.keys()].sort().join(','), 'enddt,path,rru,startdt,subject');  // nothing else leaves
});

test('bundled task lists every entry; buttons only for own entries to add', () => {
  const task = {owner: 'britta', calendar_items: [
    {id: 4, action: 'add', label: 'Mo 29.03. Lina abholen 15:30–17:30', calendar_block: block},
    {id: 7, action: 'remove', label: 'Di 30.03. Lina bringen 07:45–08:45'}]};
  const mine = context('britta').outlookActions(task);
  assert.equal((mine.match(/In Outlook eintragen/g) || []).length, 1);
  assert.match(mine, /Entfernen<\/span>\s*<span>Di 30\.03\./);
  const other = context('tobi').outlookActions(task);
  assert.match(other, /Mo 29\.03\./);
  assert.doesNotMatch(other, /In Outlook eintragen/);
  assert.equal(context('britta').outlookActions({owner: 'britta'}), '');
  assert.deepEqual(JSON.parse(JSON.stringify(context('britta').workCalendarUpto(task))), {upto: 7});
});
