// The guard's own detection, asserted on hand-written diffs: one case per move it claims to catch, plus the tightening
// case that must stay silent. A guard nobody has watched go red is a claim, not a check. Run: node test/floorguard.test.js
'use strict';
const { walk, scan } = require('./floorguard.js');
const { check, done } = require('./check.js')();

// A unified diff, written out by hand so the expected finding is derived from the text and not from the guard itself.
const diff = (lines) => { const d = { added:[], removed:[], deleted:[] }; walk(lines.join('\n'), d); return d; };
const hunk = (file, body) => ['diff --git a/' + file + ' b/' + file, '--- a/' + file, '+++ b/' + file, '@@ -1 +1 @@', ...body];
const found = (lines, stillThere) => scan(diff(lines), stillThere).join(' | ');

check(/a test skipped or narrowed/.test(found(hunk('test/a.test.js', ['+it.skip("x", () => {});']))), 'an added it.skip is caught');
check(/a test skipped or narrowed/.test(found(hunk('test/a.test.js', ['+describe.only("x", () => {});']))), 'an added describe.only is caught');
check(/a test skipped or narrowed/.test(found(hunk('tests/test_a.py', ['+@pytest.mark.skip(reason="later")']))), 'an added pytest skip is caught');
check(/a checker silenced/.test(found(hunk('src/a.js', ['+// eslint-disable-next-line complexity']))), 'an added eslint-disable is caught');
check(/a checker silenced/.test(found(hunk('src/a.ts', ['+// @ts-ignore']))), 'an added @ts-ignore is caught');
check(/a checker silenced/.test(found(hunk('bench/a.py', ['+# ruff: noqa: E501']))), 'an added file-wide ruff noqa is caught');
check(/an empty catch/.test(found(hunk('src/a.js', ['+try { f(); } catch (e) {}']))), 'an added empty catch is caught');
check(/a TODO with no issue reference/.test(found(hunk('src/a.js', ['+// TODO tidy this up']))), 'a bare TODO is caught');
check(found(hunk('src/a.js', ['+// TODO #412 tidy this up'])) === '', 'a TODO naming an issue is allowed');
check(/a test file deleted/.test(found(['diff --git a/test/a.test.js b/test/a.test.js', '--- a/test/a.test.js', '+++ /dev/null'])), 'a deleted test file is caught');
check(/a pinned assertion count lowered/.test(found(hunk('test/a.test.js', ['-done(7, n => n);', '+done(5, n => n);']))), 'a lowered done() count is caught');
check(found(hunk('test/a.test.js', ['-done(5, n => n);', '+done(7, n => n);'])) === '', 'a raised done() count is silent');
check(/a lint budget raised/.test(found(hunk('test/lintbudget.js', ['-const BUDGET = 0;', '+const BUDGET = 3;']))), 'a raised lint budget is caught');
check(found(hunk('test/lintbudget.js', ['-const BUDGET = 3;', '+const BUDGET = 0;'])) === '', 'a lowered lint budget is silent');
check(/a mutant removed from the list/.test(found(hunk('test/mutants.list.js', ["-  { from:'area: the product', file:'src/area.js' }"]))), 'a removed mutant entry is caught');
check(/a mutant removed from the list/.test(found(hunk('test/mutants/bench.js', ["-  { from:'bench: judge parse', file:'bench/judge.py' }"]))), 'a removed per-module mutant entry is caught');
check(found(['diff --git a/docs/kit/test/a.test.js b/docs/kit/test/a.test.js', '--- a/docs/kit/test/a.test.js', '+++ /dev/null']) === '', 'a deleted test file under docs/ is outside the gate');
check(found(hunk('docs/kit/test/mutants.list.js', ["-  { from:'area: the product', file:'src/area.js' }"])) === '', 'a mutant list under docs/ is not this project\'s');
check(found(hunk('test/floorguard.js', ['+// eslint-disable-next-line complexity'])) === '', 'the guard does not report its own pattern table');
check(found(hunk('test/floorguard.test.js', ['+it.skip("x", () => {});'])) === '', 'the guard does not report its own test fixtures');
check(found(hunk('app/static/vendor/three.module.min.js', ['+try{a()}catch(e){}'])) === '', 'the hash-pinned vendored three.js is not scanned');
check(/an empty catch/.test(found(hunk('app/static/vendor/other.js', ['+try{a()}catch(e){}']))), 'any other vendored file is still scanned');
check(found(hunk('test/mutants.list.js', ["-  { from:'a', file:'x' }", "+  { from:'a', file:'x' },"])) === '', 'a reformatted mutant entry is not a removal');
const gone = ["-  { from:'memory: cap', file:F,", "-    find:'hits[:40]', replace:'hits' },"], asked = [];
check(/a mutant removed from the list/.test(found(hunk('test/mutants/memory.js', gone), () => true)), 'a removed mutant whose line is still in the code is caught');
check(found(hunk('test/mutants/memory.js', gone), t => (asked.push(t), false)) === '' && asked[0] === 'hits[:40]', 'a removed mutant whose line the change deleted is not a loosening');

done(25, n => 'floorguard: all ' + n + ' checks passed');
