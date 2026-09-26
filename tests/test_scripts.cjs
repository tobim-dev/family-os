const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

// All scripts share one global scope in the browser. A second top-level
// let/const with the same name breaks the page; a second function silently
// replaces the first. Each top-level name must therefore be unique.
test('top-level names are unique across all page scripts', () => {
  const html = fs.readFileSync('static/index.html', 'utf8');
  const scripts = [...html.matchAll(/<script src="\/static\/([\w.]+)"/g)].map(m => m[1]);
  assert.ok(scripts.includes('app.js') && scripts.length >= 5);
  const seen = new Map();
  for (const file of scripts) {
    const source = fs.readFileSync('static/' + file, 'utf8');
    const names = [];
    for (const m of source.matchAll(/^(?:async\s+)?function\s+(\w+)/gm)) names.push(m[1]);
    for (const m of source.matchAll(/^(?:let|const|var)\s+([^;=]+?)\s*(?:=|;)/gm)) {
      for (const part of m[1].split(',')) names.push(part.trim().split(/\s|=/)[0]);
    }
    // Declarations continued on the same line: "let a=null,b=null;"
    for (const m of source.matchAll(/^(?:let|const)\s+(.+);\s*$/gm)) {
      for (const part of m[1].split(/,(?![^{(\[]*[})\]])/)) {
        const name = part.trim().match(/^(\w+)\s*=/);
        if (name) names.push(name[1]);
      }
    }
    for (const name of new Set(names)) {
      assert.ok(!seen.has(name), `${name} in ${file} and ${seen.get(name)}`);
      seen.set(name, file);
    }
  }
});
