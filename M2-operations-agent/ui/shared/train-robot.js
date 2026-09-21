// RailSense AI — "Loco", the train robot (shared Three.js character).
//
// A procedural robot whose torso is a locomotive nose: headlight, gold livery
// stripes and a cowcatcher; a driver's-cab head with a visor, blinking eyes,
// a smokestack that puffs steam and a pantograph antenna; piston arms with
// coupler hands; and a wheeled bogie that rolls along a short rail.
//
//   const loco = createTrainRobot(THREE);
//   scene.add(loco.group);
//   loco.gesture('wave' | 'point' | 'nod' | 'cheer' | 'alert', { target: Vector3 });
//   loco.update(dt, t, { lookX, roam });   // every frame
//
// Used by the Control Room and Admin Console banners (ui/shared/hero-deck.js).

export function createTrainRobot(THREE, opts = {}) {
  const C = {
    body: opts.bodyColor ?? 0x2563EB,
    trim: opts.trimColor ?? 0xC9A22A,
    steel: 0x1E293B,
    dark: 0x0B1220,
    eye: opts.eyeColor ?? 0x67E8F9,
    light: 0xFFF7D6,
  };
  const mat = {
    body: new THREE.MeshStandardMaterial({ color: C.body, metalness: 0.55, roughness: 0.32 }),
    trim: new THREE.MeshStandardMaterial({ color: C.trim, metalness: 0.85, roughness: 0.25, emissive: C.trim, emissiveIntensity: 0.12 }),
    steel: new THREE.MeshStandardMaterial({ color: C.steel, metalness: 0.7, roughness: 0.4 }),
    chrome: new THREE.MeshStandardMaterial({ color: 0xCBD5E1, metalness: 1, roughness: 0.18 }),
    visor: new THREE.MeshStandardMaterial({ color: C.dark, metalness: 0.4, roughness: 0.08 }),
    eye: new THREE.MeshBasicMaterial({ color: C.eye }),
    lamp: new THREE.MeshBasicMaterial({ color: C.light }),
    tip: new THREE.MeshBasicMaterial({ color: 0xF5D776 }),
  };

  // Rounded box via an extruded rounded rectangle (no addons needed).
  function roundedBox(w, h, d, r, material) {
    const s = new THREE.Shape();
    const x = -w / 2, y = -h / 2;
    s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
    s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
    s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
    const g = new THREE.ExtrudeGeometry(s, { depth: d - 2 * Math.min(r, d / 3), bevelEnabled: true,
      bevelThickness: Math.min(r, d / 3), bevelSize: Math.min(r, d / 3) * 0.8, bevelSegments: 3, curveSegments: 6 });
    g.center();
    return new THREE.Mesh(g, material);
  }

  const group = new THREE.Group();     // placed in the scene by the caller
  const rig = new THREE.Group();       // rolls along the rail
  group.add(rig);

  // ---- rail under the robot ---------------------------------------------
  const rail = new THREE.Group();
  [-0.36, 0.36].forEach((z) => {
    const r = new THREE.Mesh(new THREE.BoxGeometry(3.2, 0.05, 0.06), mat.chrome);
    r.position.set(0, 0.03, z); rail.add(r);
  });
  for (let i = -7; i <= 7; i++) {
    const sleeper = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.03, 0.95), mat.steel);
    sleeper.position.set(i * 0.21, 0.01, 0); rail.add(sleeper);
  }
  group.add(rail);

  // ---- bogie + wheels ----------------------------------------------------
  const bogie = roundedBox(1.05, 0.2, 0.62, 0.06, mat.steel);
  bogie.position.y = 0.34; rig.add(bogie);
  const wheels = [];
  [[-0.36, -0.36], [0.36, -0.36], [-0.36, 0.36], [0.36, 0.36]].forEach(([x, z]) => {
    const w = new THREE.Group();
    const tyre = new THREE.Mesh(new THREE.CylinderGeometry(0.19, 0.19, 0.1, 24), mat.steel);
    tyre.rotation.x = Math.PI / 2;
    const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 0.12, 16), mat.trim);
    hub.rotation.x = Math.PI / 2;
    const spoke = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.04, 0.115), mat.chrome);
    w.add(tyre, hub, spoke);
    w.position.set(x, 0.24, z);
    rig.add(w); wheels.push(w);
  });

  // ---- body (hips + locomotive torso) ------------------------------------
  const body = new THREE.Group(); body.position.y = 0.46; rig.add(body);
  const hip = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.26, 0.2, 20), mat.steel);
  hip.position.y = 0.08; body.add(hip);

  const torso = new THREE.Group(); torso.position.y = 0.62; body.add(torso);
  const shell = roundedBox(0.95, 0.9, 0.78, 0.16, mat.body);
  torso.add(shell);
  // gold livery stripes across the nose
  [-0.16, -0.26].forEach((y) => {
    const s = new THREE.Mesh(new THREE.BoxGeometry(0.97, 0.045, 0.8), mat.trim);
    s.position.y = y; torso.add(s);
  });
  // headlight
  const lampHousing = new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.13, 0.06, 24), mat.chrome);
  lampHousing.rotation.x = Math.PI / 2; lampHousing.position.set(0, 0.12, 0.41); torso.add(lampHousing);
  const lamp = new THREE.Mesh(new THREE.CircleGeometry(0.1, 24), mat.lamp);
  lamp.position.set(0, 0.12, 0.445); torso.add(lamp);
  const lampLight = new THREE.PointLight(0xFFF1C1, 1.4, 3.2, 2);
  lampLight.position.set(0, 0.12, 0.7); torso.add(lampLight);
  // cowcatcher (pilot)
  const pilotShape = new THREE.Shape();
  pilotShape.moveTo(-0.46, 0); pilotShape.lineTo(0.46, 0); pilotShape.lineTo(0.3, -0.22); pilotShape.lineTo(-0.3, -0.22);
  const pilot = new THREE.Mesh(new THREE.ExtrudeGeometry(pilotShape, { depth: 0.16, bevelEnabled: false }), mat.trim);
  pilot.position.set(0, -0.42, 0.28); torso.add(pilot);
  for (let i = -3; i <= 3; i++) {
    const bar = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.2, 0.03), mat.steel);
    bar.position.set(i * 0.1, -0.52, 0.45); bar.rotation.x = -0.35; torso.add(bar);
  }
  // number plate
  const plate = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.1, 0.02), mat.visor);
  plate.position.set(0, 0.34, 0.405); torso.add(plate);
  const plateGlow = new THREE.Mesh(new THREE.PlaneGeometry(0.26, 0.04), new THREE.MeshBasicMaterial({ color: 0x60A5FA }));
  plateGlow.position.set(0, 0.34, 0.417); torso.add(plateGlow);

  // ---- head (driver's cab) -------------------------------------------------
  const neck = new THREE.Group(); neck.position.y = 0.52; torso.add(neck);
  const head = new THREE.Group(); head.position.y = 0.27; neck.add(head);
  head.add(roundedBox(0.78, 0.5, 0.62, 0.14, mat.body));
  const roof = roundedBox(0.84, 0.08, 0.68, 0.035, mat.trim);
  roof.position.y = 0.27; head.add(roof);
  const visor = roundedBox(0.62, 0.26, 0.06, 0.05, mat.visor);
  visor.position.set(0, 0.02, 0.3); head.add(visor);
  const eyes = [];
  [-0.14, 0.14].forEach((x) => {
    const e = new THREE.Mesh(new THREE.CapsuleGeometry(0.045, 0.05, 4, 10), mat.eye);
    e.rotation.z = Math.PI / 2; e.position.set(x, 0.02, 0.34); head.add(e); eyes.push(e);
  });
  // smokestack
  const stack = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.06, 0.2, 16), mat.steel);
  stack.position.set(-0.22, 0.4, -0.05); head.add(stack);
  const stackRim = new THREE.Mesh(new THREE.TorusGeometry(0.085, 0.02, 8, 20), mat.trim);
  stackRim.rotation.x = Math.PI / 2; stackRim.position.set(-0.22, 0.5, -0.05); head.add(stackRim);
  // pantograph antenna
  const panto = new THREE.Group(); panto.position.set(0.2, 0.31, -0.05); head.add(panto);
  const pantoLow = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.26, 0.03), mat.chrome);
  pantoLow.position.y = 0.13; pantoLow.rotation.z = 0.5; panto.add(pantoLow);
  const pantoHigh = new THREE.Group(); pantoHigh.position.set(-0.06, 0.24, 0); panto.add(pantoHigh);
  const pantoArm = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.24, 0.03), mat.chrome);
  pantoArm.position.y = 0.11; pantoArm.rotation.z = -0.55; pantoHigh.add(pantoArm);
  const pantoBar = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.025, 0.05), mat.trim);
  pantoBar.position.set(0.06, 0.22, 0); pantoHigh.add(pantoBar);
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.035, 12, 12), mat.tip);
  tip.position.set(0.2, 0.23, 0); pantoHigh.add(tip);

  // ---- arms (pivot +Z points along the arm) ---------------------------------
  function makeArm(side) {
    const shoulder = new THREE.Group();
    shoulder.position.set(side * 0.56, 0.24, 0);
    torso.add(shoulder);
    const joint = new THREE.Mesh(new THREE.SphereGeometry(0.11, 16, 16), mat.trim);
    shoulder.add(joint);
    const upper = new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.07, 0.36, 14), mat.steel);
    upper.rotation.x = Math.PI / 2; upper.position.z = 0.2; shoulder.add(upper);
    const piston = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.22, 10), mat.chrome);
    piston.rotation.x = Math.PI / 2; piston.position.z = 0.4; shoulder.add(piston);
    const elbow = new THREE.Group(); elbow.position.z = 0.44; shoulder.add(elbow);
    const eJoint = new THREE.Mesh(new THREE.SphereGeometry(0.075, 12, 12), mat.body);
    elbow.add(eJoint);
    const fore = new THREE.Mesh(new THREE.CylinderGeometry(0.065, 0.06, 0.3, 14), mat.body);
    fore.rotation.x = Math.PI / 2; fore.position.z = 0.17; elbow.add(fore);
    const hand = new THREE.Group(); hand.position.z = 0.36; elbow.add(hand);
    const palm = roundedBox(0.15, 0.1, 0.12, 0.03, mat.trim);
    hand.add(palm);
    [-0.045, 0.045].forEach((x) => {
      const claw = new THREE.Mesh(new THREE.BoxGeometry(0.035, 0.035, 0.1), mat.chrome);
      claw.position.set(x, 0, 0.09); hand.add(claw);
    });
    return { shoulder, elbow, rest: new THREE.Quaternion(), side };
  }
  const armL = makeArm(-1), armR = makeArm(1);
  // Resting pose: arms hang down and slightly out.
  [armL, armR].forEach((a) => {
    a.shoulder.rotation.set(Math.PI / 2 - 0.08, 0, a.side * 0.18);
    a.rest.copy(a.shoulder.quaternion);
  });

  // ---- steam puffs -----------------------------------------------------------
  const puffTex = (() => {
    const c = document.createElement('canvas'); c.width = c.height = 64;
    const g = c.getContext('2d');
    const grd = g.createRadialGradient(32, 32, 2, 32, 32, 32);
    grd.addColorStop(0, 'rgba(255,255,255,.9)'); grd.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grd; g.fillRect(0, 0, 64, 64);
    return new THREE.CanvasTexture(c);
  })();
  const puffs = [];
  for (let i = 0; i < 8; i++) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: puffTex, color: 0xE0F2FE, transparent: true, opacity: 0, depthWrite: false }));
    s.visible = false; group.add(s); puffs.push({ s, life: 1 });
  }
  let puffTimer = 0;

  // ---- contact shadow ----------------------------------------------------------
  const shadow = new THREE.Mesh(new THREE.CircleGeometry(0.75, 32),
    new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.35, depthWrite: false }));
  shadow.rotation.x = -Math.PI / 2; shadow.position.y = 0.005; rig.add(shadow);

  // ---- animation state -----------------------------------------------------------
  let gestureState = null;          // { name, t0, dur, target }
  let blinkAt = 2, clockT = 0, lastX = 0;
  const q = new THREE.Quaternion(), qTarget = new THREE.Quaternion();
  const eUp = new THREE.Euler(-Math.PI / 2 + 0.25, 0, 0);   // arm raised overhead
  const upQuat = (side) => new THREE.Quaternion().setFromEuler(new THREE.Euler(-Math.PI / 2 + 0.15, 0, side * 0.35));
  const ease = (x) => x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2;
  const envelope = (p) => (p < 0.2 ? ease(p / 0.2) : p > 0.8 ? ease((1 - p) / 0.2) : 1);

  const DURATIONS = { wave: 2.4, point: 3.2, nod: 1.6, cheer: 2.2, alert: 2.4 };
  function gesture(name, o = {}) {
    gestureState = { name, t0: clockT, dur: DURATIONS[name] || 2, target: o.target || null };
  }

  function aimQuat(arm, target) {
    // Temporarily look at the target (+Z faces it), read, restore.
    const saved = arm.shoulder.quaternion.clone();
    arm.shoulder.lookAt(target);
    const out = arm.shoulder.quaternion.clone();
    arm.shoulder.quaternion.copy(saved);
    return out;
  }

  function update(dt, t, o = {}) {
    clockT = t;
    // Roll back and forth on the rail; wheels spin with the distance travelled.
    const roam = o.roam ?? 0.55;
    const x = Math.sin(t * 0.45) * roam;
    rig.position.x = x;
    const dx = x - lastX; lastX = x;
    wheels.forEach((w) => { w.rotation.z -= dx / 0.19; });

    // Idle life: bob, sway, antenna, headlight, blink.
    body.position.y = 0.46 + Math.sin(t * 2.2) * 0.025;
    torso.rotation.z = -dx * 1.6 + Math.sin(t * 1.1) * 0.02;
    panto.rotation.z = Math.sin(t * 1.3) * 0.12;
    pantoHigh.rotation.z = Math.sin(t * 1.3 + 0.6) * 0.18;
    tip.material.color.setHex(Math.sin(t * 5) > 0 ? 0xF5D776 : 0x7C5E0E);
    const yaw = THREE.MathUtils.clamp((o.lookX ?? 0) * 0.6, -0.6, 0.6);
    neck.rotation.y += (yaw - neck.rotation.y) * 0.08;
    neck.rotation.x = 0;
    if (t > blinkAt) {
      const k = (t - blinkAt) / 0.14;
      const s = k < 1 ? Math.max(0.12, Math.abs(1 - 2 * k)) : 1;
      eyes.forEach((e) => e.scale.set(s, 1, 1));   // capsule is rotated: local X is vertical
      if (k >= 1) blinkAt = t + 2.5 + Math.random() * 3;
    }

    // Arms: idle swing, then blend towards the active gesture.
    [armL, armR].forEach((a, i) => {
      const swing = Math.sin(t * 2.2 + i * Math.PI) * 0.06 - dx * 2;
      q.copy(a.rest).multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(swing, 0, 0)));
      a.shoulder.quaternion.copy(q);
      a.elbow.rotation.x = -0.25;
    });
    let eyeColor = C.eye, lampColor = C.light, lampPower = 1.2 + Math.sin(t * 3) * 0.2;

    if (gestureState) {
      const p = (t - gestureState.t0) / gestureState.dur;
      if (p >= 1) { gestureState = null; }
      else {
        const w = envelope(p), g = gestureState.name;
        if (g === 'wave') {
          qTarget.copy(upQuat(1));
          armR.shoulder.quaternion.slerp(qTarget, w);
          armR.elbow.rotation.x = -0.25 - w * (0.5 + Math.sin(t * 12) * 0.45);
          neck.rotation.z = Math.sin(t * 4) * 0.08 * w;
        } else if (g === 'point' && gestureState.target) {
          armR.shoulder.quaternion.slerp(aimQuat(armR, gestureState.target), w);
          armR.elbow.rotation.x = -0.25 * (1 - w);
          const local = torso.worldToLocal(gestureState.target.clone());
          neck.rotation.y += (Math.atan2(local.x, local.z) * 0.8 - neck.rotation.y) * 0.1 * w;
        } else if (g === 'nod') {
          neck.rotation.x = Math.sin(p * Math.PI * 4) * 0.22 * w;
        } else if (g === 'cheer') {
          armL.shoulder.quaternion.slerp(upQuat(-1), w);
          armR.shoulder.quaternion.slerp(upQuat(1), w);
          armL.elbow.rotation.x = armR.elbow.rotation.x = -0.2 - Math.abs(Math.sin(t * 8)) * 0.4 * w;
          body.position.y += Math.abs(Math.sin(t * 8)) * 0.08 * w;
        } else if (g === 'alert') {
          const on = Math.sin(t * 14) > 0;
          eyeColor = on ? 0xF87171 : 0x7F1D1D;
          lampColor = on ? 0xF87171 : 0x450A0A;
          lampPower = on ? 2.6 : 0.4;
          armL.shoulder.quaternion.slerp(aimQuat(armL, torso.localToWorld(new THREE.Vector3(-0.4, 1.4, 0.6))), w * 0.9);
        }
      }
    }
    mat.eye.color.setHex(eyeColor);
    mat.lamp.color.setHex(lampColor);
    lampLight.color.setHex(lampColor);
    lampLight.intensity = lampPower;

    // Steam from the stack.
    puffTimer -= dt;
    if (puffTimer <= 0) {
      puffTimer = 0.55;
      const free = puffs.find((pf) => !pf.s.visible);
      if (free) {
        stack.getWorldPosition(free.s.position);
        group.worldToLocal(free.s.position);
        free.s.position.y += 0.12;
        free.life = 0; free.s.visible = true;
      }
    }
    puffs.forEach((pf) => {
      if (!pf.s.visible) return;
      pf.life += dt / 1.8;
      if (pf.life >= 1) { pf.s.visible = false; return; }
      pf.s.position.y += dt * 0.45; pf.s.position.x -= dt * 0.12;
      const sc = 0.12 + pf.life * 0.45;
      pf.s.scale.set(sc, sc, 1);
      pf.s.material.opacity = 0.55 * (1 - pf.life);
    });
  }

  // World position just above the head, for speech bubbles.
  function headAnchor(v = new THREE.Vector3()) {
    return head.localToWorld(v.set(0, 0.62, 0));
  }

  return { group, update, gesture, headAnchor, rig };
}
