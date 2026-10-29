// Every other check here reads the code as it now stands, so a test can be weakened without one of them noticing: delete
// a test file and nothing runs it, lower a done(N) to match a population that already shrank and check.js agrees, drop an
// entry from mutants.list.js and the runner never misses it. This one reads the DIFF instead, and only ever reports a
// change that LOWERS the bar — tightening is silent, loosening is loud. A diff it could not compute exits 2, never 0.
// Run: node test/floorguard.js [--base <ref>] — part of `npm run gate`.
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');

const git = (args) => {
  try { return execFileSync('git', args, { encoding:'utf8', stdio:['ignore','pipe','pipe'] }); }
  catch (e){ return null; }
};
const bail = (why) => {
  console.log('FAIL floorguard could not read the diff: ' + why + ' — a diff that did not run is not a pass');
  process.exit(2);
};

/* The patterns below occur literally in this file, in its own test, which carries one fixture per pattern, and in
   mutants.list.js, which stores the text it breaks. Scanning any of the three reports the guard as its own violation,
   so all three are exempt by path — stated here, where the reason is readable, rather than inline. The vendored
   three.js build is third-party code kept byte for byte (its minifier writes empty catches); tests/test_app.py pins it
   by sha256, so any edit to it is already red. Only that one file is exempt, not the folder it sits in. */
const EXEMPT = /test\/floorguard(\.test)?\.js$|test\/mutants(?:\.list|\/[\w-]+)\.js$|^app\/static\/vendor\/three\.module\.min\.js$/;

