'use client'

import { useState } from 'react'
import { SplineScene } from '@/components/ui/splite'
import { motion, AnimatePresence } from 'framer-motion'

const ENGINEER_ACCOUNTS = [
  { id: 'ENG-001', username: 'admin',   password: 'admin123',   name: 'Chief Engineer',   role: 'Chief Mechanical Engineer' },
  { id: 'ENG-102', username: 'menike',  password: 'menike2024', name: 'Asitha Menike',    role: 'Locomotive Inspector'      },
  { id: 'ENG-205', username: 'silva',   password: 'silva2024',  name: 'Rohan Silva',      role: 'Track Maintenance Officer' },
  { id: 'ENG-308', username: 'perera',  password: 'perera2024', name: 'Nilantha Perera',  role: 'Signal Technician'         },
]

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState('')
  const [loading, setLoading]   = useState(false)
  const [loggedIn, setLoggedIn] = useState(false)
  const [engineer, setEngineer] = useState<typeof ENGINEER_ACCOUNTS[0] | null>(null)

  function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    setTimeout(() => {
      const match = ENGINEER_ACCOUNTS.find(
        a => a.username === username.trim().toLowerCase() && a.password === password
      )
      if (match) {
        setEngineer(match)
        setLoggedIn(true)
        setTimeout(() => { window.location.href = 'http://localhost:8002' }, 1800)
      } else {
        setError('Invalid credentials. Check your username and password.')
        setLoading(false)
      }
    }, 900)
  }

  return (
    <main className="min-h-screen w-full flex overflow-hidden">

      {/* ── LEFT PANEL — dark with 3D scene ── */}
      <div className="hidden md:flex flex-1 relative flex-col justify-between p-10 bg-[#050810] overflow-hidden">

        {/* Grid */}
        <div className="absolute inset-0 bg-[linear-gradient(rgba(59,130,246,0.04)_1px,transparent_1px),linear-gradient(90deg,rgba(59,130,246,0.04)_1px,transparent_1px)] bg-[size:48px_48px] pointer-events-none" />

        {/* Glow orbs */}
        <div className="absolute top-[-15%] left-[-10%] w-[400px] h-[400px] bg-blue-600/15 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute bottom-[-10%] right-[-5%] w-[300px] h-[300px] bg-indigo-600/15 rounded-full blur-3xl pointer-events-none" />

        {/* Top logo */}
        <div className="relative z-10 flex items-center gap-3">
          <img src="/logo.png" alt="RailSense Logo" className="h-10 w-auto object-contain drop-shadow-lg" />
          <div>
            <p className="text-white font-bold text-sm">RailSense AI</p>
            <p className="text-blue-300/60 text-[10px] tracking-widest uppercase">Maintenance Agent</p>
          </div>
        </div>

        {/* 3D Scene */}
        <div className="absolute inset-0">
          <SplineScene
            scene="https://prod.spline.design/kZDDjO5HuC9GJUM2/scene.splinecode"
            className="w-full h-full"
          />
        </div>

        {/* Bottom text */}
        <div className="relative z-10">
          <div className="inline-flex items-center gap-2 bg-white/10 backdrop-blur border border-white/10 rounded-full px-3 py-1 mb-4">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-white/80 text-[11px] font-medium">System Online</span>
          </div>
          <h2 className="text-white text-2xl font-bold leading-snug">
            Maintenance &<br />Asset Intelligence
          </h2>
          <p className="text-blue-300/60 text-sm mt-2 max-w-xs">
            Real-time fleet health monitoring across all Sri Lanka Railways routes.
          </p>
        </div>
      </div>

      {/* ── RIGHT PANEL — clean white form ── */}
      <div className="w-full md:w-[420px] shrink-0 bg-white flex flex-col justify-center px-10 py-12 relative">

        {/* Top accent */}
        <div className="absolute top-0 left-0 right-0 h-1 md:hidden"
          style={{ background: 'linear-gradient(90deg, #1e40af, #06b6d4)' }} />

        {/* Mobile logo (hidden on desktop) */}
        <div className="flex items-center gap-3 mb-8 md:hidden">
          <div className="w-9 h-9 rounded-xl flex items-center justify-center"
            style={{ background: 'linear-gradient(135deg, #1e40af, #06b6d4)' }}>
            <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
              <path d="M12 2L2 7l10 5 10-5-10-5z"/>
              <path d="M2 17l10 5 10-5"/>
              <path d="M2 12l10 5 10-5"/>
            </svg>
          </div>
          <p className="text-slate-800 font-bold">RailSense AI</p>
        </div>

        <AnimatePresence mode="wait">
          {loggedIn && engineer ? (

            /* ── Success state ── */
            <motion.div
              key="success"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="flex flex-col items-center text-center gap-5"
            >
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: 'spring', stiffness: 260, damping: 20, delay: 0.1 }}
                className="w-16 h-16 rounded-full bg-emerald-100 flex items-center justify-center"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-8 h-8 text-emerald-500">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
              </motion.div>
              <div>
                <p className="text-slate-800 font-bold text-xl">Welcome, {engineer.name.split(' ')[0]}!</p>
                <p className="text-slate-500 text-sm mt-1">{engineer.role}</p>
                <p className="text-blue-500 text-xs mt-1 font-mono bg-blue-50 px-2 py-0.5 rounded-full inline-block">{engineer.id}</p>
              </div>
              <div className="flex items-center gap-2 text-slate-400 text-sm">
                <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                Redirecting to dashboard…
              </div>
            </motion.div>

          ) : (

            /* ── Login form ── */
            <motion.div key="form" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.4 }}>

              <div className="flex justify-center mb-6">
                <img
                  src="/logo.png"
                  alt="RailSense Logo"
                  className="h-28 w-auto object-contain"
                />
              </div>
              <h1 className="text-3xl font-bold text-slate-800 mb-1">Welcome back</h1>
              <p className="text-slate-400 text-sm mb-8">Sign in to your engineer account</p>

              <form onSubmit={handleLogin} className="space-y-5">

                {/* Username */}
                <div>
                  <label className="block text-xs font-semibold text-slate-500 mb-2 uppercase tracking-wider">
                    Username
                  </label>
                  <div className="relative">
                    <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4">
                        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                        <circle cx="12" cy="7" r="4"/>
                      </svg>
                    </span>
                    <input
                      type="text"
                      value={username}
                      onChange={e => setUsername(e.target.value)}
                      placeholder="Enter your username"
                      required
                      className="w-full pl-10 pr-4 py-3 rounded-xl border border-slate-200 text-slate-800 text-sm placeholder:text-slate-300 bg-slate-50 focus:bg-white focus:outline-none focus:border-blue-400 focus:ring-3 focus:ring-blue-100 transition-all"
                    />
                  </div>
                </div>

                {/* Password */}
                <div>
                  <label className="block text-xs font-semibold text-slate-500 mb-2 uppercase tracking-wider">
                    Password
                  </label>
                  <div className="relative">
                    <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4">
                        <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                        <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                      </svg>
                    </span>
                    <input
                      type="password"
                      value={password}
                      onChange={e => setPassword(e.target.value)}
                      placeholder="••••••••"
                      required
                      className="w-full pl-10 pr-4 py-3 rounded-xl border border-slate-200 text-slate-800 text-sm placeholder:text-slate-300 bg-slate-50 focus:bg-white focus:outline-none focus:border-blue-400 focus:ring-3 focus:ring-blue-100 transition-all"
                    />
                  </div>
                </div>

                {/* Error */}
                <AnimatePresence>
                  {error && (
                    <motion.div
                      initial={{ opacity: 0, y: -6 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      className="flex items-start gap-2 text-red-600 text-xs bg-red-50 border border-red-200 rounded-xl px-4 py-3"
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5 shrink-0 mt-0.5">
                        <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                      </svg>
                      {error}
                    </motion.div>
                  )}
                </AnimatePresence>

                {/* Submit */}
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full py-3 rounded-xl text-white font-bold text-sm flex items-center justify-center gap-2 transition-all disabled:opacity-60 disabled:cursor-not-allowed hover:opacity-90 active:scale-[0.98] shadow-lg"
                  style={{ background: 'linear-gradient(135deg, #1e40af 0%, #3b82f6 60%, #06b6d4 100%)' }}
                >
                  {loading ? (
                    <>
                      <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                      Authenticating…
                    </>
                  ) : (
                    <>
                      Sign In
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-4 h-4">
                        <line x1="5" y1="12" x2="19" y2="12"/>
                        <polyline points="12 5 19 12 12 19"/>
                      </svg>
                    </>
                  )}
                </button>
              </form>

              {/* Demo accounts */}
              <div className="mt-7 pt-6 border-t border-slate-100">
                <p className="text-slate-400 text-xs text-center mb-3">Demo accounts — click to autofill</p>
                <div className="grid grid-cols-2 gap-2">
                  {ENGINEER_ACCOUNTS.map(a => (
                    <button
                      key={a.id}
                      type="button"
                      onClick={() => { setUsername(a.username); setPassword(a.password); setError('') }}
                      className="text-left px-3 py-2.5 rounded-xl border border-slate-200 bg-slate-50 hover:bg-blue-50 hover:border-blue-200 transition-all group"
                    >
                      <p className="text-slate-700 text-[11px] font-semibold group-hover:text-blue-600 transition-colors">{a.name.split(' ')[0]}</p>
                      <p className="text-slate-400 text-[10px] font-mono">{a.username}</p>
                    </button>
                  ))}
                </div>
              </div>

              <p className="text-center text-slate-300 text-[11px] mt-8">
                RailSense AI · M4 Maintenance Intelligence · IT3041
              </p>
            </motion.div>

          )}
        </AnimatePresence>
      </div>
    </main>
  )
}
