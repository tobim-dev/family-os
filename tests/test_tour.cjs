const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const ctx = vm.createContext({});
vm.runInContext(fs.readFileSync('static/tour.js', 'utf8') + '\nthis.steps = TOUR_STEPS;', ctx);
const steps = ctx.steps;
const app = fs.readFileSync('static/app.js', 'utf8');
const all = fs.readdirSync('static').filter(f => f.endsWith('.js')).map(f => fs.readFileSync('static/' + f, 'utf8')).join('\n');

test('every step points to an existing view and has text', () => {
  const views = JSON.parse(app.match(/if\(!\[(.*?)\]\.includes\(next\)\)/)[1].replace(/'/g, '"').replace(/^/, '[').replace(/$/, ']'));
  assert.ok(steps.length >= 10);
  for (const step of steps) {
    assert.ok(views.includes(step.view), step.view);
    assert.ok(step.title.length > 3 && step.text.length > 40, step.title);
  }
  for (const view of ['plan', 'issues', 'tasks', 'meals', 'nanny', 'lina', 'notifications', 'connections']) {
    assert.ok(steps.some(s => s.view === view), 'Bereich fehlt im Rundgang: ' + view);
  }
});

test('highlighted elements exist in the page scripts', () => {
  for (const step of steps.filter(s => s.highlight)) {
    const token = step.highlight.match(/\[([\w-]+(?:="[^"]+")?)\]|#([\w-]+)|\.([\w-]+)/);
    const needle = token[1] || (token[2] ? `id="${token[2]}"` : `class="${token[3]}`);
    assert.ok(all.includes(needle.replace(/"$/, '')), `${step.title}: ${needle} nicht gefunden`);
  }
});
