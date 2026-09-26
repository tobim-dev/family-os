const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

// Minimal stand-in for the Scriptable API: records texts and layout calls.
function scriptable({response, status = 200, cached = null, family = 'medium'}) {
  const texts = [];
  const files = {cache: cached};
  class Stack {
    addStack() { return new Stack(); }
    addText(text) { texts.push(text); return {}; }
    addImage() { return {}; }
    addSpacer() {}
    layoutVertically() {}
    centerAlignContent() {}
    setPadding() {}
  }
  class ListWidget extends Stack {
    async presentMedium() {}
  }
  class Request {
    constructor(url) { this.url = url; this.response = {statusCode: status}; }
    async loadJSON() {
      Request.last = this;
      if (response instanceof Error) throw response;
      return response;
    }
  }
  const context = {
    ListWidget, Request, texts,
    Color: Object.assign(function Color() {}, {dynamic: () => ({})}),
    Font: {systemFont: () => ({}), boldSystemFont: () => ({})},
    Size: function Size() {},
    SFSymbol: {named: () => ({image: {}})},
    FileManager: {local: () => ({
      joinPath: (a, b) => a + '/' + b,
      documentsDirectory: () => '/docs',
      fileExists: () => files.cache !== null,
      readString: () => files.cache,
      writeString: (_, value) => { files.cache = value; },
    })},
    config: {runsInWidget: true, widgetFamily: family},
    Script: {setWidget(widget) { context.widget = widget; }, complete() {}},
    files,
  };
  return context;
}

async function run(context) {
  const source = fs.readFileSync('static/scriptable/family-os-widget.js', 'utf8')
    .replace('__FOS_ORIGIN__', 'https://fos.example').replace('__FOS_KEY__', 'fosw_test');
  vm.createContext(context);
  await vm.runInContext(`(async () => {${source}\n})()`, context);
  return context;
}

function day(offset) {
  const date = new Date(Date.now() + offset * 86400000);
  const pad = number => String(number).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

const sample = () => ({
  user: 'Tobi', generated: day(0) + 'T07:30:00+02:00', tasks: 2, task_titles: ['Windeln kaufen', 'Nanny anfragen'],
  approvals: 1, issues: 0,
  days: [
    {day: day(0), closure: null, bring: 'Tobi', pickup: 'Britta', nanny: [], dinner: 'Linsencurry'},
    {day: day(1), closure: 'Feiertag', bring: null, pickup: null, nanny: ['16:00–18:00'], dinner: null},
  ],
});

test('widget template has both placeholders exactly once', () => {
  const source = fs.readFileSync('static/scriptable/family-os-widget.js', 'utf8');
  assert.equal(source.split('__FOS_ORIGIN__').length, 2);
  assert.equal(source.split('__FOS_KEY__').length, 2);
});

test('medium widget shows today, tomorrow and open items', async () => {
  const context = await run(scriptable({response: sample()}));
  const texts = context.texts;
  for (const expected of ['Heute', 'Morgen', 'Bringen: Tobi', 'Abholen: Britta', 'Linsencurry', 'Feiertag',
    'Nanny 16:00–18:00', '1 zu bestätigen · 2 Aufgaben', 'Stand 07:30']) {
    assert.ok(texts.includes(expected), expected + ' in ' + JSON.stringify(texts));
  }
  assert.equal(context.widget.url, 'https://fos.example/');
  assert.ok(context.files.cache, 'response is cached for offline use');
});

test('offline shows the cached state marked as old', async () => {
  const context = await run(scriptable({response: new Error('offline'), cached: JSON.stringify(sample())}));
  assert.ok(context.texts.includes('Offline · Stand 07:30'));
});

test('revoked key and no cache give a clear message', async () => {
  let context = await run(scriptable({response: {detail: 'x'}, status: 401}));
  assert.ok(context.texts.some(t => t.includes('Widget-Schlüssel ungültig')));
  context = await run(scriptable({response: new Error('offline')}));
  assert.ok(context.texts.includes('Keine Verbindung zu Family OS.'));
});

test('small widget stays compact', async () => {
  const context = await run(scriptable({response: sample(), family: 'small'}));
  assert.ok(context.texts.includes('Tobi → Britta'));
  assert.ok(!context.texts.includes('Morgen'));
});
