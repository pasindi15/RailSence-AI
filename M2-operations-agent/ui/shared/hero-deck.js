// RailSense AI — shared 3D banner stage for M2 (Control Room + Admin Console).
//
//   const { mountHeroDeck } = await import('/shared/hero-deck.js');
//   const deck = await mountHeroDeck(rootEl, {
//     build(ctx)  { ...add page-specific objects...; return { tick(dt, t) {} } },
//     script(ctx) { return [{ text, gesture, target: () => Vector3 }, ...] },
//   });
//   deck.refresh();   // after the page's data changes
//   deck.destroy();   // when the view is torn down
//
// The stage provides: renderer + lights, a holographic platform (rings, radar
// sweep, grid, dust), "Loco" the train robot rolling on its rail, a speech
// bubble that follows the robot's head and types each script line while the
// robot performs that line's gesture, floating HTML labels, mouse parallax,
// and pausing whenever the banner can't be seen (hidden tab, other view,
// scrolled away). With reduced motion it renders still frames only.
import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.167.1/build/three.module.js';
import { createTrainRobot } from './train-robot.js';

export { THREE };

export async function mountHeroDeck(root, config = {}) {
  const stage = root.querySelector('.m2h-stage');
  const labelsEl = root.querySelector('.m2h-labels');
  const bubble = root.querySelector('.m2h-bubble');
  const bubbleText = root.querySelector('.m2h-bubble-text');
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  } catch (_) {
    root.classList.add('m2h-no-webgl');
    return { refresh() {}, destroy() {} };
  }
  renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  stage.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x050913, 0.04);
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100);
  const camBase = new THREE.Vector3(...(config.camera || [0, 4.6, 11]));
  const lookAt = new THREE.Vector3(...(config.lookAt || [0, 1.2, 0]));

  scene.add(new THREE.HemisphereLight(0xBFDBFE, 0x0B1220, 0.9));
  const key = new THREE.DirectionalLight(0xFFFFFF, 1.6); key.position.set(4, 7, 6); scene.add(key);
  const rim = new THREE.PointLight(0xC9A22A, 18, 14, 2); rim.position.set(-4, 3.5, -3); scene.add(rim);
  const fill = new THREE.PointLight(0x3B82F6, 14, 14, 2); fill.position.set(4, 2, -2); scene.add(fill);

  // Soft additive glow texture.
  const glowTex = (() => {
    const c = document.createElement('canvas'); c.width = c.height = 64;
    const g = c.getContext('2d');
    const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grd.addColorStop(0, 'rgba(255,255,255,1)'); grd.addColorStop(0.25, 'rgba(255,255,255,.5)');
    grd.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grd; g.fillRect(0, 0, 64, 64);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  })();
  const glow = (color, size, opacity = 1) => {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color, transparent: true, opacity,
      blending: THREE.AdditiveBlending, depthWrite: false }));
    s.scale.set(size, size, 1);
    return s;
  };
  const additive = (color, opacity) => new THREE.MeshBasicMaterial({ color, transparent: true, opacity,
    blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide });

  // ---- holographic platform ------------------------------------------------
  const platform = new THREE.Group();
  const [px, pz] = config.platformAt || [0, 0];
  const R = config.platformRadius || 4.6;
  platform.position.set(px, 0, pz);
  scene.add(platform);
  const disc = new THREE.Mesh(new THREE.CircleGeometry(R, 96), new THREE.MeshBasicMaterial({ color: 0x0B1B3A, transparent: true, opacity: 0.6 }));
  disc.rotation.x = -Math.PI / 2; platform.add(disc);
  const grid = new THREE.PolarGridHelper(R, 12, 6, 96, 0x1E3A8A, 0x13244A);
  grid.material.transparent = true; grid.material.opacity = 0.5; platform.add(grid);
  const rings = [[R, R * 1.018, 0x60A5FA, 0.6, 2], [R * 1.1, R * 1.11, 0xC9A22A, 0.5, 1.55], [R * 0.58, R * 0.587, 0x3B82F6, 0.35, 2]]
    .map(([a, b, c, o, arc], i) => {
      const m = new THREE.Mesh(new THREE.RingGeometry(a, b, 128, 1, 0, Math.PI * arc), additive(c, o));
      m.rotation.x = -Math.PI / 2; m.position.y = 0.01 + i * 0.004; platform.add(m); return m;
    });
  const sweep = new THREE.Mesh(new THREE.CircleGeometry(R, 64, 0, Math.PI / 5), additive(0x3B82F6, 0.14));
  sweep.rotation.x = -Math.PI / 2; sweep.position.y = 0.015; platform.add(sweep);

  const dustN = 300, dustPos = new Float32Array(dustN * 3);
  for (let i = 0; i < dustN; i++) {
    const r = 1 + Math.random() * 8, a = Math.random() * Math.PI * 2;
    dustPos[i * 3] = Math.cos(a) * r; dustPos[i * 3 + 1] = Math.random() * 5; dustPos[i * 3 + 2] = Math.sin(a) * r - 1;
  }
  const dustGeo = new THREE.BufferGeometry();
  dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPos, 3));
  const dust = new THREE.Points(dustGeo, new THREE.PointsMaterial({ map: glowTex, color: 0x60A5FA, size: 0.08,
    transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false }));
  scene.add(dust);

  // ---- the robot -------------------------------------------------------------
  const robot = createTrainRobot(THREE, config.robot || {});
  robot.group.position.set(...(config.robotAt || [-2.4, 0, 1.4]));
  robot.group.rotation.y = config.robotYaw ?? 0.35;
  robot.group.scale.setScalar(config.robotScale || 1);
  scene.add(robot.group);

  // ---- floating labels ---------------------------------------------------------
  const labels = [];
  function addLabel(html, color = '#60A5FA', anchor = new THREE.Vector3()) {
    const el = document.createElement('div');
    el.className = 'm2h-label';
    el.style.setProperty('--c', color);
    el.innerHTML = html;
    labelsEl.appendChild(el);
    const item = { el, anchor, hidden: false };
    labels.push(item);
    return item;
  }
  function clearLabels() { labels.splice(0).forEach((l) => l.el.remove()); }

  const ctx = { THREE, scene, platform, robot, camera, glow, additive, addLabel, clearLabels, R };
  const hooks = (config.build && config.build(ctx)) || {};

  // ---- speech bubble + script -----------------------------------------------
  let steps = [], stepIdx = 0, stepEnds = 0, typing = null;
  function nextStep(t) {
    try { steps = (config.script && config.script(ctx)) || []; }
    catch (err) { console.warn('hero script failed:', err); steps = []; }
    if (!steps.length) { bubble.classList.remove('show'); stepEnds = t + 3; return; }
    const step = steps[stepIdx++ % steps.length];
    const target = step.target ? step.target() : null;
    if (step.gesture) robot.gesture(step.gesture, { target });
    bubble.classList.add('show');
    bubble.dataset.tone = step.tone || '';
    clearInterval(typing);
    const text = step.text || '';
    if (reduceMotion) bubbleText.textContent = text;
    else {
      let i = 0; bubbleText.textContent = '';
      typing = setInterval(() => { bubbleText.textContent = text.slice(0, ++i); if (i >= text.length) clearInterval(typing); }, 24);
    }
    stepEnds = t + Math.max(4.8, text.length * 0.055 + 2.6);
  }

  // ---- layout / interaction -------------------------------------------------
  function resize() {
    const w = stage.clientWidth || 1, h = stage.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.position.copy(camBase).multiplyScalar(w / h < 1.1 ? 1.3 : 1);
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize); ro.observe(stage); resize();

  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  const onMove = (e) => {
    const r = root.getBoundingClientRect();
    pointer.tx = ((e.clientX - r.left) / r.width - 0.5) * 2;
    pointer.ty = ((e.clientY - r.top) / r.height - 0.5) * 2;
  };
  const onLeave = () => { pointer.tx = 0; pointer.ty = 0; };
  root.addEventListener('pointermove', onMove);
  root.addEventListener('pointerleave', onLeave);
  let onScreen = true;
  const io = new IntersectionObserver((es) => { onScreen = es[0].isIntersecting; });
  io.observe(root);

  const clock = new THREE.Clock();
  const v = new THREE.Vector3();
  let t = 0;
  function frame(dt) {
    t += dt;
    pointer.x += (pointer.tx - pointer.x) * 0.05; pointer.y += (pointer.ty - pointer.y) * 0.05;
    camera.position.x = camBase.x + pointer.x * 0.7;
    camera.position.y = camBase.y - pointer.y * 0.5;
    camera.lookAt(lookAt);

    rings[0].rotation.z += dt * 0.1; rings[1].rotation.z -= dt * 0.18; rings[2].rotation.z += dt * 0.3;
    sweep.rotation.z -= dt * 0.8;
    const d = dust.geometry.attributes.position;
    for (let i = 0; i < dustN; i++) { let y = d.getY(i) + dt * 0.1; if (y > 5) y = 0; d.setY(i, y); }
    d.needsUpdate = true;

    robot.update(dt, t, { lookX: pointer.x, roam: config.roam ?? 0.55 });
    if (hooks.tick) hooks.tick(dt, t);
    if (t >= stepEnds) nextStep(t);

    const w = stage.clientWidth, h = stage.clientHeight;
    labels.forEach((l) => {
      v.copy(l.anchor).project(camera);
      l.el.style.left = `${(v.x * 0.5 + 0.5) * w}px`;
      l.el.style.top = `${(-v.y * 0.5 + 0.5) * h}px`;
      l.el.style.opacity = v.z < 1 && !l.hidden ? '1' : '0';
    });
    robot.headAnchor(v).project(camera);
    bubble.style.left = `${(v.x * 0.5 + 0.5) * w}px`;
    bubble.style.top = `${(-v.y * 0.5 + 0.5) * h}px`;

    renderer.render(scene, camera);
  }

  const visible = () => onScreen && !document.hidden && root.isConnected && root.offsetParent !== null;
  let raf = 0, alive = true;
  function loop() {
    if (!alive) return;
    raf = requestAnimationFrame(loop);
    const dt = Math.min(clock.getDelta(), 0.05);
    if (!visible()) return;
    frame(dt);
  }
  frame(0.016);   // poster frame, even if the tab starts in the background
  let stillTimer = 0;
  if (reduceMotion) stillTimer = setInterval(() => frame(0.016), 4000);
  else loop();

  return {
    ctx,
    refresh() { if (hooks.refresh) hooks.refresh(); if (!visible()) frame(0.016); },
    destroy() {
      alive = false;
      cancelAnimationFrame(raf); clearInterval(stillTimer); clearInterval(typing);
      ro.disconnect(); io.disconnect();
      root.removeEventListener('pointermove', onMove);
      root.removeEventListener('pointerleave', onLeave);
      clearLabels();
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}