const LOOSENING = [
  { rule:'a test skipped or narrowed', re:/\b(?:it|test|describe)\.(?:skip|only)\b|\bx(?:it|describe)\(|\bpytest\.(?:mark\.)?skip/ },
  { rule:'a checker silenced', re:/eslint-disable|@ts-(?:ignore|nocheck)|jscpd:ignore|istanbul ignore|#\s*(?:ruff:\s*)?noqa|#\s*type:\s*ignore|nosemgrep/ },
  { rule:'an empty catch', re:/catch\s*(?:\([^)]*\))?\s*\{\s*\}/ },
  { rule:'a TODO with no issue reference', re:/\bTODO\b(?![^\n]*#\d)/ }
];
const NUMBERS = [
  { rule:'a pinned assertion count lowered', re:/done\(\s*(\d+)/, worse:(now, was) => now < was },
  { rule:'a lint budget raised', re:/BUDGET\s*=\s*(\d+)/, worse:(now, was) => now > was }
];

// origin/main when there is one to compare against, else the previous commit. Neither means there is no earlier state,
// and nothing can have been lowered relative to it — that is a clean run, not an unreadable one.
function resolveBase(){
  const i = process.argv.indexOf('--base');
  if (i > -1) return process.argv[i + 1];
  if (git(['rev-parse', '--verify', '-q', 'origin/main'])) return 'origin/main';
  if (git(['rev-parse', '--verify', '-q', 'HEAD^'])) return 'HEAD^';
  return null;
}

// Added and removed lines, plus the files the change deletes outright. Untracked files count as all-added: a new file
// carrying a suppression comment is the same move as adding one to a tracked file.
function readDiff(base){
  const mb = git(['merge-base', base, 'HEAD']);
  if (!mb) bail('no merge base against ' + base);
  const text = git(['diff', '--unified=0', mb.trim(), '--']);
  if (text === null) bail('could not diff against ' + base);
  const list = git(['ls-files', '--others', '--exclude-standard']);
  if (list === null) bail('could not list untracked files');
  const d = { added:[], removed:[], deleted:[] };
  walk(text, d);
  for (const f of list.split('\n').filter(Boolean)) addFile(f, d);
  return d;
}

function addFile(f, d){
  let body = '';
  try { body = fs.readFileSync(f, 'utf8'); } catch (e){ return; }   // a file that vanished mid-run is not a finding
  for (const text of body.split('\n')) d.added.push({ file:f, text });
}

/* `---` and `+++` name a file only between a `diff` line and that file's first `@@` hunk; inside a hunk they are content,
   so an added `+++i` is a change, not a header. A deletion's new name is /dev/null, so the old name is kept. */
function walk(text, d){
  let file = '', old = '', header = false;
  for (const line of text.split('\n')){
    if (line.startsWith('diff ')) header = true;
    else if (line.startsWith('@@')) header = false;
    else if (header) [file, old] = heading(line, file, old, d);
    else if (line.startsWith('+')) d.added.push({ file, text:line.slice(1) });
    else if (line.startsWith('-')) d.removed.push({ file, text:line.slice(1) });
  }
}

function heading(line, file, old, d){
  const name = (s) => s.replace(/^[ab]\//, '');
  if (line.startsWith('--- ')) return [file, name(line.slice(4))];
  if (!line.startsWith('+++ ')) return [file, old];
  const next = name(line.slice(4));
  if (next !== '/dev/null') return [next, old];
  d.deleted.push(old);
  return [old, old];
}

const nums = (lines, re) => lines.map(l => l.text.match(re)).filter(Boolean).map(m => Number(m[1]));

// A number only counts as lowered when the same file shows the old value leaving and the new value arriving.
function numberFindings(d, out){
  for (const { rule, re, worse } of NUMBERS){
    for (const file of new Set(d.added.map(a => a.file))){
      const was = nums(d.removed.filter(r => r.file === file), re);
      const now = nums(d.added.filter(a => a.file === file), re);
      if (was.length && now.length && worse(Math.min(...now), Math.min(...was)))
        out.push(rule + ' in ' + file + ': ' + Math.min(...was) + ' -> ' + Math.min(...now));
    }
  }
}

/* A line in mutants.list.js changes whenever the entry is reformatted or its `find` text moves, and the old line then
   shows up as removed while the entry is still there. Only a `from:` name that left and did not come back is a removal,
   and only while the text it broke is still in the code: a change that deletes that text leaves its mutant nothing to
   break (the runner refuses a `find` that matches nothing), so the entry goes with it. An unreadable `find` counts. */
function mutantsGone(d, stillThere){
  const entries = (lines) => {
    const out = [];
    for (const l of lines.filter(l => /^test\/mutants(?:\.list|\/[\w-]+)\.js$/.test(l.file))){
      const name = l.text.match(/\bfrom:\s*'([^']+)'/), find = l.text.match(/\bfind:\s*'((?:[^'\\]|\\.)*)'/);
      if (name) out.push({ name:name[1], find:null });
      if (find && out.length && out[out.length - 1].find === null) out[out.length - 1].find = find[1];
    }
    return out;
  };
  const kept = new Set(entries(d.added).map(e => e.name));
  return entries(d.removed).filter(e => !kept.has(e.name) && (e.find === null || stillThere(e.find))).map(e => e.name);
}

/* The text a mutant broke, read back from its JS string literal, searched for in the tracked code outside the mutant
   lists; its first non-blank line is enough to know whether the change deleted it. */
function inCode(literal){
  const text = literal.replace(/\\(.)/g, (_, c) => ({ n:'\n', t:'\t' })[c] ?? c).split('\n').find(s => s.trim()) ?? '';
  return git(['grep', '-q', '-F', '-e', text, '--', '.', ':(exclude)test/mutants*']) !== null;
}

function scan(d, stillThere = inCode){
  const out = [];
  for (const { file, text } of d.added){
    if (EXEMPT.test(file)) continue;
    for (const { rule, re } of LOOSENING) if (re.test(text)) out.push(rule + ' in ' + file + ': ' + text.trim().slice(0, 90));
  }
  // docs/ holds reports and documentation, outside the gate as it is outside lint and duplication
  for (const f of d.deleted) if (!/^docs\//.test(f) && /\.test\.js$|_test\.|test_/.test(f)) out.push('a test file deleted: ' + f);
  for (const name of mutantsGone(d, stillThere)) out.push('a mutant removed from the list: ' + name);
  numberFindings(d, out);
  return out;
}

/* The scan runs on a real diff here and on hand-written diffs in test/floorguard.test.js, which is the second caller
   the export exists for: a guard whose own detection is never asserted is a guard nobody has seen go red. */
module.exports = { walk, scan };

if (require.main === module){
  const base = resolveBase();
  if (!base){ console.log('floorguard: no earlier commit to compare against, nothing could have been lowered'); process.exit(0); }
  const findings = scan(readDiff(base));
  for (const f of findings) console.log('FAIL ' + f);
  console.log(findings.length
    ? findings.length + ' floor violation(s) against ' + base + ': raise the bar back, or say in the change why it moved'
    : 'floorguard: nothing in this change lowers the bar (base ' + base + ')');
  process.exit(findings.length ? 1 : 0);
}
