"use client";

import { useMemo, useRef, useState, useEffect } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Environment, ContactShadows } from "@react-three/drei";
import * as THREE from "three";
import { motion, useScroll, useTransform } from "framer-motion";
import { PiTrainBold } from "react-icons/pi";

class HeartCurve extends THREE.Curve<THREE.Vector3> {
  constructor() {
    super();
  }
  getPoint(t: number, optionalTarget = new THREE.Vector3()) {
    t = t * Math.PI * 2;
    const x = 16 * Math.pow(Math.sin(t), 3);
    const y =
      13 * Math.cos(t) -
      5 * Math.cos(2 * t) -
      2 * Math.cos(3 * t) -
      Math.cos(4 * t);
    return optionalTarget.set(x * 0.002, (y + 6) * 0.002, 0);
  }
}

const sharedHeartCurve = new HeartCurve();

function ResponsiveGroup({
  children,
  scale = 1,
}: {
  children: React.ReactNode;
  scale?: number;
}) {
  const { viewport } = useThree();
  const s = Math.min(1.3, viewport.width / 2.8) * scale;
  return <group scale={s}>{children}</group>;
}

function GlassCapsule({
  color,
  power,
  intensity,
}: {
  color: string;
  power: number;
  intensity: number;
}) {
  const materialRef = useRef<THREE.ShaderMaterial>(null);

  const uniforms = useMemo(
    () => ({
      color: { value: new THREE.Color("#ffffff") },
      power: { value: 2.5 },
      intensity: { value: 0.6 },
    }),
    []
  );

  useFrame(() => {
    if (materialRef.current) {
      materialRef.current.uniforms.color.value.set(color);
      materialRef.current.uniforms.power.value = power;
      materialRef.current.uniforms.intensity.value = intensity;
    }
  });

  return (
    <mesh>
      <sphereGeometry args={[0.3, 64, 64, 0, Math.PI * 2, 0, Math.PI]} />
      <shaderMaterial
        ref={materialRef}
        uniforms={uniforms}
        vertexShader={`
          varying vec3 vNormal;
          varying vec3 vViewPosition;
          void main() {
            vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
            vViewPosition = -mvPosition.xyz;
            vNormal = normalize(normalMatrix * normal);
            gl_Position = projectionMatrix * mvPosition;
          }
        `}
        fragmentShader={`
          uniform vec3 color;
          uniform float power;
          uniform float intensity;
          varying vec3 vNormal;
          varying vec3 vViewPosition;
          void main() {
            vec3 normal = normalize(vNormal);
            vec3 viewDir = normalize(vViewPosition);
            float fresnel = 1.0 - max(dot(viewDir, normal), 0.0);
            fresnel = pow(fresnel, power);
            gl_FragColor = vec4(color, fresnel * intensity);
          }
        `}
        transparent={true}
        blending={THREE.AdditiveBlending}
        depthWrite={false}
      />
    </mesh>
  );
}

const earBaseMat = new THREE.MeshStandardMaterial({
  color: "#f0f0f0",
  roughness: 0.5,
});
const earRingMat = new THREE.MeshStandardMaterial({
  color: "#ffffff",
  roughness: 0.3,
});
const earCenterMat = new THREE.MeshStandardMaterial({
  color: "#cccccc",
  roughness: 0.8,
});
const antennaBaseMat = new THREE.MeshStandardMaterial({
  color: "#999999",
  roughness: 0.4,
  metalness: 0.5,
});
const antennaStickMat = new THREE.MeshStandardMaterial({
  color: "#d0d0d0",
  roughness: 0.4,
  metalness: 0.2,
});
const antennaTipMat = new THREE.MeshStandardMaterial({
  color: "#00c6ff",
  roughness: 0.2,
  toneMapped: false,
});

