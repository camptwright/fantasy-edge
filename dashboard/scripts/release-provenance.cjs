// Build-time provenance and read-only runtime verification. No env inspection.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const sourceRoots = ['src', 'public', 'scripts', 'package.json', 'package-lock.json',
  'next.config.js', 'postcss.config.js', 'tailwind.config.js', 'tsconfig.json',
  'next-env.d.ts', 'Dockerfile', '.dockerignore'];
const artifactRoots = ['.next', 'public', 'server.js', 'package.json'];

function inventory(root, roots) {
  const result = {};
  function visit(relative) {
    const absolute = path.join(root, relative);
    if (!fs.existsSync(absolute)) return;
    const stat = fs.lstatSync(absolute);
    if (stat.isSymbolicLink()) throw new Error('Symlink in release inventory');
    if (stat.isDirectory()) {
      for (const name of fs.readdirSync(absolute).sort()) {
        if (name === 'cache' || name === 'node_modules' || name.startsWith('.')) continue;
        visit(path.join(relative, name));
      }
    } else if (stat.isFile()) {
      result[relative] = crypto.createHash('sha256').update(fs.readFileSync(absolute)).digest('hex');
    }
  }
  roots.forEach(visit);
  return result;
}

function differences(expected, actual) {
  return {
    missing: Object.keys(expected).filter(k => !(k in actual)).sort(),
    unexpected: Object.keys(actual).filter(k => !(k in expected)).sort(),
    changed: Object.keys(expected).filter(k => k in actual && expected[k] !== actual[k]).sort(),
  };
}

function main(mode, root) {
  if (mode === 'source') return {schema: 1, files: inventory(root, sourceRoots)};
  if (mode === 'seal') {
    const source = JSON.parse(fs.readFileSync(path.join(root, 'release-source.json')));
    const manifest = {schema: 1, source: source.files,
      build_id: fs.readFileSync(path.join(root, '.next/BUILD_ID'), 'utf8').trim(),
      artifacts: inventory(root, artifactRoots)};
    fs.writeFileSync(path.join(root, 'release-manifest.json'), JSON.stringify(manifest));
    return {status: 'sealed'};
  }
  if (mode !== 'verify') throw new Error('Unknown mode');
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'release-manifest.json')));
  if (manifest.schema !== 1 || !Object.keys(manifest.source || {}).length ||
      !Object.keys(manifest.artifacts || {}).length) throw new Error('Invalid manifest');
  const drift = differences(manifest.artifacts, inventory(root, artifactRoots));
  const build = fs.readFileSync(path.join(root, '.next/BUILD_ID'), 'utf8').trim();
  return {status: Object.values(drift).some(v => v.length) || build !== manifest.build_id ? 'drift' : 'matched',
    source: manifest.source, build_id: build, artifacts_checked: Object.keys(manifest.artifacts).length,
    artifacts: drift};
}

module.exports = {inventory, differences, main, sourceRoots, artifactRoots};
if (require.main === module) {
  try {
    const report = main(process.argv[2], process.argv[3] || process.cwd());
    console.log(JSON.stringify(report));
    if (report.status === 'drift') process.exitCode = 1;
  } catch {
    console.log(JSON.stringify({status: 'unavailable_or_invalid_manifest'}));
    process.exitCode = 1;
  }
}
