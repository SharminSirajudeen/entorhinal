import { createScene } from './scene.js';

const $ = id => document.getElementById(id);
/* now, in the visitor's own time zone, as the date field holds it: YYYY-MM-DDTHH:MM */
const now = () => {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
};
/* one-click examples. Recorded: a whole STALE life that this pipeline built in our benchmark run, loaded with no
   model call. Live, hand-written: two dated sessions, then a question whose premise the second may have changed */
const EXAMPLES = [
  { name: 'A design subscription (50 sessions)', seed: 'subscription' },
  { name: 'A snorkel mask (50 sessions)', seed: 'snorkel' },
  { name: 'A weekend trip (50 sessions)', seed: 'travel' },
  { name: 'Bike and cast (implied consequence)', question: 'Which route should I bike tomorrow?', sessions: [
    ['2026-03-01 08:30', "I bike 10 miles to work daily, it's the best part of my morning."],
    ['2026-03-22 19:05', 'Bad news: I fell on the stairs and my leg is in a cast for six weeks.']] },
  { name: 'Sold the car (implied consequence)', question: 'Where should I park at work tomorrow?', sessions: [
    ['2026-05-02 08:00', 'I drive my Corolla to work every morning.'],
    ['2026-05-20 18:30', 'I sold my car yesterday; the money goes to the house deposit.']] },
  { name: 'Moved city (direct change)', question: 'Which Dubai gym near my home should I join?', sessions: [
    ['2026-01-10 09:00', 'I live in Dubai, near the marina.'],
    ['2026-02-14 10:00', 'We finally moved to Abu Dhabi last weekend.']] },
  { name: 'Nothing changed (no false alarm)', question: 'Which night shift should I swap next week?', sessions: [
    ['2026-04-01 09:00', 'I work night shifts as a nurse.'],
    ['2026-04-15 09:00', 'We adopted a cat named Miso.']] },
];
const el = (tag, cls, text) =>
  Object.assign(document.createElement(tag), { className: cls || '', textContent: text || '' });
const wait = ms => new Promise(done => setTimeout(done, ms));
const CLOCK = { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
const clock = t => new Date(t * 1000).toLocaleTimeString([], CLOCK);
const usd = n => n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumSignificantDigits: 2 });
const seconds = c => c.seconds.toFixed(1) + ' s';
const many = n => n.toLocaleString('en-US');
const SAID = { active: ', running', done: ', done', skipped: '', waiting: '' };
const STEP = { S4: 'Extract', S5: 'Relate', S6: 'Judge', S8: 'Check', S9: 'Answer' };  /* log tags, by step id */
let busy = false;
let shown = 0;      /* server time of the newest event in the log */
let known = null;   /* each fact's status at the last render, so a change can be shown; null before the first */
let caught = new Set();  /* the stale facts the latest premise check found a question resting on */

async function call(path, body) {
  const r = await fetch(path, body === undefined ? { cache: 'no-store' }
    : { method: 'POST', body: JSON.stringify(body) });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error);
  return data;
}

function status(text, state) {
  $('status').textContent = text;
  $('status').dataset.state = state;
}

/* ---- timeline ---- */
const change = f => !known ? '' : !(f.id in known) ? 'new' : known[f.id] === f.status ? '' : 'staled';

function fact(f, byId) {
  const li = el('li', 'fact');
  li.dataset.status = f.status;
  li.dataset.change = change(f);
  const head = el('p', 'fact-head');
  head.append(el('span', 'when', f.time), el('span', '', f.subject + ' · ' + f.attribute));
  const value = el('p', 'value');
  value.append(el('span', '', f.value));
  li.append(head, value);
  const by = byId[f.invalidated_by];
  if (f.status === 'stale' && by) {
    head.append(el('span', 'pill', 'Stale'));
    li.append(el('p', 'cause', 'invalidated by "' + by.value + '" on ' + by.time + ' (' + f.reason + ')'));
  }
  if (caught.has(f.id)) {
    li.dataset.caught = '';
    head.append(el('span', 'pill caught', 'Caught by the check'));
  }
  return li;
}

async function facts() {
  const all = await call('/timeline');
  return [all, Object.fromEntries(all.map(f => [f.id, f]))];
}

