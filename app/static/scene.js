/* The live scene: the visitor's facts as a constellation laid out in time, moved only by the server's own activity
   events (step, fact ids, labels) and by the request being in flight. Nothing here runs on a timer pretending to work:
   a pulse, a beam or a probe starts when its request or step starts and stops on the event that ends it. */
import {
  AdditiveBlending, BufferAttribute, BufferGeometry, CanvasTexture, Color, Group, Line, LineBasicMaterial, Mesh,
  MeshBasicMaterial, OctahedronGeometry, PerspectiveCamera, PlaneGeometry, Points, PointsMaterial,
  QuadraticBezierCurve3, Scene, SphereGeometry, Sprite, SpriteMaterial, SRGBColorSpace, Vector3, WebGLRenderer,
} from './vendor/three.module.min.js';

const COL = 2.3, ROW = 0.62, ARC = 32;  /* world units between sessions and between facts; points on a thread */
const WRAP = 12;  /* a memory of up to this many sessions stays on one line */
const HUE = { fact: new Color('#5ac8fa'), stale: new Color('#ff5a52'), probe: new Color('#ffd60a'),
  ok: new Color('#30d158'), beam: new Color('#7cc7ff'), pulse: new Color('#ffffff') };
const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
const ease = (dt, tau) => (still ? 1 : 1 - Math.exp(-dt / tau));
const day = time => time.slice(0, 10);

function canvasTexture(w, h, draw) {
  const c = Object.assign(document.createElement('canvas'), { width: w, height: h });
  draw(c.getContext('2d'));
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  return t;
}

const glow = () => canvasTexture(64, 64, g => {
  const r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  r.addColorStop(0, 'rgba(255,255,255,1)');
  r.addColorStop(0.22, 'rgba(255,255,255,.5)');
  r.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = r;
  g.fillRect(0, 0, 64, 64);
});

const words = (text, size) => canvasTexture(512, 96, g => {
  g.font = '600 ' + size + 'px system-ui, -apple-system, BlinkMacSystemFont, sans-serif';
  g.fillStyle = '#fff';
  g.textBaseline = 'middle';
  g.fillText(text, 6, 48, 500);
});

const ring = () => canvasTexture(128, 128, g => {
  g.strokeStyle = '#fff';
  g.lineWidth = 5;
  g.beginPath();
  g.arc(64, 64, 58, 0, Math.PI * 2);
  g.stroke();
});

const beamMap = () => canvasTexture(64, 4, g => {
  const r = g.createLinearGradient(0, 0, 64, 0);
  r.addColorStop(0, 'rgba(255,255,255,0)');
  r.addColorStop(0.5, 'rgba(255,255,255,1)');
  r.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = r;
  g.fillRect(0, 0, 64, 4);
});

const additive = (map, color) =>
  new SpriteMaterial({ map, color: color.clone(), blending: AdditiveBlending, transparent: true, depthWrite: false });

function sprite(material, scale) {
  const s = new Sprite(material);
  s.scale.setScalar(scale);
  return s;
}

function lineOf(points, color) {
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new BufferAttribute(new Float32Array(points * 3), 3));
  return new Line(geometry, new LineBasicMaterial({ color: color.clone(), transparent: true, opacity: 0.85 }));
}

/* a still field of faint points behind the facts, turned very slowly when calm: depth, not decoration that moves */
function dustCloud(count) {
  const p = new Float32Array(count * 3);
  for (let i = 0; i < p.length; i += 3) {
    p[i] = (Math.random() - 0.5) * 30;
    p[i + 1] = (Math.random() - 0.5) * 14;
    p[i + 2] = -3 - Math.random() * 12;
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new BufferAttribute(p, 3));
  return geometry;
}

const free = object => object.traverse(o => {
  if (o.geometry && !o.geometry.shared) o.geometry.dispose();
  if (o.material) { if (o.material.map && !o.material.map.shared) o.material.map.dispose(); o.material.dispose(); }
});

export function createScene(stage) {
  let renderer;
  try {
    renderer = new WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  } catch (e) {
    stage.classList.add('stage-off');
    return { sync() {}, begin() {}, event() {}, end() {} };
  }
  return build(stage, renderer);
}

