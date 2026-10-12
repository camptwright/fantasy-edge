const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {main, inventory, sourceRoots} = require('../scripts/release-provenance.cjs');

function fixture(t) {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'fantasy-release-test-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  fs.mkdirSync(path.join(root,'.next'));
  fs.mkdirSync(path.join(root,'src'));
  fs.writeFileSync(path.join(root,'src/app.tsx'),'original source');
  fs.writeFileSync(path.join(root,'.next/BUILD_ID'),'test-build');
  fs.writeFileSync(path.join(root,'server.js'),'server');
  fs.writeFileSync(path.join(root,'release-source.json'),JSON.stringify(main('source',root)));
  main('seal',root);
  return root;
}

test('sealed build matches and preserves source evidence', t=>{
  const root=fixture(t), result=main('verify',root);
  assert.equal(result.status,'matched');
  assert.equal(result.build_id,'test-build');
  assert.deepEqual(result.source,inventory(root,sourceRoots));
});
for (const failure of ['changed','missing','unexpected']) {
  test(`detects ${failure} artifacts`,t=>{
    const root=fixture(t);
    if(failure==='changed') fs.writeFileSync(path.join(root,'server.js'),'tampered');
    if(failure==='missing') fs.unlinkSync(path.join(root,'server.js'));
    if(failure==='unexpected') fs.writeFileSync(path.join(root,'.next/extra.js'),'extra');
    const result=main('verify',root);
    assert.equal(result.status,'drift');
    assert.equal(result.artifacts[failure].length,1);
  });
}
test('ignores runtime cache and env files but rejects symlinked source',t=>{
  const root=fixture(t);
  fs.mkdirSync(path.join(root,'.next/cache'));
  fs.writeFileSync(path.join(root,'.next/cache/runtime'),'mutable');
  fs.writeFileSync(path.join(root,'.env'),'never read');
  fs.writeFileSync(path.join(root,'src/.env'),'never read');
  assert.equal(main('verify',root).status,'matched');
  assert.deepEqual(main('source',root).files,JSON.parse(fs.readFileSync(path.join(root,'release-source.json'))).files);
  fs.symlinkSync(path.join(root,'.env'),path.join(root,'src/linked.ts'));
  assert.throws(()=>main('source',root),/Symlink/);
});
test('missing or invalid manifest cannot qualify a release',t=>{
  const root=fixture(t);
  fs.writeFileSync(path.join(root,'release-manifest.json'),'{}');
  assert.throws(()=>main('verify',root),/Invalid manifest/);
  fs.unlinkSync(path.join(root,'release-manifest.json'));
  assert.throws(()=>main('verify',root));
});
