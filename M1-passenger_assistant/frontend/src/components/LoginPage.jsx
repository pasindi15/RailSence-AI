import { useState } from "react";

const PASSENGER_ACCOUNTS = [
  { id: "PSG-001", username: "kavya",   password: "kavya2024",   name: "Kavya Perera",    nic: "200012345678" },
  { id: "PSG-002", username: "dilshan", password: "dilshan2024", name: "Dilshan Silva",   nic: "199887654321" },
  { id: "PSG-003", username: "nimal",   password: "nimal2024",   name: "Nimal Fernando",  nic: "200198765432" },
  { id: "PSG-004", username: "guest",   password: "guest123",    name: "Guest Passenger", nic: "N/A"          },
];

export default function LoginPage({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError]       = useState("");
  const [loading, setLoading]   = useState(false);
  const [success, setSuccess]   = useState(false);
  const [passenger, setPassenger] = useState(null);

  function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    setTimeout(() => {
      const match = PASSENGER_ACCOUNTS.find(
        (a) => a.username === username.trim().toLowerCase() && a.password === password
      );
      if (match) {
        setPassenger(match);
        setSuccess(true);
        setTimeout(() => onLogin(match), 1600);
      } else {
        setError("Invalid username or password.");
        setLoading(false);
      }
    }, 800);
  }

  function autofill(a) {
    setUsername(a.username);
    setPassword(a.password);
    setError("");
  }

  return (
    <div className="login-root">

      {/* ── LEFT PANEL ── */}
      <div className="login-left">
        <div className="login-grid-bg" />
        <div className="login-glow login-glow-1" />
        <div className="login-glow login-glow-2" />

        {/* Brand */}
        <div className="login-brand">
          <div className="login-brand-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" width="20" height="20">
              <rect x="2" y="7" width="20" height="13" rx="2"/>
              <path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/>
              <line x1="12" y1="12" x2="12" y2="16"/>
              <line x1="8" y1="14" x2="16" y2="14"/>
            </svg>
          </div>
          <div>
            <p className="login-brand-name">RailSense AI</p>
            <p className="login-brand-sub">Passenger Assistant</p>
          </div>
        </div>

        {/* Animated train track */}
        <div className="login-train-wrap">
          <div className="login-track">
            <div className="login-rail login-rail-top" />
            <div className="login-sleepers">
              {Array.from({ length: 10 }).map((_, i) => (
                <div key={i} className="login-sleeper" />
              ))}
            </div>
            <div className="login-rail login-rail-bottom" />
          </div>
          <div className="login-train">
            <svg viewBox="0 0 120 48" fill="none" xmlns="http://www.w3.org/2000/svg" width="120" height="48">
              <rect x="4" y="8" width="112" height="30" rx="6" fill="#1e40af"/>
              <rect x="4" y="8" width="112" height="30" rx="6" stroke="#3b82f6" strokeWidth="1.5"/>
              <rect x="8" y="12" width="20" height="14" rx="3" fill="#60a5fa" opacity="0.8"/>
              <rect x="32" y="12" width="20" height="14" rx="3" fill="#60a5fa" opacity="0.8"/>
              <rect x="56" y="12" width="20" height="14" rx="3" fill="#60a5fa" opacity="0.8"/>
              <rect x="80" y="12" width="20" height="14" rx="3" fill="#60a5fa" opacity="0.8"/>
              <rect x="100" y="12" width="14" height="14" rx="3" fill="#93c5fd" opacity="0.9"/>
              <circle cx="24" cy="40" r="5" fill="#1e3a8a" stroke="#60a5fa" strokeWidth="1.5"/>
              <circle cx="96" cy="40" r="5" fill="#1e3a8a" stroke="#60a5fa" strokeWidth="1.5"/>
              <circle cx="24" cy="40" r="2" fill="#60a5fa"/>
              <circle cx="96" cy="40" r="2" fill="#60a5fa"/>
              <rect x="4" y="30" width="112" height="6" rx="0" fill="#1e3a8a" opacity="0.6"/>
            </svg>
          </div>
        </div>

        {/* Bottom caption */}
        <div className="login-left-footer">
          <div className="login-status-pill">
            <span className="login-status-dot" />
            <span>Live Service</span>
          </div>
          <h2 className="login-left-title">Your Journey,<br />Our Intelligence</h2>
          <p className="login-left-sub">Real-time train info, booking, and assistance across all Sri Lanka Railways routes.</p>
        </div>
      </div>

      {/* ── RIGHT PANEL ── */}
      <div className="login-right">
        <div className="login-right-inner">

          {success && passenger ? (
            <div className="login-success">
              <div className="login-success-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2.5" width="36" height="36">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
              </div>
              <p className="login-success-name">Welcome, {passenger.name.split(" ")[0]}!</p>
              <p className="login-success-id">{passenger.id}</p>
              <div className="login-redirect-row">
                <div className="login-spinner" />
                <span>Loading assistant…</span>
              </div>
            </div>
          ) : (
            <>
              <h1 className="login-title">Welcome back</h1>
              <p className="login-subtitle">Sign in to your passenger account</p>

              <form className="login-form" onSubmit={handleSubmit}>
                <div className="login-field">
                  <label className="login-label">Username</label>
                  <div className="login-input-wrap">
                    <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
                      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                      <circle cx="12" cy="7" r="4"/>
                    </svg>
                    <input
                      className="login-input"
                      type="text"
                      placeholder="Enter your username"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      required
                      autoComplete="username"
                    />
                  </div>
                </div>

                <div className="login-field">
                  <label className="login-label">Password</label>
                  <div className="login-input-wrap">
                    <svg className="login-input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
                      <rect x="3" y="11" width="18" height="11" rx="2"/>
                      <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                    </svg>
                    <input
                      className="login-input"
                      type="password"
                      placeholder="••••••••"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                      autoComplete="current-password"
                    />
                  </div>
                </div>

                {error && (
                  <div className="login-error">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                      <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                    </svg>
                    {error}
                  </div>
                )}

                <button className="login-btn" type="submit" disabled={loading}>
                  {loading ? (
                    <><div className="login-spinner login-spinner-sm" /> Signing in…</>
                  ) : (
                    <>Sign In
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" width="16" height="16">
                        <line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>
                      </svg>
                    </>
                  )}
                </button>
              </form>

              {/* Demo accounts */}
              <div className="login-demo">
                <p className="login-demo-label">Demo accounts — click to autofill</p>
                <div className="login-demo-grid">
                  {PASSENGER_ACCOUNTS.map((a) => (
                    <button key={a.id} className="login-demo-chip" type="button" onClick={() => autofill(a)}>
                      <span className="login-demo-chip-name">{a.name.split(" ")[0]}</span>
                      <span className="login-demo-chip-user">{a.username}</span>
                    </button>
                  ))}
                </div>
              </div>

              <p className="login-footer-text">RailSense AI · M1 Passenger Assistant · IT3041</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