async function showTimeline() {
  const [all, byId] = await facts();
  $('timeline').replaceChildren(...(all.length ? all.map(f => fact(f, byId))
    : [el('li', 'empty', 'Nothing remembered yet. Try an example, or add your own session below.')]));
  const stale = all.filter(f => f.status === 'stale').length;
  $('counts').textContent = all.length ? many(all.length) + ' facts · ' + stale + ' made untrue' : '';
  known = Object.fromEntries(all.map(f => [f.id, f.status]));
  $('stage').toggleAttribute('data-empty', !all.length);
  scene.sync(all);
  const first = $('timeline').querySelector('[data-caught]');  /* scrolled within the list, never the page */
  if (first) $('timeline').scrollTop += first.getBoundingClientRect().top - $('timeline').getBoundingClientRect().top - 8;
  return all;
}

/* ---- answer: the premise check first, then the answer ---- */
function banner(text, why) {
  const box = el('div', 'banner');
  const words = el('p');
  words.append(el('strong', '', 'Outdated: '), text);
  box.append(words, el('p', 'why', why));
  return box;
}

/* each assumption the check found; one a newer fact made untrue says which fact, when, and why */
function assumption(premise, stale, byId) {
  if (!stale) return el('p', 'clear', premise.replace(/\.$/, '') + ': not outdated');
  const by = byId[stale.invalidated_by];
  const since = by ? '. Changed on ' + by.time + ' by "' + by.value + '"' : '';
  return banner(premise.replace(/\.$/, '') + since, stale.reason);
}

/* the model's **bold**, as bold; everything else as plain text (never parsed as HTML) */
function prose(node, text) {
  node.replaceChildren(...text.split(/\*\*(.+?)\*\*/).map((part, i) => i % 2 ? el('strong', '', part) : part));
}

async function showAnswer(a, report, text) {
  const [, byId] = await facts();
  const { premises, stale } = a.premise_report;
  caught = new Set(stale.map(s => s.fact_id));
  report.replaceChildren(...(premises.length
    ? premises.map(p => assumption(p, stale.find(s => s.premise === p), byId))
    : [el('p', 'clear', 'The question assumes nothing about you.')]));
  prose(text, a.text);
}

/* ---- live pipeline: the server's own log, polled while a request runs ---- */
function entry(e) {
  const li = el('li', e.call ? 'call' : '');
  li.append(el('time', 'at', clock(e.t)), el('span', 'tag', STEP[e.step] || e.step), el('span', 'what', e.text));
  const c = e.call;
  const tokens = c && many(c.tokens) + ' tokens';
  if (c) li.append(el('span', 'cost', seconds(c) + ' · ' + tokens + ' · ' + usd(c.usd)));
  return li;
}

async function poll() {
  const fresh = (await call('/activity').catch(() => [])).filter(e => e.t > shown);
  if (!fresh.length) return fresh;
  shown = fresh[fresh.length - 1].t;
  const box = $('log').parentElement;
  const atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 32;
  $('log').append(...fresh.map(entry));
  if (atEnd) box.scrollTop = box.scrollHeight;
  return fresh;
}

/* the thinking orb: while a model step runs, what it is doing, for how long, and the latest thing the pipeline said */
let thinking = null;  /* { step, since, timer } while a model step runs */
function think(step, said) {
  if (said) $('thinking-said').textContent = said;
  if (step === (thinking && thinking.step)) return;
  if (thinking) clearInterval(thinking.timer);
  thinking = step && { step, since: performance.now() };
  $('thinking').hidden = !step;
  if (!step) return;
  $('thinking-what').textContent = step.dataset.doing;
  const tick = () => { $('thinking-time').textContent = ((performance.now() - thinking.since) / 1000).toFixed(1) + ' s'; };
  tick();
  thinking.timer = setInterval(tick, 100);
}

/* a step is done once it has logged; the one after the latest logged step is running; a model step with no model
   call was skipped */
function stateOf(step, i, at, call, finished) {
  if (i <= at) return (call || !step.hasAttribute('data-model')) ? 'done' : 'skipped';
  return !finished && i === at + 1 ? 'active' : 'waiting';
}

