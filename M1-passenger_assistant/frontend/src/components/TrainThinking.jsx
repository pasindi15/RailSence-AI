// Railway "diamond crossing" thinking indicator: two rail pairs crossing in an X
// that take turns squeezing while the glyph turns, an amber signal lamp in the
// centre, and three sleepers that light up in sequence. Pure SVG + CSS keyframes
// (transform/opacity only); see .train-thinking in echo.css.
export default function TrainThinking() {
  return (
    <span className="train-thinking" aria-hidden="true">
      <svg className="tt-glyph" viewBox="0 0 32 32" width="28" height="28">
        <defs>
          <linearGradient id="tt-rail" gradientUnits="userSpaceOnUse" x1="3" y1="16" x2="29" y2="16">
            <stop offset="0" stopColor="#6EA0FF" />
            <stop offset="1" stopColor="#2F5BEA" />
          </linearGradient>
        </defs>
        <g transform="rotate(45 16 16)">
          <g className="tt-rail tt-rail-a">
            <line x1="3" y1="16" x2="12" y2="16" />
            <line x1="20" y1="16" x2="29" y2="16" />
          </g>
        </g>
        <g transform="rotate(-45 16 16)">
          <g className="tt-rail tt-rail-b">
            <line x1="3" y1="16" x2="12" y2="16" />
            <line x1="20" y1="16" x2="29" y2="16" />
          </g>
        </g>
        <circle className="tt-halo" cx="16" cy="16" r="4.2" />
        <circle className="tt-dot" cx="16" cy="16" r="2.4" />
      </svg>
      <span className="tt-sleepers">
        <i />
        <i />
        <i />
      </span>
    </span>
  );
}