function RobotEar({
  position,
  scale = 1,
  isLeft = false,
}: {
  position: [number, number, number];
  scale?: number;
  isLeft?: boolean;
}) {
  const dir = isLeft ? -1 : 1;
  return (
    <group position={position} scale={scale}>
      <mesh rotation={[0, 0, Math.PI / 2]} castShadow receiveShadow material={earBaseMat}>
        <cylinderGeometry args={[0.04, 0.04, 0.025, 32]} />
      </mesh>
      <mesh position={[dir * 0.012, 0, 0]} rotation={[0, 0, Math.PI / 2]} castShadow receiveShadow material={earRingMat}>
        <torusGeometry args={[0.032, 0.008, 16, 32]} />
      </mesh>
      <mesh position={[dir * 0.012, 0, 0]} rotation={[0, 0, Math.PI / 2]} castShadow receiveShadow material={earCenterMat}>
        <cylinderGeometry args={[0.03, 0.03, 0.005, 32]} />
      </mesh>
      <group position={[dir * 0.015, 0.035, 0]} rotation={[-0.4, 0, 0]}>
        <mesh position={[0, 0.01, 0]} castShadow receiveShadow material={antennaBaseMat}>
          <cylinderGeometry args={[0.006, 0.008, 0.02, 16]} />
        </mesh>
        <mesh position={[0, 0.06, 0]} castShadow receiveShadow material={antennaStickMat}>
          <cylinderGeometry args={[0.003, 0.003, 0.1, 8]} />
        </mesh>
        <mesh position={[0, 0.11, 0]} castShadow receiveShadow material={antennaTipMat}>
          <sphereGeometry args={[0.006, 16, 16]} />
        </mesh>
      </group>
    </group>
  );
}

const eyeMat = new THREE.MeshBasicMaterial({
  color: new THREE.Color(2, 2, 2),
  toneMapped: false,
  transparent: true,
});
const heartMat = new THREE.MeshBasicMaterial({
  color: "#00c6ff",
  toneMapped: false,
});