function stage(path, events, finished) {
  const steps = [...document.querySelectorAll('.track[data-path="' + path + '"] .step')];
  const latest = events.length ? events[events.length - 1].step : null;
  const at = steps.findIndex(s => s.dataset.step === latest);
  steps.forEach((s, i) => {
    const c = events.find(e => e.call && e.step === s.dataset.step);
    const state = s.dataset.state = stateOf(s, i, at, c, finished);
    s.querySelector('.took').textContent = c ? seconds(c.call) : state === 'skipped' ? 'Skipped' : '';
    s.querySelector('.said').textContent = SAID[state];
    const doing = s.dataset.doing + '…';  /* set only when it changes: #status is a live region, read out on change */
    if (state === 'active' && $('status').textContent !== doing) $('status').textContent = doing;
  });
  const running = steps.find(s => s.dataset.state === 'active' && s.hasAttribute('data-model'));
  const said = [...events].reverse().find(e => !e.call);
  think(running || null, said && said.text);
}

function total(events, finished) {
  const calls = events.filter(e => e.call).map(e => e.call);
  const tokens = calls.reduce((n, c) => n + c.tokens, 0), cost = calls.reduce((n, c) => n + c.usd, 0);
  const counted = calls.length + (calls.length === 1 ? ' model call · ' : ' model calls · ');
  $('total').textContent = calls.length ? counted + many(tokens) + ' tokens · ' + usd(cost)
    : finished ? 'Idle' : 'Running';
}

async function watch(path, request, time) {
  const events = [];
  let open = true;
  const ended = request.catch(() => {}).then(() => { open = false; });
  $('engine').dataset.path = path;
  stage(path, events, false);
  scene.begin(path, time);
  total(events, false);
  while (open) {
    await Promise.race([ended, wait(400)]);
    const last = !open;
    const fresh = await poll();
    fresh.forEach(scene.event);
    events.push(...fresh);
    stage(path, events, last);
    total(events, last);
  }
  scene.end();
  think(null);
  return request;
}

/* ---- actions ---- */
const run = (label, work) => async e => {
  e?.preventDefault();
  if (busy) return;
  busy = true;
  document.body.dataset.busy = '';
  status(label + '…', 'busy');
  try {
    const done = await work() || '';
    status(done, '');
    setTimeout(() => { if ($('status').textContent === done) status('', ''); }, 6000);  /* a result fades; an error stays */
  } catch (err) { status(err.message, 'error'); }
  busy = false;
  delete document.body.dataset.busy;
  await showTimeline().catch(() => {});
};

async function add() {
  const session = { time: $('time').value.replace('T', ' '), text: $('text').value };
  caught = new Set();  /* a new session can change what the last check found */
  remember(null);
  await watch('add', call('/ingest', { sessions: [session] }), session.time);
  $('text').value = '';
  $('time').value = now();
}

async function ask() {
  await showAnswer(await watch('ask', call('/ask', { question: $('question').value })), $('report'), $('answer-text'));
  $('answer').hidden = false;
  $('answer').scrollIntoView({ block: 'nearest' });
}

async function remove() {
  await call('/delete-all', {});
  caught = new Set();
  remember(null);
  $('answer').hidden = true;
  $('compare').hidden = true;
  $('log').replaceChildren();
  $('total').textContent = 'Idle';
}

const reveal = node => node.closest('section').scrollIntoView({ block: 'nearest' });
/* which recorded memory this browser holds untouched, so a reload shows its comparison again; a convenience only */
const remember = name => {
  try { if (name) localStorage.setItem('example', name); else localStorage.removeItem('example'); } catch { /* off */ }
};
const remembered = () => { try { return localStorage.getItem('example'); } catch { return null; } };

/* a recorded memory, rebuilt in the scene session by session: a fact counts as stale only once the fact that replaced
   it has arrived, so each red thread draws at the moment its change happened. O(sessions x facts), about 4 s */
