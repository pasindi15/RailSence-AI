import React, { useState, useEffect } from 'react';
import { Eye, EyeOff } from 'lucide-react';

const PASSENGER_ACCOUNTS = [
  { id: "PSG-001", username: "kavya",   password: "kavya2024",   name: "Kavya Perera",    nic: "200012345678" },
  { id: "PSG-002", username: "dilshan", password: "dilshan2024", name: "Dilshan Silva",   nic: "199887654321" },
  { id: "PSG-003", username: "nimal",   password: "nimal2024",   name: "Nimal Fernando",  nic: "200198765432" },
  { id: "PSG-004", username: "guest",   password: "guest123",    name: "Guest Passenger", nic: "N/A"          },
];

interface PassengerAccount {
  id: string;
  username: string;
  password: string;
  name: string;
  nic: string;
}

interface AnimatedSignInProps {
  onLogin: (passenger: PassengerAccount) => void;
}

const AnimatedSignIn: React.FC<AnimatedSignInProps> = ({ onLogin }) => {
  const [theme, setTheme]             = useState<'light' | 'dark'>('light');
  const [showPassword, setShowPassword] = useState(false);
  const [username, setUsername]       = useState('');
  const [password, setPassword]       = useState('');
  const [isLoading, setIsLoading]     = useState(false);
  const [error, setError]             = useState('');
  const [success, setSuccess]         = useState(false);
  const [passenger, setPassenger]     = useState<PassengerAccount | null>(null);
  const [mounted, setMounted]         = useState(false);
  const [formVisible, setFormVisible] = useState(false);

  useEffect(() => {
    setMounted(true);
    setTimeout(() => setFormVisible(true), 300);
  }, []);

  const handleSignIn = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);
    setTimeout(() => {
      const match = PASSENGER_ACCOUNTS.find(
        a => a.username === username.trim().toLowerCase() && a.password === password
      );
      if (match) {
        setPassenger(match);
        setSuccess(true);
        setTimeout(() => onLogin(match), 1600);
      } else {
        setError('Invalid username or password.');
        setIsLoading(false);
      }
    }, 800);
  };

  if (!mounted) return null;

  const dark = theme === 'dark';

  return (
    <div
      className={`min-h-screen w-full flex items-center justify-center p-4 md:p-8 transition-colors duration-300`}
      style={{ background: dark ? '#0f172a' : 'linear-gradient(135deg, #e8f0fe 0%, #f0f7ff 50%, #e0f2fe 100%)' }}
    >
      {/* Theme toggle */}
      <button
        onClick={() => setTheme(dark ? 'light' : 'dark')}
        className={`fixed right-5 top-5 rounded-full p-2.5 z-50 transition-all duration-200 cursor-pointer ${
          dark ? 'bg-slate-700 text-yellow-400 hover:bg-slate-600' : 'bg-white/80 text-slate-600 hover:bg-white shadow-md'
        }`}
      >
        {dark ? (
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/>
            <path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/>
            <path d="M2 12h2"/><path d="M20 12h2"/>
            <path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>
          </svg>
        ) : (
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>
          </svg>
        )}
      </button>

      {/* Card */}
      <div
        className={`w-full max-w-6xl rounded-2xl overflow-hidden shadow-2xl flex flex-col md:flex-row transition-all duration-500 ${
          formVisible ? 'opacity-100 scale-100' : 'opacity-0 scale-95'
        }`}
      >
        {/* ── LEFT PANEL — full-bleed image collage ── */}
        <div className="hidden md:block relative w-full md:w-3/5" style={{ minHeight: '620px' }}>

          {/* Full-bleed grid fills the entire panel via absolute positioning */}
          <div className="absolute inset-0 grid grid-cols-2 grid-rows-3">

            {/* Row 1 — img1 */}
            <div className="overflow-hidden">
              <img src={`${import.meta.env.BASE_URL}login-images/img1.jpg`} alt="Sri Lanka train" className="w-full h-full object-cover block" />
            </div>

            {/* Row 1 — Stat card 1 (blue) */}
            <div
              className="relative flex flex-col justify-center items-center p-8 text-white overflow-hidden"
              style={{ background: 'linear-gradient(135deg, #1e40af 0%, #2563eb 60%, #0891b2 100%)' }}
            >
              <div className="absolute inset-0 opacity-10"
                style={{ backgroundImage: 'radial-gradient(circle at 30% 70%, white 1px, transparent 1px)', backgroundSize: '20px 20px' }}
              />
              <p className="text-xs uppercase tracking-[0.2em] opacity-70 mb-3 font-medium">Monthly Riders</p>
              <h2 className="text-5xl font-bold mb-2 tracking-tight" style={{ fontFamily: 'Poppins, system-ui, sans-serif' }}>2.5M+</h2>
              <div className="w-8 h-0.5 bg-white/50 rounded-full my-2" />
              <p className="text-center text-xs opacity-80 leading-relaxed max-w-[140px]">passengers travel Sri Lanka Railways every month</p>
            </div>

            {/* Row 2 — img2 */}
            <div className="overflow-hidden">
              <img src={`${import.meta.env.BASE_URL}login-images/img2.jpg`} alt="Railway station" className="w-full h-full object-cover block" />
            </div>

            {/* Row 2 — img3 */}
            <div className="overflow-hidden">
              <img src={`${import.meta.env.BASE_URL}login-images/img3.jpg`} alt="Train journey" className="w-full h-full object-cover block" />
            </div>

            {/* Row 3 — Stat card 2 (emerald) */}
            <div
              className="relative flex flex-col justify-center items-center p-8 text-white overflow-hidden"
              style={{ background: 'linear-gradient(135deg, #065f46 0%, #059669 60%, #10b981 100%)' }}
            >
              <div className="absolute inset-0 opacity-10"
                style={{ backgroundImage: 'radial-gradient(circle at 70% 30%, white 1px, transparent 1px)', backgroundSize: '20px 20px' }}
              />
              <p className="text-xs uppercase tracking-[0.2em] opacity-70 mb-3 font-medium">Availability</p>
              <h2 className="text-5xl font-bold mb-2 tracking-tight" style={{ fontFamily: 'Poppins, system-ui, sans-serif' }}>24/7</h2>
              <div className="w-8 h-0.5 bg-white/50 rounded-full my-2" />
              <p className="text-center text-xs opacity-80 leading-relaxed max-w-[140px]">AI-powered assistance for all your journey needs</p>
            </div>

            {/* Row 3 — img4 */}
            <div className="overflow-hidden">
              <img src={`${import.meta.env.BASE_URL}login-images/img4.jpg`} alt="Sri Lanka scenery" className="w-full h-full object-cover block" />
            </div>

          </div>

          {/* Brand overlay bar at top */}
          <div className="absolute top-0 left-0 right-0 z-10 px-6 py-5"
            style={{ background: 'linear-gradient(to bottom, rgba(0,0,0,0.55) 0%, transparent 100%)' }}
          >
            <div className="flex items-center gap-3">
              <img src={`${import.meta.env.BASE_URL}logo.png`} alt="RailSense AI" className="h-8 w-auto object-contain brightness-0 invert" />
              <span className="text-white font-semibold text-sm tracking-wide" style={{ fontFamily: 'Poppins, system-ui, sans-serif' }}>
                RailSense AI
              </span>
            </div>
          </div>

          {/* Bottom tagline overlay */}
          <div className="absolute bottom-0 left-0 right-0 z-10 px-6 py-5"
            style={{ background: 'linear-gradient(to top, rgba(0,0,0,0.55) 0%, transparent 100%)' }}
          >
            <p className="text-white/80 text-xs tracking-wide" style={{ fontFamily: 'Poppins, system-ui, sans-serif' }}>
              Sri Lanka's Intelligent Railway Network
            </p>
          </div>

        </div>

        {/* ── RIGHT PANEL — sign in form ── */}
        <div
          className={`w-full md:w-2/5 flex flex-col justify-center p-8 md:p-12 ${dark ? 'bg-slate-900' : 'bg-white'}`}
          style={{
            transform: formVisible ? 'translateX(0)' : 'translateX(24px)',
            opacity: formVisible ? 1 : 0,
            transition: 'transform 0.6s ease-out, opacity 0.6s ease-out',
          }}
        >
          {success && passenger ? (

            /* Success state */
            <div className="flex flex-col items-center text-center gap-5 py-10">
              <div className="w-16 h-16 rounded-full bg-emerald-100 flex items-center justify-center">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-8 h-8 text-emerald-500">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
              </div>
              <div>
                <p className={`font-bold text-xl ${dark ? 'text-white' : 'text-slate-800'}`} style={{ fontFamily: 'Poppins, system-ui, sans-serif' }}>
                  Welcome, {passenger.name.split(' ')[0]}!
                </p>
                <p className="text-slate-400 text-sm mt-1">{passenger.id}</p>
              </div>
              <div className="flex items-center gap-2 text-slate-400 text-sm">
                <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                Loading assistant…
              </div>
            </div>

          ) : (

            <>
              {/* Logo */}
              <div className="flex justify-center mb-7">
                <img src={`${import.meta.env.BASE_URL}logo.png`} alt="RailSense AI" className="h-16 w-auto object-contain" />
              </div>

              <h1 className={`text-2xl font-bold mb-1 ${dark ? 'text-white' : 'text-gray-900'}`} style={{ fontFamily: 'Poppins, system-ui, sans-serif' }}>
                Sign in to <span className="text-blue-600">RailSense AI</span>
              </h1>
              <p className={`text-sm mb-8 ${dark ? 'text-slate-400' : 'text-slate-500'}`}>
                Welcome back — enter your passenger account details.
              </p>

              <form onSubmit={handleSignIn} className="space-y-5">

                {/* Username */}
                <div className="space-y-1.5">
                  <label className={`block text-sm font-medium ${dark ? 'text-slate-200' : 'text-slate-700'}`}>
                    Username
                  </label>
                  <input
                    type="text"
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                    placeholder="Enter your username"
                    required
                    autoComplete="username"
                    className={`block w-full rounded-lg border py-3 px-4 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all ${
                      dark
                        ? 'bg-slate-800 border-slate-700 text-white placeholder:text-slate-500'
                        : 'bg-slate-50 border-slate-200 text-slate-900 placeholder:text-slate-400 focus:bg-white'
                    }`}
                  />
                </div>

                {/* Password */}
                <div className="space-y-1.5">
                  <label className={`block text-sm font-medium ${dark ? 'text-slate-200' : 'text-slate-700'}`}>
                    Password
                  </label>
                  <div className="relative">
                    <input
                      type={showPassword ? 'text' : 'password'}
                      value={password}
                      onChange={e => setPassword(e.target.value)}
                      placeholder="••••••••"
                      required
                      autoComplete="current-password"
                      className={`block w-full rounded-lg border py-3 px-4 pr-11 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all ${
                        dark
                          ? 'bg-slate-800 border-slate-700 text-white placeholder:text-slate-500'
                          : 'bg-slate-50 border-slate-200 text-slate-900 placeholder:text-slate-400 focus:bg-white'
                      }`}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className={`absolute inset-y-0 right-0 flex items-center pr-3.5 cursor-pointer ${dark ? 'text-slate-400' : 'text-slate-400 hover:text-slate-600'}`}
                    >
                      {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                    </button>
                  </div>
                </div>

                {/* Error */}
                {error && (
                  <div className="flex items-start gap-2.5 text-red-600 text-xs bg-red-50 border border-red-200 rounded-xl px-4 py-3">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5 shrink-0 mt-0.5">
                      <circle cx="12" cy="12" r="10"/>
                      <line x1="12" y1="8" x2="12" y2="12"/>
                      <line x1="12" y1="16" x2="12.01" y2="16"/>
                    </svg>
                    {error}
                  </div>
                )}

                {/* Submit */}
                <button
                  type="submit"
                  disabled={isLoading}
                  className="flex w-full justify-center items-center gap-2 rounded-lg py-3 px-4 text-sm font-semibold text-white shadow-lg transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed hover:opacity-90 active:scale-[0.98] cursor-pointer"
                  style={{ background: 'linear-gradient(135deg, #1e40af 0%, #2563eb 60%, #0891b2 100%)' }}
                >
                  {isLoading ? (
                    <>
                      <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"/>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
                      </svg>
                      Signing in…
                    </>
                  ) : 'Sign In'}
                </button>
              </form>

              {/* Demo accounts */}
              <div className={`mt-7 pt-6 border-t ${dark ? 'border-slate-700' : 'border-slate-100'}`}>
                <p className="text-slate-400 text-xs text-center mb-3">Demo accounts — click to autofill</p>
                <div className="grid grid-cols-2 gap-2">
                  {PASSENGER_ACCOUNTS.map(a => (
                    <button
                      key={a.id}
                      type="button"
                      onClick={() => { setUsername(a.username); setPassword(a.password); setError(''); }}
                      className={`text-left px-3 py-2.5 rounded-xl border transition-all cursor-pointer ${
                        dark
                          ? 'border-slate-700 bg-slate-800 hover:bg-slate-700 hover:border-slate-600'
                          : 'border-slate-200 bg-slate-50 hover:bg-blue-50 hover:border-blue-200'
                      }`}
                    >
                      <p className={`text-[11px] font-semibold ${dark ? 'text-slate-200' : 'text-slate-700'}`}>
                        {a.name.split(' ')[0]}
                      </p>
                      <p className="text-slate-400 text-[10px] font-mono">{a.username}</p>
                    </button>
                  ))}
                </div>
              </div>

              <p className="text-center text-[10px] mt-6 text-slate-400">
                RailSense AI · M1 Passenger Assistant · IT3041
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export { AnimatedSignIn };