function RobotEye({
  position,
  rotation,
  scale = 1,
  blinkDuration = 0.15,
  blinkCycle = 3.0,
  isLovedRef,
}: {
  position: [number, number, number];
  rotation: [number, number, number];
  scale?: number;
  blinkDuration?: number;
  blinkCycle?: number;
  isLovedRef: React.MutableRefObject<boolean>;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const normalEyesRef = useRef<THREE.Group>(null);
  const heartEyeRef = useRef<THREE.Mesh>(null);

  useFrame(({ clock }) => {
    if (!groupRef.current || !normalEyesRef.current || !heartEyeRef.current) return;
    const isHeart = isLovedRef.current;
    normalEyesRef.current.visible = !isHeart;
    heartEyeRef.current.visible = isHeart;
    const cycle = clock.getElapsedTime() % blinkCycle;
    let targetScaleY = 1;
    if (cycle < blinkDuration && !isHeart) {
      const progress = cycle / blinkDuration;
      const blinkClose = Math.sin(progress * Math.PI);
      targetScaleY = Math.max(0.05, 1.0 - blinkClose);
    }
    groupRef.current.scale.set(scale, scale * targetScaleY, scale);
  });

  const { topPath, bottomPath } = useMemo(() => {
    const w = 0.025, h = 0.035, r = 0.02, g = 0.005;
    const tPath = new THREE.CurvePath<THREE.Vector3>();
    tPath.add(new THREE.LineCurve3(new THREE.Vector3(-w, g, 0), new THREE.Vector3(-w, h - r, 0)));
    tPath.add(new THREE.QuadraticBezierCurve3(new THREE.Vector3(-w, h - r, 0), new THREE.Vector3(-w, h, 0), new THREE.Vector3(-w + r, h, 0)));
    tPath.add(new THREE.LineCurve3(new THREE.Vector3(-w + r, h, 0), new THREE.Vector3(w - r, h, 0)));
    tPath.add(new THREE.QuadraticBezierCurve3(new THREE.Vector3(w - r, h, 0), new THREE.Vector3(w, h, 0), new THREE.Vector3(w, h - r, 0)));
    tPath.add(new THREE.LineCurve3(new THREE.Vector3(w, h - r, 0), new THREE.Vector3(w, g, 0)));
    const bPath = new THREE.CurvePath<THREE.Vector3>();
    bPath.add(new THREE.LineCurve3(new THREE.Vector3(-w, -g, 0), new THREE.Vector3(-w, -(h - r), 0)));
    bPath.add(new THREE.QuadraticBezierCurve3(new THREE.Vector3(-w, -(h - r), 0), new THREE.Vector3(-w, -h, 0), new THREE.Vector3(-w + r, -h, 0)));
    bPath.add(new THREE.LineCurve3(new THREE.Vector3(-w + r, -h, 0), new THREE.Vector3(w - r, -h, 0)));
    bPath.add(new THREE.QuadraticBezierCurve3(new THREE.Vector3(w - r, -h, 0), new THREE.Vector3(w, -h, 0), new THREE.Vector3(w, -(h - r), 0)));
    bPath.add(new THREE.LineCurve3(new THREE.Vector3(w, -(h - r), 0), new THREE.Vector3(w, -g, 0)));
    return { topPath: tPath, bottomPath: bPath };
  }, []);

  return (
    <group ref={groupRef} position={position} rotation={rotation} scale={scale}>
      <mesh ref={heartEyeRef} visible={false} material={heartMat}>
        <tubeGeometry args={[sharedHeartCurve, 64, 0.0035, 8, true]} />
      </mesh>
      <group ref={normalEyesRef}>
        <mesh material={eyeMat}>
          <tubeGeometry args={[topPath, 20, 0.0035, 8, false]} />
        </mesh>
        <mesh material={eyeMat}>
          <tubeGeometry args={[bottomPath, 20, 0.0035, 8, false]} />
        </mesh>
      </group>
    </group>
  );
}

function generatePbrTexturesAsync(): Promise<{
  colorMap: THREE.CanvasTexture;
  bumpMap: THREE.CanvasTexture;
}> {
  return new Promise((resolve) => {
    setTimeout(() => {
      const size = 512;
      const canvasC = document.createElement("canvas");
      const canvasB = document.createElement("canvas");
      canvasC.width = canvasB.width = size;
      canvasC.height = canvasB.height = size;
      const ctxC = canvasC.getContext("2d");
      const ctxB = canvasB.getContext("2d");
      if (ctxC && ctxB) {
        ctxC.fillStyle = "#dcdcdc";
        ctxC.fillRect(0, 0, size, size);
        ctxB.fillStyle = "#808080";
        ctxB.fillRect(0, 0, size, size);
        for (let i = 0; i < 10000; i++) {
          const x = Math.random() * size;
          const y = Math.random() * size;
          const r = 0.5 + Math.random() * 1.5;
          const isDark = Math.random() > 0.15;
          ctxC.beginPath(); ctxC.arc(x, y, r, 0, Math.PI * 2);
          ctxC.fillStyle = isDark ? "#222222" : "#dddddd"; ctxC.fill();
          ctxB.beginPath(); ctxB.arc(x, y, r, 0, Math.PI * 2);
          ctxB.fillStyle = isDark ? "#000000" : "#ffffff"; ctxB.fill();
        }
      }
      const texC = new THREE.CanvasTexture(canvasC);
      const texB = new THREE.CanvasTexture(canvasB);
      texC.wrapS = texB.wrapS = THREE.RepeatWrapping;
      texC.wrapT = texB.wrapT = THREE.RepeatWrapping;
      texC.repeat.set(6, 3); texB.repeat.set(6, 3);
      texC.needsUpdate = true; texB.needsUpdate = true;
      resolve({ colorMap: texC, bumpMap: texB });
    }, 0);
  });
}

function RobotPrototype({
  neckParams = { baseR:0.25,baseH:-0.01,midR:0.23,midH:0.02,lipBottomR:0.27,lipBottomH:0.025,lipTopR:0.28,lipTopH:0.05,innerR:0.24,innerDropH:0.03 },
  bodyParams = { bodyBevelR:0.21,bodyBevelY:0.38,bodyBevelT:0.015 },
  color = "#c4c4c4",
  pantallaColor = "#00c6ff",
  pantallaBrillo = 1.4,
  blinkCycle = 3.0,
  metalness = 0.0,
  screenPosRef,
}: {
  neckParams?: Record<string, number>;
  bodyParams?: Record<string, number>;
  color?: string;
  pantallaColor?: string;
  pantallaBrillo?: number;
  blinkCycle?: number;
  metalness?: number;
  screenPosRef?: React.MutableRefObject<{ x: number; y: number }>;
}) {
  const isLovedRef = useRef(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const bodyRef = useRef<THREE.Group>(null);
  const headRef = useRef<THREE.Group>(null);
  const _projVec = useRef(new THREE.Vector3());

  const [textures, setTextures] = useState<{
    colorMap: THREE.CanvasTexture | null;
    bumpMap: THREE.CanvasTexture | null;
  }>({ colorMap: null, bumpMap: null });

  const design = {
    pantallaColor,
    pantallaGrosor: 3.8,
    pantallaBrillo,
    separacionOjos: 0.07,
    tamañoOrejas: 1.3,
    escalaOjos: 1.1,
    parpadeoFrecuencia: blinkCycle,
    parpadeoDuracion: 0.45,
    colorChasis: color,
    alturaCabeza: 0.6,
  };

  const config = { moveSpeed:0.35, bodyRotSpeed:10.0, headRotSpeed:20.0, bodyTiltX:0.0, bodyTiltY:0.95, headLookX:0.3, headLookY:1.8 };

  useFrame((state, delta) => {
    if (!bodyRef.current || !headRef.current) return;
    const dt = Math.min(delta, 0.1);
    const tx = state.pointer.x, ty = state.pointer.y;
    const maxMoveX = state.viewport.width / 3.5;
    bodyRef.current.position.x = THREE.MathUtils.lerp(bodyRef.current.position.x, tx * maxMoveX, config.moveSpeed * dt);
    const relativeX = tx - bodyRef.current.position.x / 2.5;
    bodyRef.current.rotation.y = THREE.MathUtils.lerp(bodyRef.current.rotation.y, -relativeX * config.bodyTiltY, config.bodyRotSpeed * dt);
    bodyRef.current.rotation.x = THREE.MathUtils.lerp(bodyRef.current.rotation.x, relativeX * relativeX * config.bodyTiltX - ty * 0.25, config.bodyRotSpeed * dt);
    bodyRef.current.rotation.z = THREE.MathUtils.lerp(bodyRef.current.rotation.z, -relativeX * 0.15, config.bodyRotSpeed * dt);
    headRef.current.rotation.y = THREE.MathUtils.lerp(headRef.current.rotation.y, relativeX * config.headLookY, config.headRotSpeed * dt);
    headRef.current.rotation.x = THREE.MathUtils.lerp(headRef.current.rotation.x, -ty * config.headLookX, config.headRotSpeed * dt);

    // Project head world position → bubble screen %
    if (screenPosRef) {
      headRef.current.getWorldPosition(_projVec.current);
      _projVec.current.x += 0.52;
      _projVec.current.y += 0.08;
      _projVec.current.project(state.camera);
      screenPosRef.current = {
        x: (_projVec.current.x * 0.5 + 0.5) * 100,
        y: (-_projVec.current.y * 0.5 + 0.5) * 100,
      };
    }
  });

  useEffect(() => {
    let mounted = true;
    let generatedMaps: { colorMap: THREE.CanvasTexture; bumpMap: THREE.CanvasTexture } | null = null;
    generatePbrTexturesAsync().then((res) => {
      if (mounted) { generatedMaps = res; setTextures(res); }
      else { res.colorMap.dispose(); res.bumpMap.dispose(); }
    });
    return () => {
      mounted = false;
      if (generatedMaps) { generatedMaps.colorMap.dispose(); generatedMaps.bumpMap.dispose(); }
    };
  }, []);

  const handlePointerDown = (e: import("@react-three/fiber").ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    isLovedRef.current = true;
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => { isLovedRef.current = false; }, 2000);
  };

  const neckProfile = useMemo(() => [
    new THREE.Vector2(neckParams.innerR, neckParams.baseH),
    new THREE.Vector2(neckParams.baseR, neckParams.baseH),
    new THREE.Vector2(neckParams.midR, neckParams.midH),
    new THREE.Vector2(neckParams.lipBottomR, neckParams.lipBottomH),
    new THREE.Vector2(neckParams.lipTopR, neckParams.lipTopH),
    new THREE.Vector2(neckParams.innerR, neckParams.lipTopH),
    new THREE.Vector2(neckParams.innerR, neckParams.lipTopH - neckParams.innerDropH),
  ], [neckParams]);

  const headMat = useMemo(() => new THREE.MeshStandardMaterial({ color: "#111111", roughness: 1.0, metalness: 0.0 }), []);

  if (!textures.colorMap) return null;

  return (
    <group ref={bodyRef} position={[0, -0.3, 0]}
      onPointerDown={handlePointerDown}
      onPointerOver={() => (document.body.style.cursor = "pointer")}
      onPointerOut={() => (document.body.style.cursor = "auto")}
    >
      <mesh castShadow receiveShadow>
        <sphereGeometry args={[0.43, 64, 64, 0, Math.PI * 2, Math.PI * 0.15, Math.PI * 0.85]} />
        <meshStandardMaterial color={design.colorChasis} map={textures.colorMap ?? undefined} bumpMap={textures.bumpMap ?? undefined} bumpScale={0.005} roughness={1.0} metalness={metalness} envMapIntensity={0.0} />
      </mesh>

      {bodyParams.bodyBevelT > 0 && (
        <mesh position={[0, bodyParams.bodyBevelY, 0]} rotation={[Math.PI / 2, 0, 0]} castShadow receiveShadow>
          <torusGeometry args={[bodyParams.bodyBevelR, bodyParams.bodyBevelT, 32, 64]} />
          <meshStandardMaterial color={design.colorChasis} map={textures.colorMap ?? undefined} bumpMap={textures.bumpMap ?? undefined} bumpScale={0.005} roughness={1.0} metalness={metalness} envMapIntensity={0.0} />
        </mesh>
      )}

      <mesh position={[0, 0.38, 0]} receiveShadow castShadow>
        <latheGeometry args={[neckProfile, 64]} />
        <meshStandardMaterial color={design.colorChasis} map={textures.colorMap ?? undefined} bumpMap={textures.bumpMap ?? undefined} bumpScale={0.005} roughness={1.0} metalness={metalness} envMapIntensity={0.0} />
      </mesh>

      <group ref={headRef} position={[0, design.alturaCabeza, 0]}>
        <mesh material={headMat} castShadow receiveShadow>
          <sphereGeometry args={[0.28, 64, 64, 0, Math.PI * 2, 0, Math.PI]} />
        </mesh>
        <GlassCapsule color={design.pantallaColor} power={design.pantallaGrosor} intensity={design.pantallaBrillo} />
        <group position={[0, -0.02, 0.29]}>
          <RobotEye position={[-design.separacionOjos, 0, 0]} rotation={[0, -0.2, 0]} scale={design.escalaOjos} blinkDuration={design.parpadeoDuracion} blinkCycle={design.parpadeoFrecuencia} isLovedRef={isLovedRef} />
          <RobotEye position={[design.separacionOjos, 0, 0]} rotation={[0, 0.2, 0]} scale={design.escalaOjos} blinkDuration={design.parpadeoDuracion} blinkCycle={design.parpadeoFrecuencia} isLovedRef={isLovedRef} />
        </group>
        <RobotEar position={[-0.29, 0, 0]} isLeft={true} scale={design.tamañoOrejas} />
        <RobotEar position={[0.29, 0, 0]} isLeft={false} scale={design.tamañoOrejas} />
      </group>
    </group>
  );
}

export interface NavItem {
  label: string;
  href: string;
  target?: string;
}

export interface RobotHeroProps {
  backgroundText?: string;
  navItemsLeft?: NavItem[];
  contactText?: string;
  contactHref?: string;
  contactTarget?: string;
  ctaText?: string;
  onCtaClick?: () => void;
  color?: string;
  scale?: number;
  pantallaColor?: string;
  pantallaBrillo?: number;
  blinkCycle?: number;
  metalness?: number;
}

// ─── Background ──────────────────────────────────────────────────────────────
function HeroBg() {
  return (
    <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 0 }}>
      {/* Subtle dot grid */}
      <div className="absolute inset-0" style={{
        backgroundImage: "radial-gradient(circle, rgba(255,255,255,0.06) 1px, transparent 1px)",
        backgroundSize: "40px 40px",
      }} />
      {/* Bottom fade so section blends into page */}
      <div className="absolute bottom-0 left-0 right-0 h-40" style={{
        background: "linear-gradient(to bottom, transparent, #0a0f1e)",
      }} />
    </div>
  );
}