const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
async function replay(all) {
  const byId = Object.fromEntries(all.map(f => [f.id, f]));
  const last = Math.max(...all.map(f => f.source_idx));
  $('total').textContent = 'Replaying how this memory was built';
  $('stage').toggleAttribute('data-empty', false);
  for (let k = 0; k <= last && !still; k++) {
    scene.sync(all.filter(f => f.source_idx <= k).map(f => {
      const by = byId[f.invalidated_by];
      return f.status === 'stale' && by && by.source_idx > k ? { ...f, status: 'active' } : f;
    }), true);
    await wait(75);
  }
}

const verdict = (node, correct) => {
  node.dataset.correct = correct;
  node.textContent = (correct ? 'Right' : 'Wrong') + ', by STALE\'s judge';
};

/* a recorded memory: the server swaps in the whole STALE life; beside it, the scenario's question and both answers
   our run recorded to it, from the model that read the whole history and from this memory */
async function load(name, scroll = true) {
  const x = await call('/example', { name });
  await replay((await facts())[0]);
  await showAnswer(x.ours.answer, $('ours-report'), $('ours-text'));
  const stale = (await showTimeline()).filter(f => f.status === 'stale').length;
  await poll();
  $('compare-meta').textContent = 'A whole life from the STALE benchmark: ' + x.sessions + ' sessions, ' +
    many(x.chars) + ' characters of chat. This pipeline built ' + many(x.loaded) + ' facts from it and marked ' +
    stale + ' untrue. It is your memory now; Delete everything, at the bottom, to start your own.';
  $('compare-question').textContent = x.question;
  $('flat-how').textContent = 'All ' + x.sessions + ' sessions in one prompt, reasoning on, then the question.';
  prose($('flat-text'), x.flat.answer);
  verdict($('flat-verdict'), x.flat.correct);
  $('ours-how').textContent = 'Nemotron 3 Super checks the question against the ' + many(x.loaded) +
    ' dated facts, then answers: 2 model calls, ' + usd(x.ours.answer.cost_usd) + '.';
  verdict($('ours-verdict'), x.ours.correct);
  $('compare').hidden = false;
  $('question').value = x.question;
  $('total').textContent = 'Recorded memory loaded · no model call';
  if (scroll) reveal($('compare-title'));
  remember(name);
  return 'Loaded ' + many(x.loaded) + ' facts from ' + x.sessions + ' sessions, as built in our STALE run.';
}

/* an example starts on an empty memory (sessions go in date order), and adds each session as a visitor would */
async function example() {
  const x = EXAMPLES[$('example').value];
  await remove();
  await showTimeline();
  if (x.seed) return load(x.seed);
  for (const [time, text] of x.sessions) {
    $('time').value = time.replace(' ', 'T');
    $('text').value = text;
    reveal($('timeline'));
    await add();
    await showTimeline();
  }
  $('question').value = x.question;
  reveal($('ask'));
  $('ask').focus({ preventScroll: true });
  return 'Example added. Press Ask to check its question.';
}

$('add').form.addEventListener('submit', run('Adding', add));
$('ask').form.addEventListener('submit', run('Asking', ask));
$('try').addEventListener('submit', run('Loading', example));
const wipe = run('Deleting', remove);
$('delete').addEventListener('click', e => { if (confirm('Delete all your memory?')) wipe(e); });
$('only-stale').addEventListener('change', e => $('timeline').toggleAttribute('data-only-stale', e.target.checked));
$('text').addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) $('add').form.requestSubmit();
});
for (const [label, live] of [['Recorded in our STALE run: instant, no model call', false],
  ['Live on Nemotron: two sessions, then a question', true]]) {
  const group = Object.assign(document.createElement('optgroup'), { label });
  EXAMPLES.forEach((x, i) => { if (!x.seed === live) group.append(new Option(x.name, i)); });
  $('example').append(group);
}
$('example').addEventListener('change', e => {
  $('run-example').textContent = EXAMPLES[e.target.value].seed ? 'Load this memory' : 'Run it live';
});
$('time').value = now();
const scene = createScene($('stage'));
/* an empty memory opens on the first recorded one, so the page never starts blank; it costs no model call */
showTimeline().then(all => {
  const name = all.length ? remembered() : EXAMPLES[0].seed;
  return name ? run('Loading', () => load(name, false))() : poll();
}).catch(() => {});
