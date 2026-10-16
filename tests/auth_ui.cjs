const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../static/js/auth.js'), 'utf8');

function setup(seconds = 0, input = false, agreement = null, resend = false) {
  let now = 1000;
  let tick;
  const handlers = {};
  const button = { tagName: input ? 'INPUT' : 'BUTTON', value: 'Send code', textContent: 'Send code',
    after(value) { this.status = value; } };
  const form = { dataset: { cooldown: seconds }, querySelector: selector => selector === '[data-required-agreement]' ? agreement : button,
    hasAttribute: name => name === 'data-resend-code' && resend,
    checkValidity: () => true, addEventListener: (name, handler) => { handlers[name] = handler; } };
  vm.runInNewContext(script, { document: { querySelectorAll: selector => selector === 'form[data-auth-form]' ? [form] : [],
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


test('signup remains disabled until agreement is checked, including browser Back', () => {
  const agreement={checked:false,addEventListener(name,handler){this.changed=handler;}};
  const ui=setup(0,true,agreement);
  assert.equal(ui.button.disabled,true);
  let prevented=false;ui.handlers.submit({preventDefault(){prevented=true;}});assert.equal(prevented,true);
  agreement.checked=true;agreement.changed();assert.equal(ui.button.disabled,false);
  ui.handlers.submit({preventDefault(){assert.fail('agreed signup blocked');}});assert.equal(ui.button.disabled,true);
  agreement.checked=false;ui.handlers.pageshow();assert.equal(ui.button.disabled,true);
});

test('resend countdown uses a clear timer and enables at zero', () => {
  const ui=setup(60,false,null,true);
  assert.equal(ui.button.textContent,'Resend in 1:00');
  ui.advance(59);assert.equal(ui.button.textContent,'Resend in 0:01');assert.equal(ui.button.disabled,true);
  ui.advance(1);assert.equal(ui.button.disabled,false);assert.equal(ui.button.textContent,'Send code');
});
