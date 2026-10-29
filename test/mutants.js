// The mutation run: each entry of test/mutants.list.js breaks one guarded line in a copy of the tree, and the test it
// names must go red on the assertion it names. A survivor means the test does not bite; a find that does not match
// exactly once means the list went stale. Both fail the gate.
//   node test/mutants.js                     every mutant (the `development` gate, and the optional full run when live)
//   EG_MUTANTS=changed node test/mutants.js  only those whose file or test differs from origin/main; every one when the
//                                            list, runner or harness changed (the `live` gate: GATE_MODE=live in scripts/ci.sh)
// The run uses every core: each shard is this file again, with its own copy of the tree.
'use strict';
const fs = require('fs'), os = require('os'), path = require('path');
const { spawnSync, spawn } = require('child_process');
const root = path.join(__dirname, '..'), LIST = 'test/mutants.list.js';
const MUTANTS = require(path.join(root, LIST));
const LIMIT = 300000;   // a runaway mutant is killed here; a shard per core runs each test about 2.5x slower than alone

const count = (text, s) => text.split(s).length - 1;
const sh = (dir, cmd) => spawnSync(cmd, { cwd:dir, shell:true, encoding:'utf8', timeout:LIMIT });
const run = (dir, m) => { if (m.before) sh(dir, m.before); return m.cmd ? sh(dir, m.cmd) : spawnSync(process.execPath, [m.mustFail], { cwd:dir, encoding:'utf8', timeout:LIMIT }); };
// our harness prints `FAIL <name>`; another runner (`cmd`) is matched on its own failure line, e.g. `<name> [E]`
const failLine = (r, m) => ((r.stdout || '') + '\n' + (r.stderr || '')).split('\n').find(l => (m.cmd || l.startsWith('FAIL')) && l.indexOf(m.expect) >= 0);

function mutate(dir, m){
  const file = path.join(dir, m.file), orig = fs.readFileSync(file, 'utf8'), n = count(orig, m.find);
  if (n !== 1) return 'FAIL mutants: ' + m.from + ' matches ' + n + ' times in ' + m.file + ', not once';
  fs.writeFileSync(file, orig.replace(m.find, () => m.replace));
  const r = run(dir, m);
  fs.writeFileSync(file, orig);
  const hit = r.status !== 0 && failLine(r, m);
  if (hit){ console.log('   killed ' + m.from); return null; }
  return 'FAIL mutants: ' + m.from + (r.status === 0 ? ' survives ' : ' is not killed by "' + m.expect + '" in ') + m.mustFail + (r.signal ? ' (' + r.signal + ')' : '');
}

/* the live gate's selection: a mutant whose file or test changed */
function changedOnly(){
  const git = args => spawnSync('git', args, { cwd:root, encoding:'utf8' });
  const names = git(['diff', '--name-only', 'origin/main']);
  if (names.status !== 0) throw new Error('EG_MUTANTS=changed compares with origin/main, which this checkout lacks: ' + names.stderr);
  const files = names.stdout.split('\n').filter(Boolean);
  // the harness, the runner or the list changed (an edited entry names no changed file): every mutant runs
  if (files.some(f => f === 'test/check.js' || f === 'test/mutants.js' || f === LIST || f.startsWith('test/mutants/'))) return MUTANTS;
  return MUTANTS.filter(m => files.includes(m.file) || files.includes(m.mustFail));
}
const SELECTED = process.env.EG_MUTANTS === 'changed' ? changedOnly() : MUTANTS;

/* one shard: every n-th selected mutant from k, in its own copy; the control (each named test green unmutated, after its
   mutant's `before` step, since a test that needs a build is red without one) in shard 0 */
function shard(k, n){
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mutants-'));
  let fails = 0;
  try {
    // Python swap: the venv is linked like node_modules; data/ (the 300 MB benchmark) and cache/ are never copied
    fs.cpSync(root, dir, { recursive:true, filter:src => !/[/\\](?:node_modules|\.git|dist|\.venv|data|cache|__pycache__|\.claude)$/.test(src) });
    for (const d of ['node_modules', '.venv']) if (fs.existsSync(path.join(root, d))) fs.symlinkSync(path.join(root, d), path.join(dir, d), 'dir');
    if (k === 0) [...new Set(SELECTED.map(m => m.mustFail))].forEach(t => {
      const r = run(dir, SELECTED.find(m => m.mustFail === t));
      if (r.status !== 0){ fails++; console.log('FAIL mutants: ' + t + ' is red before any mutation'); }
      // an `expect` that shows on a green run names no failure, so it cannot prove which test went red
      SELECTED.filter(m => m.mustFail === t && failLine(r, m)).forEach(m => { fails++; console.log('FAIL mutants: ' + m.from + ' expects "' + m.expect + '", which a green run prints'); });
    });
    SELECTED.forEach((m, i) => { if (i % n !== k) return; const f = mutate(dir, m); if (f){ fails++; console.log(f); } });
  } finally { fs.rmSync(dir, { recursive:true, force:true }); }
  return fails;
}

if (process.env.MUTANT_SHARD){
  const [k, n] = process.env.MUTANT_SHARD.split('/').map(Number);
  process.exit(shard(k, n) ? 1 : 0);
}
const N = Math.max(1, Math.min(os.cpus().length, SELECTED.length || 1));
Promise.all(Array.from({ length:N }, (_, k) => new Promise(done => {
  const c = spawn(process.execPath, [__filename], { env:Object.assign({}, process.env, { MUTANT_SHARD:k + '/' + N }) });
  let out = ''; c.stdout.on('data', d => { out += d; }); c.stderr.on('data', d => { out += d; });
  c.on('close', code => done({ out, code }));
}))).then(rs => {
  rs.forEach(r => process.stdout.write(r.out));
  const fails = rs.reduce((t, r) => t + r.out.split('\n').filter(l => l.startsWith('FAIL mutants:')).length + (r.code && !/FAIL mutants:/.test(r.out) ? 1 : 0), 0);
  const of = SELECTED.length + (SELECTED.length < MUTANTS.length ? ' (changed only, of ' + MUTANTS.length + ')' : '');
  console.log(fails ? fails + ' mutant failure(s) of ' + of : 'mutants: all ' + of + ' killed, each by its named assertion');
  process.exit(fails ? 1 : 0);
});