/* one renderer, one scene; everything below is the state the events move */
function build(stage, renderer) {
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.domElement.setAttribute('aria-hidden', 'true');
  stage.append(renderer.domElement);
  const scene = new Scene(), camera = new PerspectiveCamera(38, 1, 0.1, 200), root = new Group();
  scene.add(root);
  const GLOW = Object.assign(glow(), { shared: true }), CORE = Object.assign(new SphereGeometry(0.11, 24, 16),
    { shared: true });
  const state = { nodes: new Map(), threads: [], rays: [], dates: new Map(), columns: new Map(), phase: 'idle',
    pending: null, lit: new Set(), look: new Vector3(), dist: 9, pointer: { x: 0, y: 0 }, t: 0, energy: 0 };
  const dust = new Points(dustCloud(180), new PointsMaterial({ size: 0.04, color: HUE.beam.clone(), transparent: true,
    opacity: 0.32, depthWrite: false }));
  scene.add(dust);

  const pulse = sprite(additive(GLOW, HUE.pulse), 0.8);
  pulse.material.opacity = 0;
  const beam = new Mesh(new PlaneGeometry(0.09, 1), new MeshBasicMaterial({ map: beamMap(), color: HUE.beam.clone(),
    transparent: true, opacity: 0, blending: AdditiveBlending, depthWrite: false }));
  const probe = new Group(), probeCore = new Mesh(new OctahedronGeometry(0.13),
    new MeshBasicMaterial({ color: HUE.probe.clone(), transparent: true }));
  const probeGlow = sprite(additive(GLOW, HUE.probe), 1.1);
  probe.add(probeCore, probeGlow);
  probe.scale.setScalar(0.001);
  const halo = sprite(additive(ring(), HUE.pulse), 0.3);
  halo.material.opacity = 0;
  const axis = lineOf(2, new Color('#ffffff'));
  axis.material.opacity = 0.12;
  root.add(pulse, beam, probe, halo, axis);
  const fx = { pulse: 0, beam: 0, probe: 0, ring: 1, okFlash: 0, beamFrom: 0, beamTo: 0 };

  /* ---- facts ---- */
  function node(id, time, label) {
    const group = new Group();
    const core = new Mesh(CORE, new MeshBasicMaterial({ color: HUE.fact.clone(), transparent: true }));
    const aura = sprite(additive(GLOW, HUE.fact), 0.95);
    const tag = new Sprite(new SpriteMaterial({ map: words(label || '', 40), transparent: true, depthWrite: false }));
    tag.center.set(-0.06, 0.5);
    tag.scale.set(1.9, 0.36, 1);
    group.add(core, aura, tag);
    root.add(group);
    const n = { id, time, label, group, core, aura, tag, pos: new Vector3(), target: new Vector3(), born: 0,
      stale: 0, staleTo: 0, lit: 0, flash: 0, seed: Math.random() * 6.3 };
    state.nodes.set(id, n);
    return n;
  }

  function relabel(n, label) {
    if (!label || n.label === label) return;
    n.tag.material.map.dispose();
    n.tag.material.map = words(label, 40);
    n.label = label;
  }

  function dateTag(time) {
    if (state.dates.has(time)) return state.dates.get(time);
    const tag = new Sprite(new SpriteMaterial({ map: words(day(time), 34), transparent: true, depthWrite: false,
      opacity: 0.45 }));
    tag.center.set(0.03, 0.5);
    tag.scale.set(1.7, 0.32, 1);
    root.add(tag);
    state.dates.set(time, tag);
    return tag;
  }

  /* sessions left to right in time order, a session's facts stacked; a long memory wraps into rows of sessions, read
     like lines of text, so that it keeps about the stage's shape. O(sessions x facts), run when the set changes */
  function layout() {
    const all = [...state.nodes.values()];
    const times = [...new Set(all.map(n => n.time).concat(state.pending || []))].sort();
    const stacks = new Map(times.map(t => [t, all.filter(n => n.time === t)]));
    const tall = Math.max(1, ...[...stacks.values()].map(s => s.length));
    const base = -((tall - 1) / 2) * ROW - 0.6, band = tall * ROW + 1.4;  /* a row: its tallest stack and date tags */
    const per = Math.max(WRAP, Math.ceil(Math.sqrt(camera.aspect * times.length * band / COL)));
    const rows = Math.max(1, Math.ceil(times.length / per)), wide = Math.min(per, times.length);
    state.columns = new Map(times.map((t, i) => [t, { x: (i % per - (wide - 1) / 2) * COL,
      y: ((rows - 1) / 2 - Math.floor(i / per)) * band }]));
    for (const [t, c] of state.columns) {
      const stack = stacks.get(t);
      stack.forEach((n, j) => n.target.set(c.x, c.y + ((stack.length - 1) / 2 - j) * ROW + 0.1, 0));
      dateTag(t).position.set(c.x, c.y + base - 0.3, 0);
    }
    for (const [t, tag] of state.dates) {
      if (!state.columns.has(t)) { free(tag); root.remove(tag); state.dates.delete(t); }
    }
    const xs = [...state.columns.values()].map(c => c.x), x0 = Math.min(0, ...xs), x1 = Math.max(0, ...xs);
    const edge = ((rows - 1) / 2) * band;
    axis.visible = rows === 1;
    const pos = axis.geometry.attributes.position;
    pos.setXYZ(0, x0 - 0.6, base, 0);
    pos.setXYZ(1, x1 + 0.6, base, 0);
    pos.needsUpdate = true;
    state.bounds = { x0: x0 - 0.45, x1: x1 + 1.35, y0: base - edge - 0.45, y1: ((tall - 1) / 2) * ROW + edge + 0.45 };
  }

  const column = time => state.columns.get(time) ?? { x: 0, y: 0 };

  function thread(from, to, drawn) {
    if (state.threads.some(th => th.from === from && th.to === to)) return;
    const line = lineOf(ARC + 1, HUE.stale);
    const spark = sprite(additive(GLOW, HUE.stale), 0.5);
    root.add(line, spark);
    state.threads.push({ from, to, line, spark, drawn, curve: new QuadraticBezierCurve3(new Vector3(), new Vector3(),
      new Vector3()) });
  }

  function drop(n) {
    free(n.group);
    root.remove(n.group);
    state.nodes.delete(n.id);
    state.threads = state.threads.filter(th => {
      const gone = th.from === n || th.to === n;
      if (gone) { free(th.line); free(th.spark); root.remove(th.line, th.spark); }
      return !gone;
    });
  }

  /* ---- the four calls the page makes ---- */
  /* `grow`: a replay, so a fact that goes stale flashes and its thread draws in, as on a live change */
  function sync(facts, grow = false) {
    const ids = new Set(facts.map(f => f.id));
    for (const n of [...state.nodes.values()]) if (!ids.has(n.id)) drop(n);
    for (const f of facts) {
      const n = state.nodes.get(f.id) || node(f.id, f.time, f.attribute);
      relabel(n, f.attribute);
      n.time = f.time;
      const stale = f.status === 'stale' ? 1 : 0;
      if (grow && stale && !n.staleTo) n.flash = 0.8;
      n.staleTo = stale;
    }
    for (const f of facts) {
      const by = state.nodes.get(f.invalidated_by);
      if (f.status === 'stale' && by) thread(state.nodes.get(f.id), by, grow ? 0 : 1);
    }
    state.pending = null;
    layout();
    for (const n of state.nodes.values()) if (!n.born && n.pos.lengthSq() === 0) n.pos.copy(n.target);
    kick(1.5);
  }

  function begin(path, time) {
    for (const n of state.nodes.values()) n.flash = 0;
    state.phase = path === 'add' ? 'S4' : 'S8';
    if (path === 'add') {
      state.pending = time;
      layout();
      pulse.position.set(column(time).x, column(time).y + 0.15, 0.2);
      fx.pulse = 1;
    } else {
      fx.probe = 1;
      probe.position.set(state.look.x + 3, state.look.y + 1.5, 3);
    }
    kick(1);
  }

  const onEvent = {
    S4(e) {
      if (e.call) return;
      e.ids.forEach((id, i) => {
        const n = state.nodes.get(id) || node(id, state.pending, e.labels[i]);
        n.pos.copy(pulse.position);
      });
      fx.pulse = 0;
      state.phase = 'S5';
      layout();
    },
    S5(e) {
      state.lit = new Set(e.ids);
      state.phase = 'S6';
      const xs = e.ids.map(id => state.nodes.get(id)).filter(Boolean).map(n => n.target.x);
      if (!xs.length) return;
      fx.beam = 1;
      fx.beamFrom = Math.min(...xs) - 0.4;
      fx.beamTo = column(state.pending).x + 0.4;
    },
    S6(e) {
      fx.beam = 0;
      if (e.call || e.ids.length < 2) return;
      const [old, by] = e.ids.map(id => state.nodes.get(id));
      if (!old || !by) return;
      old.staleTo = 1;
      old.flash = 0.8;
      thread(old, by, 0);
    },
    Store() {
      state.lit = new Set();
      state.phase = 'idle';
    },
    S8(e) {
      if (e.call) return;
      state.phase = 'S9';
      if (!e.ids.length) fx.okFlash = 1;
      for (const id of e.ids) {
        const n = state.nodes.get(id);
        if (!n) continue;
        n.flash = 1;
        const ray = lineOf(2, HUE.stale);
        root.add(ray);
        state.rays.push({ ray, to: n, life: 1 });
      }
    },
    S9() {
      fx.probe = 0;
      fx.ring = 0;
      halo.position.copy(probe.position);
      state.phase = 'idle';
    },
  };

  function event(e) {
    const handle = onEvent[e.step];
    if (handle) handle(e);
    kick(2.5);
  }

  function end() {
    fx.pulse = 0;
    fx.beam = 0;
    fx.probe = 0;
    state.lit = new Set();
    state.phase = 'idle';
    kick(1.5);
  }

  /* ---- per frame ---- */
  const tint = new Color(), mid = new Vector3(), at = new Vector3();

  function tickNode(n, dt, t) {
    n.pos.lerp(n.target, ease(dt, 0.45));
    n.born += (1 - n.born) * ease(dt, 0.5);
    n.stale += (n.staleTo - n.stale) * ease(dt, 0.6);
    n.lit += ((state.lit.has(n.id) ? 1 : 0) - n.lit) * ease(dt, 0.25);
    if (!still) n.flash = Math.max(0, n.flash - dt * 0.55);
    const bob = still ? 0 : Math.sin(t * 0.7 + n.seed) * 0.035;
    n.group.position.set(n.pos.x, n.pos.y + bob, n.pos.z);
    tint.copy(HUE.fact).lerp(HUE.stale, Math.min(1, n.stale + n.flash));
    n.core.material.color.copy(tint);
    n.aura.material.color.copy(tint);
    n.core.scale.setScalar(n.born * (1 - 0.3 * n.stale) * (1 + 0.5 * n.flash));
    n.aura.material.opacity = n.born * (0.5 - 0.3 * n.stale + 0.5 * n.lit + 0.6 * n.flash);
    n.aura.scale.setScalar(0.95 + 0.7 * n.lit + 1.4 * n.flash);
    n.tag.material.opacity = n.born * (0.92 - 0.42 * n.stale);
    n.tag.material.color.copy(n.stale > 0.5 ? HUE.stale : HUE.pulse);
  }

  function tickThread(th, dt) {
    th.drawn += (1 - th.drawn) * ease(dt, 0.7);
    const a = th.from.group.position, b = th.to.group.position, c = th.curve;
    mid.set((a.x + b.x) / 2, Math.max(a.y, b.y) + 1.1, 0.5);
    c.v0.copy(a);
    c.v1.copy(mid);
    c.v2.copy(b);
    const pos = th.line.geometry.attributes.position;
    for (let i = 0; i <= ARC; i++) { c.getPoint(i / ARC, at); pos.setXYZ(i, at.x, at.y, at.z); }
    pos.needsUpdate = true;
    th.line.geometry.setDrawRange(0, Math.max(2, Math.ceil(th.drawn * (ARC + 1))));
    c.getPoint(Math.min(1, th.drawn), at);
    th.spark.position.copy(at);
    th.spark.material.opacity = Math.max(0, 1 - th.drawn) * 1.6;
  }

  function tickRays(dt) {
    state.rays = state.rays.filter(r => {
      if (!still) r.life -= dt * 0.6;
      const pos = r.ray.geometry.attributes.position;
      pos.setXYZ(0, probe.position.x, probe.position.y, probe.position.z);
      const p = r.to.group.position;
      pos.setXYZ(1, p.x, p.y, p.z);
      pos.needsUpdate = true;
      r.ray.material.opacity = Math.max(0, r.life);
      if (r.life > 0 && (still ? state.phase !== 'idle' : true)) return true;
      free(r.ray);
      root.remove(r.ray);
      return false;
    });
  }

  function tickFx(dt, t) {
    const b = state.bounds || { x0: -1, x1: 1, y0: -1, y1: 1 };
    pulse.material.opacity += (fx.pulse - pulse.material.opacity) * ease(dt, 0.2);
    pulse.scale.setScalar(0.55 + (still ? 0 : 0.16 * Math.sin(t * 4.2)));
    beam.material.opacity += (fx.beam * 0.55 - beam.material.opacity) * ease(dt, 0.25);
    const sweep = still ? 0.5 : (Math.sin(t * 1.7) + 1) / 2;
    beam.position.set(fx.beamFrom + (fx.beamTo - fx.beamFrom) * sweep, (b.y0 + b.y1) / 2, 0.05);
    beam.scale.y = b.y1 - b.y0;
    const s = probe.scale.x + (fx.probe - probe.scale.x) * ease(dt, 0.3);
    probe.scale.setScalar(Math.max(0.001, s));
    const orbit = state.phase === 'S8' && !still;
    const goal = orbit ? at.set(state.look.x + Math.cos(t * 1.3) * 1.6, b.y1 + 0.2 + Math.sin(t * 0.9) * 0.25,
      0.9 + Math.sin(t * 1.3) * 0.7) : at.set(state.look.x, b.y1 + 0.35, 0.6);
    probe.position.lerp(goal, ease(dt, 0.35));
    probeCore.rotation.y += still ? 0 : dt * 1.8;
    fx.okFlash = still ? fx.okFlash : Math.max(0, fx.okFlash - dt * 0.7);
    probeGlow.material.color.copy(HUE.probe).lerp(HUE.ok, fx.okFlash);
    fx.ring = Math.min(1, fx.ring + (still ? 1 : dt * 0.9));
    halo.scale.setScalar(0.3 + fx.ring * 2.6);
    halo.material.opacity = (1 - fx.ring) * 0.9;
  }

  function tickCamera(dt, t) {
    const b = state.bounds || { x0: -1, x1: 1, y0: -1, y1: 1 };
    const tanH = Math.tan((camera.fov * Math.PI) / 360), w = b.x1 - b.x0 + 0.3, h = b.y1 - b.y0 + 0.6;
    const dist = Math.max(h / (2 * tanH), w / (2 * tanH * camera.aspect), 3.2) + 0.4;
    state.dist += (dist - state.dist) * ease(dt, 0.6);
    state.look.lerp(mid.set((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2, 0), ease(dt, 0.6));
    const yaw = still ? 0 : Math.sin(t * 0.07) * 0.16 + state.pointer.x * 0.14;
    const pitch = 0.05 + (still ? 0 : Math.sin(t * 0.05) * 0.03 + state.pointer.y * 0.06);
    camera.position.set(state.look.x + Math.sin(yaw) * state.dist, state.look.y + Math.sin(pitch) * state.dist,
      Math.cos(yaw) * state.dist);
    camera.lookAt(state.look);
  }

  /* ---- the loop: smooth while something moves, about 20 frames a second when calm, stopped when hidden ---- */
  let raf = 0, last = 0;

  function frame(now) {
    raf = 0;
    if (document.hidden) return;
    const busy = state.phase !== 'idle' || state.energy > 0;
    if (!still) raf = requestAnimationFrame(frame);
    if (!still && !busy && now - last < 50) return;
    const dt = still ? 10 : Math.min(0.05, (now - last) / 1000 || 0.016);
    last = now;
    state.t += still ? 0 : dt;
    state.energy = Math.max(0, state.energy - dt);
    dust.rotation.y = state.t * 0.008;
    for (const n of state.nodes.values()) tickNode(n, dt, state.t);
    for (const th of state.threads) tickThread(th, dt);
    tickRays(dt);
    tickFx(dt, state.t);
    tickCamera(dt, state.t);
    renderer.render(scene, camera);
  }

  function kick(seconds) {
    state.energy = Math.max(state.energy, seconds);
    if (!raf) raf = requestAnimationFrame(frame);
  }

  new ResizeObserver(() => {
    const { width, height } = stage.getBoundingClientRect();
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    layout();
    kick(0.5);
  }).observe(stage);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) kick(0.5); });
  stage.addEventListener('pointermove', e => {
    const r = stage.getBoundingClientRect();
    state.pointer.x = ((e.clientX - r.left) / r.width) * 2 - 1;
    state.pointer.y = ((e.clientY - r.top) / r.height) * 2 - 1;
  });
  stage.addEventListener('pointerleave', () => { state.pointer.x = 0; state.pointer.y = 0; });
  layout();
  kick(1);
  return { sync, begin, event, end };
}
