import React, { useEffect, useRef, useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import RailScene from '../RailScene';
import ThemeToggle from '../ThemeToggle.jsx';
import { login } from '../../api.js';
import '../login.css';

// Autofill hints for the demo chips below - NOT an authentication mechanism.
// Credentials are verified by the backend against bcrypt hashes in the
// `passengers` table (POST /auth/login); nothing here grants access, and
// editing it in devtools achieves nothing. These four are deliberately
// published demo logins. Delete this block to hide them from the login screen.
const DEMO_HINTS = [
  { id: "PSG-001", username: "kavya",   password: "kavya2024",   name: "Kavya Perera"    },
  { id: "PSG-002", username: "dilshan", password: "dilshan2024", name: "Dilshan Silva"   },
  { id: "PSG-003", username: "nimal",   password: "nimal2024",   name: "Nimal Fernando"  },
  { id: "PSG-004", username: "guest",   password: "guest123",    name: "Guest Passenger" },
];

interface PassengerAccount {
  id: string;
  username: string;
  name: string;
  nic?: string;
}

interface AnimatedSignInProps {
  onLogin: (passenger: PassengerAccount) => void;
}

function useCountUp(target: number, active: boolean, duration = 1200) {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (!active) return;
    let frame: number;
    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(target * eased);
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, target, duration]);
  return value;
}

