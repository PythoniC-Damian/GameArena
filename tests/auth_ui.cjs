const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../static/js/auth.js'), 'utf8');

function setup(seconds = 0, input = false) {
  let now = 1000;
  let tick;
  const handlers = {};
  const button = { tagName: input ? 'INPUT' : 'BUTTON', value: 'Send code', textContent: 'Send code',
    after(value) { this.status = value; } };
  const form = { dataset: { cooldown: seconds }, querySelector: () => button,
    checkValidity: () => true, addEventListener: (name, handler) => { handlers[name] = handler; } };
  vm.runInNewContext(script, { document: { querySelectorAll: () => [form],
    createElement: () => ({ setAttribute() {} }) },
    window: { addEventListener: (name, handler) => { handlers[name] = handler; } },
    Date: { now: () => now }, setInterval: callback => { tick = callback; return 1; }, clearInterval() {} });
  return { button, handlers, advance(seconds) { now += seconds * 1000; tick(); } };
}

test('first submit disables button; repeated submit is blocked; browser Back restores it', () => {
  const { button, handlers } = setup(0, true);
  handlers.submit({ preventDefault() { assert.fail('first submit blocked'); } });
  assert.equal(button.disabled, true);
  assert.equal(button.value, 'Please wait…');
  let prevented = false;
  handlers.submit({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  handlers.pageshow();
  assert.equal(button.disabled, false);
  assert.equal(button.value, 'Send code');
});

test('cooldown displays remaining seconds and enables sending after expiry', () => {
  const ui = setup(60);
  assert.equal(ui.button.disabled, true);
  assert.match(ui.button.status.textContent, /60 seconds/);
  let prevented = false;
  ui.handlers.submit({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  ui.advance(30);
  assert.match(ui.button.status.textContent, /30 seconds/);
  ui.advance(30);
  assert.equal(ui.button.disabled, false);
  assert.equal(ui.button.status.textContent, '');
});
