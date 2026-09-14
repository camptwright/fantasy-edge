const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const vm = require('node:vm');
const source = fs.readFileSync('src/lib/resilient-api.ts', 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const exportsObject = {};
vm.runInNewContext(code, { exports: exportsObject, process, AbortSignal, fetch });
const { createApiLoader } = exportsObject;

test('successful response stays live and bounded', async () => {
  const loader = createApiLoader(async (_url, options) => {
    assert.equal(options.cache, 'no-store');
    assert.ok(options.signal);
    return { ok: true, json: async () => [{ id: 'valid' }] };
  });
  assert.equal((await loader.fetchJson('/props', []))[0].id, 'valid');
  assert.equal(loader.failures.length, 0);
});

for (const [name, fetcher] of Object.entries({
  reset: async () => { throw new Error('ECONNRESET'); },
  timeout: async () => { throw new DOMException('timeout', 'TimeoutError'); },
  status: async () => ({ ok: false }),
  body: async () => ({ ok: true, json: async () => { throw new Error('body socket closed'); } }),
  shape: async () => ({ ok: true, json: async () => ({ detail: 'not an array' }) }),
})) {
  test(`${name} becomes explicit unavailable result`, async () => {
    const loader = createApiLoader(fetcher);
    const fallback = [];
    assert.equal(await loader.fetchJson('/props', fallback), fallback);
    assert.equal(loader.failures[0], '/props');
    assert.equal(createApiLoader(fetcher).failures.length, 0);
  });
}

test('one failed concurrent feed does not discard a successful feed', async () => {
  const loader = createApiLoader(async url => {
    if (url.endsWith('/bad')) throw new Error('reset');
    return { ok: true, json: async () => [{ id: 'good' }] };
  });
  const results = await Promise.all([loader.fetchJson('/bad', []), loader.fetchJson('/good', [])]);
  assert.equal(results[0].length, 0);
  assert.equal(results[1][0].id, 'good');
  assert.equal(loader.failures.length, 1);
});