// ─── Quotes ──────────────────────────────────────────────────────────────────
const QUOTES = [
  "Hi! I'm your RailSense agent. How can I help you today?",
  "I can check live train schedules for any station.",
  "Ask me about delays — I'll know before the board does.",
  "Need a seat? I'll find the best available option.",
  "I monitor engine health across the entire fleet.",
  "Suspicious vibration on DE-1042? I caught it 3 hours ago.",
  "Operations, maintenance, bookings — I handle it all.",
  "Real-time tracking for every locomotive on the network.",
  "I predict faults before they cause disruptions.",
  "Your AI co-pilot for Sri Lanka Railways.",
];

function SpeechBubble({ posRef }: { posRef: React.MutableRefObject<{ x: number; y: number }> }) {
  const [index, setIndex] = useState(0);
  const [visible, setVisible] = useState(true);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Drive bubble position from Three.js projection — no React re-renders
  useEffect(() => {
    let raf: number;
    const sync = () => {
      if (wrapRef.current) {
        wrapRef.current.style.left = `${posRef.current.x}%`;
        wrapRef.current.style.top  = `${posRef.current.y}%`;
      }
      raf = requestAnimationFrame(sync);
    };
    raf = requestAnimationFrame(sync);
    return () => cancelAnimationFrame(raf);
  }, [posRef]);

  useEffect(() => {
    const cycle = setInterval(() => {
      setVisible(false);
      setTimeout(() => {
        setIndex((i) => (i + 1) % QUOTES.length);
        setVisible(true);
      }, 400);
    }, 3800);
    return () => clearInterval(cycle);
  }, []);

  return (
    <div ref={wrapRef} className="absolute max-w-[270px] pointer-events-none"
      style={{ zIndex: 35, transform: "translate(14px, -115%)" }}>
      <motion.div
        animate={{ opacity: visible ? 1 : 0, y: visible ? 0 : -6 }}
        transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
        className="relative rounded-2xl rounded-bl-sm px-5 py-4 text-base leading-snug font-medium text-white"
        style={{
          background: "rgba(10,15,30,0.75)",
          border: "1px solid rgba(0,198,255,0.3)",
          backdropFilter: "blur(16px)",
          boxShadow: "0 4px 24px rgba(0,198,255,0.12)",
        }}
      >
        <span className="block mb-1.5 text-xs font-mono text-[#00c6ff] uppercase tracking-widest font-semibold">
          RailSense AI
        </span>
        {QUOTES[index]}
        <span
          className="absolute -left-2 bottom-3 w-0 h-0"
          style={{
            borderTop: "6px solid transparent",
            borderBottom: "6px solid transparent",
            borderRight: "8px solid rgba(0,198,255,0.3)",
          }}
        />
      </motion.div>
      {/* Pulsing dot indicator */}
      <div className="flex gap-1 mt-2 justify-end pr-1">
        {QUOTES.map((_, i) => (
          <div
            key={i}
            className="rounded-full transition-all duration-300"
            style={{
              width: i === index ? 14 : 4,
              height: 4,
              background: i === index ? "#00c6ff" : "rgba(255,255,255,0.2)",
            }}
          />
        ))}
      </div>
    </div>
  );
}

