import React, { useMemo } from 'react';
import './rail-scene.css';

interface RailSceneProps {
  boost?: boolean;
}

function useStars(count: number) {
  return useMemo(
    () =>
      Array.from({ length: count }, (_, i) => ({
        left: ((i * 53.7) % 100).toFixed(2),
        top: ((i * 31.3) % 60).toFixed(2),
        size: 1 + ((i * 7) % 3),
        delay: ((i * 0.37) % 4).toFixed(2),
        duration: (2.4 + ((i * 0.53) % 2.6)).toFixed(2),
      })),
    [count]
  );
}

const SkylineFar: React.FC = () => (
  <svg
    className="rs-skyline-svg"
    viewBox="0 0 1200 220"
    preserveAspectRatio="none"
    aria-hidden="true"
  >
    <path
      d="M0,220 L0,150 L60,150 L60,120 L90,120 L90,150 L160,150 L160,90 L180,90 L180,60
         Q180,40 200,40 Q220,40 220,60 L220,90 L240,90 L240,150 L320,150 L320,110 L360,110 L360,150
         L460,150 L460,130 L500,130 L500,150 L620,150 L620,100 L660,100 L660,150 L760,150 L760,120
         L800,120 L800,150 L900,150 L900,95 L940,95 L940,150 L1040,150 L1040,115 L1080,115 L1080,150
         L1200,150 L1200,220 Z"
      fill="var(--rs-far-fill)"
    />
    {/* Lotus Tower silhouette */}
    <g fill="var(--rs-far-fill)">
      <rect x="196" y="18" width="8" height="90" rx="2" />
      <ellipse cx="200" cy="34" rx="20" ry="9" />
      <ellipse cx="200" cy="52" rx="15" ry="7" />
      <ellipse cx="200" cy="68" rx="10" ry="5" />
      <circle cx="200" cy="12" r="4" />
    </g>
  </svg>
);

const HillsMidBridge: React.FC = () => (
  <svg
    className="rs-skyline-svg"
    viewBox="0 0 1400 260"
    preserveAspectRatio="none"
    aria-hidden="true"
  >
    <path
      d="M0,260 L0,190 Q80,150 160,190 Q260,230 360,180 Q460,140 560,185 Q660,225 760,190
         Q860,150 960,195 Q1060,230 1160,185 Q1260,150 1400,190 L1400,260 Z"
      fill="var(--rs-mid-fill)"
    />
    {/* Nine Arches Bridge */}
    <g fill="none" stroke="var(--rs-mid-fill)" strokeWidth="10">
      <path d="M640,230 L640,150 Q670,120 700,150 L700,230" />
      <path d="M700,230 L700,150 Q730,120 760,150 L760,230" />
      <path d="M760,230 L760,150 Q790,120 820,150 L820,230" />
      <path d="M820,230 L820,150 Q850,120 880,150 L880,230" />
      <path d="M880,230 L880,150 Q910,120 940,150 L940,230" />
    </g>
    <rect x="632" y="222" width="316" height="10" fill="var(--rs-mid-fill)" />
  </svg>
);

const TrackStrip: React.FC = () => (
  <svg
    className="rs-track-svg"
    viewBox="0 0 800 80"
    preserveAspectRatio="none"
    aria-hidden="true"
  >
    <rect x="0" y="0" width="800" height="80" fill="transparent" />
    {Array.from({ length: 16 }, (_, i) => (
      <rect key={i} x={i * 50 + 10} y="18" width="14" height="44" rx="2" fill="var(--rs-sleeper-fill)" />
    ))}
    <rect x="0" y="24" width="800" height="6" rx="3" fill="var(--rs-rail-fill)" />
    <rect x="0" y="50" width="800" height="6" rx="3" fill="var(--rs-rail-fill)" />
    <g stroke="var(--rs-pole-fill)" strokeWidth="3" strokeLinecap="round">
      <line x1="90" y1="0" x2="90" y2="20" />
      <line x1="78" y1="6" x2="102" y2="6" />
      <line x1="410" y1="0" x2="410" y2="20" />
      <line x1="398" y1="6" x2="422" y2="6" />
      <line x1="730" y1="0" x2="730" y2="20" />
      <line x1="718" y1="6" x2="742" y2="6" />
    </g>
  </svg>
);

const COACH_W = 250;
const COACH_GAP = 26;
const COACH_COUNT = 5;
const COACH_H = 92;
const COACH_Y = 30;

const Wheel: React.FC<{ cx: number }> = ({ cx }) => {
  const cy = COACH_Y + COACH_H - 4;
  return (
    <g className="rs-wheel">
      <circle cx={cx} cy={cy} r="11" fill="var(--rs-train-wheel)" />
      <circle cx={cx} cy={cy - 4} r="2.4" fill="var(--rs-train-hubcap)" />
    </g>
  );
};

