const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {test} = require('node:test');
const vm = require('node:vm');

function worker(cached) {
  const handlers = {}, downloads = [], stored = [];
  const cache = {put: async (...args) => stored.push(args), keys: async () => [], delete: async () => true};
  vm.runInNewContext(readFileSync('static/sw.js', 'utf8'), {
    self: {location: {origin: 'https://arena.test'}, addEventListener: (name, fn) => {handlers[name] = fn;}},
    URL, console,
    caches: {match: async () => cached, open: async () => cache},
    fetch: async request => {downloads.push(request.url); return new Response('fresh');},
  });
  async function get(path, mode = 'cors') {
    let response;
    const work = [];
    handlers.fetch({request: {url: 'https://arena.test' + path, method: 'GET', mode},
      respondWith: value => {response = value;}, waitUntil: value => work.push(value)});
    const result = await response;
    await Promise.all(work);
    return result;
  }
  return {get, downloads, stored};
}

test('immutable assets are served without another network request', async () => {
  const cached = new Response('cached', {headers: {'Cache-Control': 'public, max-age=31536000, immutable'}});
  const app = worker(cached);
  assert.equal(await (await app.get('/static/js/app.js?v=123456abcdef')).text(), 'cached');
  assert.equal(app.downloads.length, 0);
});

test('unversioned assets keep refreshing in the background', async () => {
  const app = worker(new Response('cached', {headers: {'Cache-Control': 'public, max-age=86400'}}));
  assert.equal(await (await app.get('/static/js/app.js')).text(), 'cached');
  assert.equal(app.downloads.length, 1);
  assert.equal(app.stored.length, 1);
});

test('a new asset fingerprint downloads and stores the new file', async () => {
  const app = worker(undefined);
  assert.equal(await (await app.get('/static/js/app.js?v=abcdef123456')).text(), 'fresh');
  assert.equal(app.downloads.length, 1);
  assert.equal(app.stored.length, 1);
});

test('private pages and API responses are never read from the static cache', async () => {
  const app = worker(new Response('wrong player'));
  assert.equal(await app.get('/api/profile'), undefined);
  assert.equal(await (await app.get('/profile', 'navigate')).text(), 'fresh');
  assert.equal(app.stored.length, 0);
});