function AntennaNavbar({
  leftItems,
  contactText,
  contactHref,
  contactTarget,
  ctaText,
  onCtaClick,
}: {
  leftItems: NavItem[];
  contactText: string;
  contactHref: string;
  contactTarget?: string;
  ctaText: string;
  onCtaClick?: () => void;
}) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const { scrollY } = useScroll();
  const lineOpacity = useTransform(scrollY, [0, 50], [1, 0]);

  return (
    <nav className="sticky top-0 z-50 w-full pt-8 px-8 pointer-events-none">
      <div className="w-full max-w-[1400px] mx-auto flex flex-col relative pointer-events-auto">
        <div className="flex flex-col lg:flex-row items-center justify-between relative gap-4 lg:gap-0">

          {/* Left nav items */}
          <div className="flex flex-wrap justify-center lg:justify-start items-center gap-2 sm:gap-3 z-20">
            {leftItems.map((item, idx) => (
              <a key={item.label} href={item.href} target={item.target}
                rel={item.target === "_blank" ? "noopener noreferrer" : undefined}
                onMouseEnter={() => setHoveredIndex(idx)}
                onMouseLeave={() => setHoveredIndex(null)}
                className="relative px-5 py-2 rounded-full bg-white/10 text-white border border-white/20 hover:bg-white/20 backdrop-blur-sm text-sm font-semibold transition-all overflow-hidden"
              >
                {item.label}
                {hoveredIndex === idx && (
                  <motion.div layoutId="navbar-indicator-left"
                    className="absolute inset-0 border-b-[2px] border-[#00c6ff]"
                    transition={{ type: "spring", stiffness: 400, damping: 30 }}
                  />
                )}
              </a>
            ))}
          </div>

          {/* Centre logo mark */}
          <div className="hidden lg:flex absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 items-center justify-center pointer-events-auto cursor-pointer group z-10">
            <div className="relative flex items-center justify-center h-12 w-16">
              <div className="absolute left-2 w-1.5 h-4 bg-zinc-400 rounded-l-md transition-transform duration-300 group-hover:-translate-x-1" />
              <div className="absolute right-2 w-1.5 h-4 bg-zinc-400 rounded-r-md transition-transform duration-300 group-hover:translate-x-1" />
              <div className="z-10 w-10 h-10 bg-white/10 border-2 border-white/20 backdrop-blur-md rounded-[12px] flex items-center justify-center shadow-[0_4px_20px_rgba(0,0,0,0.3)] transition-all duration-300 group-hover:bg-white/20 group-hover:shadow-[0_4px_25px_rgba(0,198,255,0.2)]">
                <div className="w-[70%] h-[60%] bg-[#0a0f1e] rounded-lg flex items-center justify-center gap-1.5 overflow-hidden shadow-[inset_0_2px_4px_rgba(0,0,0,0.8)]">
                  <div className="w-1.5 h-3 bg-[#00c6ff] rounded-[2px] shadow-[0_0_8px_#00c6ff] transition-transform duration-200 group-hover:scale-y-[0.2]" />
                  <div className="w-1.5 h-3 bg-[#00c6ff] rounded-[2px] shadow-[0_0_8px_#00c6ff] transition-transform duration-200 group-hover:scale-y-[0.2]" />
                </div>
              </div>
            </div>
          </div>

          {/* Right actions */}
          <div className="flex flex-wrap justify-center lg:justify-end items-center gap-2 sm:gap-3 w-full lg:w-auto mt-4 lg:mt-0 z-20">
            <a href={contactHref} target={contactTarget}
              rel={contactTarget === "_blank" ? "noopener noreferrer" : undefined}
              className="px-5 py-2 rounded-full bg-white/10 text-white border border-white/20 hover:bg-white/20 backdrop-blur-sm text-sm font-semibold transition-all"
            >
              {contactText}
            </a>
            <button onClick={onCtaClick}
              className="px-5 py-2 rounded-full bg-[#00c6ff] text-black text-sm font-black hover:bg-[#00aee0] transition-colors flex items-center gap-2 shadow-[0_0_20px_rgba(0,198,255,0.4)]"
            >
              {ctaText}
              <PiTrainBold size={18} />
            </button>
          </div>
        </div>

        <motion.div style={{ opacity: lineOpacity }}
          className="w-full mt-6 border-b-2 border-dotted border-white/20"
        />
      </div>
    </nav>
  );
}

