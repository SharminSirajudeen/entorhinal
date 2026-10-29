// Every check or guard ships with a mutant here, in the same change (a check with no mutant is not done):
//   from      a short name
//   file      the file to break
//   find      an exact text that occurs ONCE in it (the runner fails on any other count — zero is a failure)
//   replace   the REALISTIC break: the one a reviewer would try first, not an easier one the test happens to catch
//   mustFail  the test file that must go red
//   expect    text of the one assertion that must be the FAIL line (a different red line does not count)
//   cmd       the shell command that runs `mustFail` with another runner; `expect` is then that runner's own failure
//             line (pytest: `FAILED tests/<file>::<test>`), which never appears when it passes
// Changing a guarded line moves its entry's `find` in the same change.
'use strict';
const pytest = require('./pytest.js');
const STORE = 'tests/test_store.py';
// each module's mutants live in test/mutants/<module>.js, exporting a list of the same shape, built with ./pytest.js
const modules = () => require('fs').readdirSync(__dirname + '/mutants').filter(f => f.endsWith('.js'))
  .flatMap(f => require('./mutants/' + f));
module.exports = [
  { from:'store: active() filters on status', file:'life/store.py', find:`return self._select("WHERE status = 'active'")`,
    replace:'return self._select()', ...pytest(STORE, 'test_active_excludes_stale') },
  { from:'store: stale() filters on status', file:'life/store.py', find:`return self._select("WHERE status = 'stale'")`,
    replace:'return self._select()', ...pytest(STORE, 'test_stale_lists_only_stale') },
  { from:'store: put() stores every fact given', file:'life/store.py', find:'map(astuple, facts))',
    replace:'map(astuple, facts[:1]))', ...pytest(STORE, 'test_put_stores_every_fact_given') },
  { from:'store: put() replaces by id', file:'life/store.py', find:'INSERT OR REPLACE INTO facts', replace:'INSERT INTO facts',
    ...pytest(STORE, 'test_put_replaces_same_id') },
  { from:'store: put() commits', file:'life/store.py', find:'        with self.db:\n            self.db.executemany(f"INSERT',
    replace:'        if self.db:\n            self.db.executemany(f"INSERT', ...pytest(STORE, 'test_memory_survives_reopen') },
  { from:'store: timeline order', file:'life/store.py', find:'ORDER BY time, id', replace:'ORDER BY id',
    ...pytest(STORE, 'test_timeline_is_chronological') },
  { from:'store: get() returns the row', file:'life/store.py', find:'return found[0] if found else None', replace:'return None',
    ...pytest(STORE, 'test_round_trip') },
  { from:'store: export keeps stale facts', file:'life/store.py', find:'for f in self.timeline()]', replace:'for f in self.active()]',
    ...pytest(STORE, 'test_export_keeps_stale_facts') },
  { from:'store: delete_all deletes', file:'life/store.py', find:'            self.db.execute("DELETE FROM facts")',
    replace:'            pass', ...pytest(STORE, 'test_delete_all_empties') },
  { from:'store: status constraint', file:'life/store.py', find:" CHECK (status IN ('active', 'stale'))", replace:'',
    ...pytest(STORE, 'test_status_is_constrained') },
  { from:'floorguard: narrowed test detection', file:'test/floorguard.js',
    find:"  { rule:'a test skipped or narrowed', re:/\\b(?:it|test|describe)\\.(?:skip|only)\\b|\\bx(?:it|describe)\\(|\\bpytest\\.(?:mark\\.)?skip/ },\n",
    replace:"  { rule:'a test skipped or narrowed', re:/\\b(?:it|test|describe)\\.skip\\b|\\bx(?:it|describe)\\(|\\bpytest\\.(?:mark\\.)?skip/ },\n",
    mustFail:'test/floorguard.test.js', expect:'an added describe.only is caught' },
  { from:'floorguard: pytest skip detection', file:'test/floorguard.js',
    find:"  { rule:'a test skipped or narrowed', re:/\\b(?:it|test|describe)\\.(?:skip|only)\\b|\\bx(?:it|describe)\\(|\\bpytest\\.(?:mark\\.)?skip/ },\n",
    replace:"  { rule:'a test skipped or narrowed', re:/\\b(?:it|test|describe)\\.(?:skip|only)\\b|\\bx(?:it|describe)\\(/ },\n",
    mustFail:'test/floorguard.test.js', expect:'an added pytest skip is caught' },
  { from:'floorguard: deleted test detection', file:'test/floorguard.js',
    find:"  for (const f of d.deleted) if (!/^docs\\//.test(f) && /\\.test\\.js$|_test\\.|test_/.test(f)) out.push('a test file deleted: ' + f);\n",
    replace:'', mustFail:'test/floorguard.test.js', expect:'a deleted test file is caught' },
  { from:'floorguard: TODO issue exemption', file:'test/floorguard.js',
    find:"  { rule:'a TODO with no issue reference', re:/\\bTODO\\b(?![^\\n]*#\\d)/ }\n",
    replace:"  { rule:'a TODO with no issue reference', re:/\\bTODO\\b/ }\n",
    mustFail:'test/floorguard.test.js', expect:'a TODO naming an issue is allowed' },
  { from:'floorguard: removed-mutant detection', file:'test/floorguard.js',
    find:'  return entries(d.removed).filter(', replace:'  return [].filter(',
    mustFail:'test/floorguard.test.js', expect:'a removed mutant entry is caught' },
  { from:'floorguard: a removal is judged by whether its line survived', file:'test/floorguard.js',
    find:'!kept.has(e.name) && (e.find === null || stillThere(e.find))', replace:'!kept.has(e.name)',
    mustFail:'test/floorguard.test.js', expect:'a removed mutant whose line the change deleted is not a loosening' },
  { from:'floorguard: a surviving line still counts', file:'test/floorguard.js',
    find:'(e.find === null || stillThere(e.find))', replace:'(e.find === null)',
    mustFail:'test/floorguard.test.js', expect:'a removed mutant whose line is still in the code is caught' },
  { from:'floorguard: lane mutant files watched', file:'test/floorguard.js',
    find:"    for (const l of lines.filter(l => /^test\\/mutants(?:\\.list|\\/[\\w-]+)\\.js$/.test(l.file))){\n",
    replace:"    for (const l of lines.filter(l => /^test\\/mutants\\.list\\.js$/.test(l.file))){\n",
    mustFail:'test/floorguard.test.js', expect:'a removed per-module mutant entry is caught' },
  { from:'floorguard: file-wide ruff noqa detection', file:'test/floorguard.js',
    find:"  { rule:'a checker silenced', re:/eslint-disable|@ts-(?:ignore|nocheck)|jscpd:ignore|istanbul ignore|#\\s*(?:ruff:\\s*)?noqa|#\\s*type:\\s*ignore|nosemgrep/ },\n",
    replace:"  { rule:'a checker silenced', re:/eslint-disable|@ts-(?:ignore|nocheck)|jscpd:ignore|istanbul ignore|#\\s*noqa|#\\s*type:\\s*ignore|nosemgrep/ },\n",
    mustFail:'test/floorguard.test.js', expect:'an added file-wide ruff noqa is caught' },
  { from:'floorguard: only the pinned three.js is exempt', file:'test/floorguard.js',
    find:'|^app\\/static\\/vendor\\/three\\.module\\.min\\.js$/;', replace:'|^app\\/static\\/vendor\\//;',
    mustFail:'test/floorguard.test.js', expect:'any other vendored file is still scanned' },
  { from:'floorguard: the pinned three.js is exempt', file:'test/floorguard.js',
    find:'|^app\\/static\\/vendor\\/three\\.module\\.min\\.js$/;', replace:'/;',
    mustFail:'test/floorguard.test.js', expect:'the hash-pinned vendored three.js is not scanned' },
  { from:'floorguard: a deleted test under docs/ is outside the gate', file:'test/floorguard.js',
    find:"if (!/^docs\\//.test(f) && /", replace:"if (/", mustFail:'test/floorguard.test.js', expect:'a deleted test file under docs/ is outside the gate' },
  { from:'floorguard: only the project\'s own mutant lists', file:'test/floorguard.js',
    find:'/^test\\/mutants(?:', replace:'/test\\/mutants(?:', mustFail:'test/floorguard.test.js', expect:'a mutant list under docs/ is not this project\'s' },
  ...modules()
];