const Coach: React.FC<{ index: number; isLead: boolean }> = ({ index, isLead }) => {
  const x = index * (COACH_W + COACH_GAP);
  const bodyPath = isLead
    ? `M${x},${COACH_Y + COACH_H} L${x},${COACH_Y + 14} Q${x},${COACH_Y} ${x + 14},${COACH_Y}
       L${x + COACH_W - 40},${COACH_Y} Q${x + COACH_W + 6},${COACH_Y} ${x + COACH_W + 6},${COACH_Y + 26}
       L${x + COACH_W + 6},${COACH_Y + COACH_H - 14} Q${x + COACH_W + 6},${COACH_Y + COACH_H} ${x + COACH_W - 8},${COACH_Y + COACH_H} Z`
    : `M${x},${COACH_Y + COACH_H} L${x},${COACH_Y + 14} Q${x},${COACH_Y} ${x + 14},${COACH_Y}
       L${x + COACH_W - 14},${COACH_Y} Q${x + COACH_W},${COACH_Y} ${x + COACH_W},${COACH_Y + 14}
       L${x + COACH_W},${COACH_Y + COACH_H} Z`;

  const windowCount = isLead ? 3 : 4;
  const windowSpan = isLead ? COACH_W - 60 : COACH_W - 30;

  return (
    <g>
      <path d={bodyPath} fill={isLead ? 'var(--rs-train-nose)' : 'var(--rs-train-body)'} />
      <rect x={x + 8} y={COACH_Y} width={COACH_W - 16} height="6" fill="var(--rs-train-roof)" />
      {Array.from({ length: windowCount }, (_, i) => (
        <rect
          key={i}
          x={x + 20 + i * (windowSpan / windowCount)}
          y={COACH_Y + 16}
          width={windowSpan / windowCount - 12}
          height="26"
          rx="5"
          fill="var(--rs-train-window)"
          className="rs-window"
          style={{ animationDelay: `${((index * 4 + i) * 0.28).toFixed(2)}s` }}
        />
      ))}
      <rect x={x + 8} y={COACH_Y + COACH_H - 16} width={COACH_W - 16} height="7" fill="var(--rs-train-band)" />
      <Wheel cx={x + 46} />
      <Wheel cx={x + COACH_W - 46} />
    </g>
  );
};

const SignalPost: React.FC = () => (
  <g className="rs-signal-post">
    <rect x="-3" y="-56" width="6" height="56" fill="var(--rs-pole-fill)" />
    <rect x="-14" y="-90" width="28" height="34" rx="6" fill="#1b2634" />
    <circle className="rs-signal-lamp" cx="0" cy="-73" r="8" />
  </g>
);

const TrainSvg: React.FC = () => {
  const totalW = COACH_COUNT * COACH_W + (COACH_COUNT - 1) * COACH_GAP + 10;
  return (
    <svg
      className="rs-train-svg"
      viewBox={`0 0 ${totalW} 140`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <ellipse cx={totalW / 2} cy="126" rx={totalW / 2 - 20} ry="8" fill="rgba(0,0,0,0.25)" />
      {Array.from({ length: COACH_COUNT }, (_, i) => (
        <Coach key={i} index={i} isLead={i === COACH_COUNT - 1} />
      ))}
      <g transform={`translate(${2 * (COACH_W + COACH_GAP) + COACH_W + 10}, ${COACH_Y + COACH_H})`}>
        <SignalPost />
      </g>
      <circle cx={totalW - 14} cy={COACH_Y + 46} r="5" fill="var(--rs-headlight-core)" />
    </svg>
  );
};

const RailScene: React.FC<RailSceneProps> = ({ boost = false }) => {
  const stars = useStars(46);

  return (
    <div className={`rail-scene${boost ? ' rail-scene--boost' : ''}`} aria-hidden="true">
      <div className="rs-sky">
        <div className="rs-sun-glow" />
        <div className="rs-stars">
          {stars.map((s, i) => (
            <span
              key={i}
              className="rs-star"
              style={{
                left: `${s.left}%`,
                top: `${s.top}%`,
                width: s.size,
                height: s.size,
                animationDelay: `${s.delay}s`,
                animationDuration: `${s.duration}s`,
              }}
            />
          ))}
        </div>
        <div className="rs-cloud rs-cloud-1" />
        <div className="rs-cloud rs-cloud-2" />
        <div className="rs-cloud rs-cloud-3" />
      </div>

      <div className="rs-layer rs-far">
        <div className="rs-scroll-track">
          <SkylineFar />
          <SkylineFar />
        </div>
      </div>

      <div className="rs-layer rs-mid">
        <div className="rs-scroll-track">
          <HillsMidBridge />
          <HillsMidBridge />
        </div>
      </div>

      <div className="rs-layer rs-track-layer">
        <div className="rs-scroll-track rs-scroll-track--fast">
          <TrackStrip />
          <TrackStrip />
          <TrackStrip />
        </div>
      </div>

      <div className="rs-train">
        <TrainSvg />
        <div className="rs-train-fx">
          <div className="rs-headlight-beam" />
          <div className="rs-speedlines">
            <span />
            <span />
            <span />
            <span />
          </div>
          <div className="rs-steam">
            <span />
            <span />
            <span />
          </div>
        </div>
      </div>
    </div>
  );
};

export default RailScene;