const AnimatedSignIn: React.FC<AnimatedSignInProps> = ({ onLogin }) => {
  const [showPassword, setShowPassword] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [passenger, setPassenger] = useState<PassengerAccount | null>(null);
  const [cardVisible, setCardVisible] = useState(false);
  const [shake, setShake] = useState(false);
  const [whoosh, setWhoosh] = useState(false);
  const shakeTimeout = useRef<number | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setCardVisible(true), 250);
    return () => window.clearTimeout(t);
  }, []);

  useEffect(() => {
    return () => {
      if (shakeTimeout.current) window.clearTimeout(shakeTimeout.current);
    };
  }, []);

  const ridersCount = useCountUp(2.5, cardVisible, 1400);
  const availabilityCount = useCountUp(24, cardVisible, 1100);

  const triggerShake = () => {
    setShake(true);
    if (shakeTimeout.current) window.clearTimeout(shakeTimeout.current);
    shakeTimeout.current = window.setTimeout(() => setShake(false), 520);
  };

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);
    try {
      // The backend checks the password against a bcrypt hash and returns a
      // signed token. The browser no longer decides who is logged in.
      const account = await login(username.trim().toLowerCase(), password);
      const signedIn: PassengerAccount = {
        id: account.user_id,
        username: account.username,
        name: account.full_name,
        nic: account.nic,
      };
      setPassenger(signedIn);
      setSuccess(true);
      setIsLoading(false);
      setTimeout(() => setWhoosh(true), 450);
      setTimeout(() => onLogin(signedIn), 1150);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid username or password.');
      setIsLoading(false);
      triggerShake();
    }
  };

  const typing = !success && !error && (username.length > 0 || password.length > 0);
  const signalClass = success
    ? 'login-signal login-signal--success'
    : error
    ? 'login-signal login-signal--error'
    : typing
    ? 'login-signal login-signal--typing'
    : 'login-signal';

  return (
    <div className="login-page">
      <RailScene boost={success} />

      <div className="login-theme-toggle">
        <ThemeToggle />
      </div>

      <div className="login-topbar">
        <div className="login-brand-mark">
          <img src={`${import.meta.env.BASE_URL}logo.png`} alt="" aria-hidden="true" />
          <span>RailSense AI</span>
        </div>
      </div>

      <div className="login-content">
        <div className="login-hero">
          <div className="login-route" aria-hidden="true">
            <div className="login-route-line" />
            <div className="login-route-runner" />
            <div className="login-route-station login-route-station-1">
              <span className="login-route-dot" />
              <span className="login-route-label">Colombo Fort</span>
            </div>
            <div className="login-route-station login-route-station-2">
              <span className="login-route-dot" />
              <span className="login-route-label">Kandy</span>
            </div>
            <div className="login-route-station login-route-station-3">
              <span className="login-route-dot" />
              <span className="login-route-label">Galle</span>
            </div>
          </div>

          <h1 className="login-headline">
            Your journey, <span className="accent">sensed in real time.</span>
          </h1>
          <p className="login-subline">
            Live schedules, delay predictions and bookings across Sri Lanka Railways — in
            English, සිංහල and தமிழ்.
          </p>
          <div className="login-stats">
            <div className="stat-chip">
              <span className="stat-chip-value">{ridersCount.toFixed(1)}M+</span>
              <span className="stat-chip-label">Monthly riders</span>
            </div>
            <div className="stat-chip">
              <span className="stat-chip-value">{Math.round(availabilityCount)}/7</span>
              <span className="stat-chip-label">AI availability</span>
            </div>
          </div>
        </div>

        <div className="login-card-wrap">
          <div className={`login-card${cardVisible ? ' login-card--visible' : ''}${shake ? ' login-card--shake' : ''}`}>
            {success && passenger ? (
              <div className="login-success">
                <div className="login-success-icon">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" width="26" height="26" aria-hidden="true">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                </div>
                <div>
                  <p className="login-success-name">Welcome, {passenger.name.split(' ')[0]}!</p>
                  <p className="login-success-id">{passenger.id}</p>
                </div>
                <div className="login-success-loading">
                  <span className="login-spinner" aria-hidden="true" />
                  Loading assistant…
                </div>
              </div>
            ) : (
              <>
                <div className="login-card-header">
                  <img
                    className="login-card-logo"
                    src={`${import.meta.env.BASE_URL}logo.png`}
                    alt="RailSense AI"
                  />
                  <span className={signalClass} aria-hidden="true" />
                </div>

                <h2 className="login-title">
                  Sign in to <span className="accent">RailSense AI</span>
                </h2>
                <p className="login-subtitle">Welcome back — enter your passenger account details.</p>

                <form onSubmit={handleSignIn}>
                  <div className="login-field">
                    <label htmlFor="login-username">Username</label>
                    <div className="login-input-shell">
                      <input
                        id="login-username"
                        className="login-input"
                        type="text"
                        value={username}
                        onChange={e => setUsername(e.target.value)}
                        placeholder="Enter your username"
                        required
                        autoComplete="username"
                      />
                    </div>
                  </div>

                  <div className="login-field">
                    <label htmlFor="login-password">Password</label>
                    <div className="login-input-shell">
                      <input
                        id="login-password"
                        className="login-input has-toggle"
                        type={showPassword ? 'text' : 'password'}
                        value={password}
                        onChange={e => setPassword(e.target.value)}
                        placeholder="••••••••"
                        required
                        autoComplete="current-password"
                      />
                      <button
                        type="button"
                        className="login-eye-btn"
                        onClick={() => setShowPassword(v => !v)}
                        aria-label={showPassword ? 'Hide password' : 'Show password'}
                      >
                        {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                      </button>
                    </div>
                  </div>

                  <div aria-live="assertive">
                    {error && (
                      <div className="login-error">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14" style={{ flexShrink: 0, marginTop: 1 }} aria-hidden="true">
                          <circle cx="12" cy="12" r="10" />
                          <line x1="12" y1="8" x2="12" y2="12" />
                          <line x1="12" y1="16" x2="12.01" y2="16" />
                        </svg>
                        {error}
                      </div>
                    )}
                  </div>

                  <button type="submit" className="login-submit" disabled={isLoading}>
                    {isLoading ? (
                      <>
                        <span className="login-spinner" aria-hidden="true" />
                        Signing in…
                      </>
                    ) : 'Sign In'}
                  </button>
                </form>

                <div className="login-demo">
                  <p className="login-demo-label">Demo accounts — click to autofill</p>
                  <div className="login-demo-grid">
                    {DEMO_HINTS.map(a => (
                      <button
                        key={a.id}
                        type="button"
                        className="login-demo-chip"
                        onClick={() => { setUsername(a.username); setPassword(a.password); setError(''); }}
                      >
                        <span className="login-demo-chip-name">{a.name.split(' ')[0]}</span>
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

      <div className={`login-whoosh${whoosh ? ' login-whoosh--active' : ''}`} aria-hidden="true" />
    </div>
  );
};

export { AnimatedSignIn };