export function RobotHero({
  backgroundText = "RAILSENSE AI",
  navItemsLeft = [
    { label: "Overview",    href: "#overview" },
    { label: "Fleet",       href: "#trains" },
    { label: "Passenger",   href: "http://localhost:5280", target: "_blank" },
    { label: "Operations",  href: "http://localhost:9005", target: "_blank" },
    { label: "Maintenance", href: "http://localhost:8006", target: "_blank" },
  ],
  contactText = "GitHub",
  contactHref = "#",
  contactTarget,
  ctaText = "Ask RailSense",
  onCtaClick,
  color = "#c4c4c4",
  scale = 1,
  pantallaColor = "#00c6ff",
  pantallaBrillo = 1.4,
  blinkCycle = 3.0,
  metalness = 0.0,
}: RobotHeroProps = {}) {
  const containerRef = useRef<HTMLElement>(null);
  const robotScreenPosRef = useRef({ x: 62, y: 28 });

  const entorno = {
    fondoArriba: "#0a0f1e",
    fondoMedio: "#0d1525",
    fondoAbajo: "#111827",
    luzAmbiente: 0.75,
    luzPrincipal: 0.0,
    luzPrincipalColor: "#00c6ff",
    luzRelleno: 0.0,
    luzRellenoColor: "#dbdbdb",
    sombraOpacidad: 0.85,
    sombraBlur: 1.7,
  };

  const handleCta = onCtaClick ?? (() => window.open("http://localhost:5280", "_blank"));

  return (
    <section ref={containerRef}
      className="relative w-full h-dvh min-h-[600px] overflow-hidden bg-[#0a0f1e]"
    >
      <HeroBg />

      {/* 3D Canvas — transparent bg so white shows through */}
      <div className="absolute inset-0 z-20">
        <Canvas shadows camera={{ position: [0, 0.2, 5], fov: 40 }}>
          <ambientLight intensity={entorno.luzAmbiente} color="#ffffff" />
          <directionalLight position={[0, 6, 3]} intensity={entorno.luzPrincipal} color={entorno.luzPrincipalColor} castShadow shadow-mapSize={[2048, 2048]} shadow-bias={-0.0005}>
            <orthographicCamera attach="shadow-camera" args={[-1.5, 1.5, 1.5, -1.5, 0.1, 20]} />
          </directionalLight>
          <directionalLight position={[-5, 2, -5]} intensity={entorno.luzRelleno} color={entorno.luzRellenoColor} />
          <Environment preset="studio" blur={0.5} />
          <ResponsiveGroup scale={scale}>
            <ContactShadows position={[0, -0.79, 0]} opacity={0.85} scale={15} resolution={1024} blur={1.7} far={2.5} color="#000000" />
            <RobotPrototype
              neckParams={{ baseR:0.215,baseH:-0.05,midR:0.28,midH:0.02,lipBottomR:0.295,lipBottomH:0.045,lipTopR:0.27,lipTopH:0.055,innerR:0.1,innerDropH:0.0 }}
              bodyParams={{ bodyBevelR:0.235,bodyBevelY:0.34,bodyBevelT:0.025 }}
              color={color} pantallaColor={pantallaColor} pantallaBrillo={pantallaBrillo} blinkCycle={blinkCycle} metalness={metalness}
              screenPosRef={robotScreenPosRef}
            />
          </ResponsiveGroup>
        </Canvas>
      </div>

      {/* Speech bubble — tracks robot head via projected screen coords */}
      <SpeechBubble posRef={robotScreenPosRef} />

      {/* Overlay UI */}
      <div className="absolute inset-0 z-30 pointer-events-none flex flex-col">
        <AntennaNavbar leftItems={navItemsLeft} contactText={contactText} contactHref={contactHref} contactTarget={contactTarget} ctaText={ctaText} onCtaClick={handleCta} />
        <div className="relative w-full max-w-[1400px] mx-auto px-8 flex-1 flex flex-col">
          {/* Hero tagline bottom-left */}
          <div className="mt-auto pb-16 pointer-events-auto">
            <p className="text-white/40 text-xs font-mono uppercase tracking-widest mb-2">Sri Lanka Railways · IT3041</p>
            <h2 className="text-white text-4xl sm:text-5xl font-black leading-tight tracking-tight">
              Intelligence<br />
              <span className="text-[#00c6ff]">on the Rails.</span>
            </h2>
            <p className="text-white/50 text-sm mt-3 max-w-xs">4-agent AI system for passenger assistance, operations, booking, and maintenance.</p>
          </div>
        </div>
      </div>
    </section>
  );
}

export default RobotHero;
