"use client";

import dynamic from "next/dynamic";
import Image from "next/image";
import { motion } from "framer-motion";

const RobotHero = dynamic(
  () => import("@/components/ui/robot-hero").then((m) => m.RobotHero),
  { ssr: false }
);

// ─── Data ────────────────────────────────────────────────────────────────────

const agents = [
  {
    id: "M1", title: "Passenger Assistant",
    desc: "AI chatbot answering queries about schedules, fares, delays, and live train status.",
    port: 5280, color: "#00c6ff", icon: "🚆", badge: "Live",
  },
  {
    id: "M2", title: "Operations Center",
    desc: "Admin dashboard for station staff to monitor trains and handle operational incidents.",
    port: 9005, color: "#7c3aed", icon: "🖥️", badge: "Live",
  },
  {
    id: "M3", title: "Hub & Booking",
    desc: "Central hub bridging passenger bookings, seat reservations, and cross-agent communication.",
    port: 9002, color: "#059669", icon: "🎫", badge: "Live",
  },
  {
    id: "M4", title: "Maintenance Agent",
    desc: "Predictive maintenance for engineers — asset health scoring, fault detection, and reports.",
    port: 8006, color: "#f59e0b", icon: "🔧", badge: "Live",
  },
];

const trains = [
  {
    name: "Yal Devi",
    image: "/trains/yal-devi.jpg",
    route: "Colombo Fort → Jaffna",
    line: "Northern Line",
    type: "Intercity Express",
    distance: "398 km",
    duration: "~7 h",
    class: "1st · 2nd · 3rd",
    highlight: "The pride of the North — connects Colombo to the Jaffna Peninsula across the restored Northern Railway.",
    color: "#00c6ff",
  },
  {
    name: "Udarata Menike",
    image: "/trains/udarata-menike.png",
    route: "Colombo Fort → Badulla",
    line: "Main Line / UdupussaWa",
    type: "Intercity",
    distance: "292 km",
    duration: "~9.5 h",
    class: "1st · 2nd · 3rd",
    highlight: "Winds through the stunning Hill Country passing Kandy, Ella, and Haputale.",
    color: "#10b981",
  },
  {
    name: "Denuwara Menike",
    image: "/trains/denuwara-menike.jpg",
    route: "Colombo Fort → Badulla",
    line: "Main Line",
    type: "Intercity Express",
    distance: "292 km",
    duration: "~8.5 h",
    class: "1st · 2nd",
    highlight: "Premium Hill Country service — air-conditioned observation saloons with panoramic views.",
    color: "#6366f1",
  },
  {
    name: "Podi Menike",
    image: "/trains/podi-menike.png",
    route: "Colombo Fort → Badulla",
    line: "Main Line",
    type: "Intercity",
    distance: "292 km",
    duration: "~9 h",
    class: "2nd · 3rd",
    highlight: "The 'Little Queen' of the hill trains — beloved morning service through tea country.",
    color: "#f59e0b",
  },
  {
    name: "Ruhunu Kumari",
    image: "/trains/ruhunu-kumari.png",
    route: "Colombo Fort → Matara",
    line: "Southern Line",
    type: "Intercity Express",
    distance: "157 km",
    duration: "~2.5 h",
    class: "1st · 2nd · 3rd",
    highlight: "Speedy coastal service hugging the Indian Ocean from Colombo to the deep south.",
    color: "#ec4899",
  },
  {
    name: "Galu Kumari",
    image: "/trains/galu-kumari.jpg",
    route: "Colombo Fort → Galle",
    line: "Southern Line",
    type: "Intercity",
    distance: "116 km",
    duration: "~2 h",
    class: "2nd · 3rd",
    highlight: "Scenic ocean-side journey to the historic fort city of Galle along the Southern coast.",
    color: "#f97316",
  },
  {
    name: "Intercity Express",
    image: "/trains/intercity-express.png",
    route: "Colombo Fort → Kandy",
    line: "Main Line",
    type: "Intercity Express",
    distance: "121 km",
    duration: "~2.5 h",
    class: "1st · 2nd · 3rd",
    highlight: "Flagship Colombo–Kandy service, the most frequently operated intercity route on the network.",
    color: "#0ea5e9",
  },
  {
    name: "Night Mail",
    image: "/trains/night-mail.jpg",
    route: "Colombo Fort → Batticaloa",
    line: "Batticaloa Line",
    type: "Night Express",
    distance: "312 km",
    duration: "~8 h",
    class: "Sleeper · 2nd · 3rd",
    highlight: "Overnight express to the East Coast — sleeper cars available for the long haul to Batticaloa.",
    color: "#8b5cf6",
  },
];

const stats = [
  { value: "1,500+", label: "Route km" },
  { value: "8", label: "Main Lines" },
  { value: "182", label: "Stations" },
  { value: "4", label: "AI Agents" },
];

// ─── Animations ───────────────────────────────────────────────────────────────

const fadeUp = {
  hidden: { opacity: 0, y: 32 },
  visible: (i: number) => ({
    opacity: 1, y: 0,
    transition: { delay: i * 0.08, duration: 0.5, ease: [0.16, 1, 0.3, 1] },
  }),
};

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function HomePage() {
  return (
    <main className="bg-[#0a0f1e] min-h-screen text-white">

      {/* ── Hero ── */}
      <RobotHero />

      {/* ── Stats bar ── */}
      <div className="border-y border-white/8 bg-white/[0.03]">
        <div className="max-w-4xl mx-auto grid grid-cols-2 sm:grid-cols-4 divide-x divide-white/8">
          {stats.map((s) => (
            <div key={s.label} className="py-6 px-8 text-center">
              <p className="text-2xl font-black text-[#00c6ff]">{s.value}</p>
              <p className="text-xs text-white/40 mt-1 uppercase tracking-widest">{s.label}</p>
            </div>
          ))}
        </div>
      </div>

      {/* ── Agents ── */}
      <section id="overview" className="py-24 px-6 max-w-6xl mx-auto">
        <motion.div initial="hidden" whileInView="visible" viewport={{ once: true, amount: 0.2 }}
          variants={fadeUp} custom={0} className="text-center mb-14">
          <p className="text-[#00c6ff] text-xs font-mono uppercase tracking-widest mb-3">System Architecture</p>
          <h2 className="text-3xl sm:text-4xl font-black tracking-tight">Four Agents, One Network</h2>
          <p className="text-white/40 mt-3 text-sm max-w-md mx-auto">
            Each agent owns a vertical of railway intelligence, connected through a shared hub.
          </p>
        </motion.div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {agents.map((agent, i) => (
            <motion.a key={agent.id} href={`http://localhost:${agent.port}`} target="_blank"
              rel="noopener noreferrer" initial="hidden" whileInView="visible"
              viewport={{ once: true, amount: 0.1 }} variants={fadeUp} custom={i + 1}
              whileHover={{ y: -4, transition: { duration: 0.2 } }}
              className="group relative flex flex-col rounded-2xl bg-white/5 border border-white/10 p-6 overflow-hidden hover:border-white/20 transition-colors"
            >
              <div className="absolute top-0 left-0 right-0 h-[3px] rounded-t-2xl" style={{ background: agent.color }} />
              <div className="absolute -top-10 left-1/2 -translate-x-1/2 w-32 h-32 rounded-full opacity-0 group-hover:opacity-10 blur-2xl transition-opacity duration-500" style={{ background: agent.color }} />
              <div className="flex items-start justify-between mb-4">
                <span className="text-3xl">{agent.icon}</span>
                <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full"
                  style={{ background: agent.color + "22", color: agent.color, border: `1px solid ${agent.color}44` }}>
                  {agent.badge}
                </span>
              </div>
              <p className="text-[10px] font-mono text-white/30 uppercase tracking-widest mb-1">{agent.id} · port {agent.port}</p>
              <h3 className="text-sm font-bold mb-2">{agent.title}</h3>
              <p className="text-white/40 text-xs leading-relaxed flex-1">{agent.desc}</p>
              <div className="mt-5 text-[11px] font-semibold flex items-center gap-1.5 transition-colors" style={{ color: agent.color }}>
                Open agent <span className="group-hover:translate-x-1 transition-transform inline-block">→</span>
              </div>
            </motion.a>
          ))}
        </div>
      </section>

      {/* ── Trains ── */}
      <section id="trains" className="py-24 px-6 max-w-7xl mx-auto">
        <motion.div initial="hidden" whileInView="visible" viewport={{ once: true, amount: 0.2 }}
          variants={fadeUp} custom={0} className="text-center mb-14">
          <p className="text-[#00c6ff] text-xs font-mono uppercase tracking-widest mb-3">Sri Lanka Railways</p>
          <h2 className="text-3xl sm:text-4xl font-black tracking-tight">The Fleet</h2>
          <p className="text-white/40 mt-3 text-sm max-w-md mx-auto">
            Iconic trains monitored and managed by the RailSense AI network.
          </p>
        </motion.div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
          {trains.map((train, i) => (
            <motion.div key={train.name} initial="hidden" whileInView="visible"
              viewport={{ once: true, amount: 0.05 }} variants={fadeUp} custom={i}
              whileHover={{ y: -5, transition: { duration: 0.2 } }}
              className="group relative flex flex-col rounded-2xl overflow-hidden bg-white/5 border border-white/10 hover:border-white/20 transition-all"
            >
              {/* Image */}
              <div className="relative h-44 overflow-hidden">
                <Image
                  src={train.image}
                  alt={train.name}
                  fill
                  className="object-cover transition-transform duration-500 group-hover:scale-105"
                  sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 25vw"
                />
                {/* Gradient overlay */}
                <div className="absolute inset-0 bg-gradient-to-t from-[#0a0f1e] via-[#0a0f1e]/30 to-transparent" />
                {/* Type badge */}
                <span className="absolute top-3 right-3 text-[10px] font-bold uppercase tracking-wider px-2.5 py-1 rounded-full backdrop-blur-sm"
                  style={{ background: train.color + "33", color: train.color, border: `1px solid ${train.color}55` }}>
                  {train.type}
                </span>
                {/* Line label */}
                <span className="absolute bottom-3 left-3 text-[10px] font-mono text-white/50 uppercase tracking-widest">
                  {train.line}
                </span>
              </div>

              {/* Body */}
              <div className="flex flex-col flex-1 p-4">
                <h3 className="text-base font-black mb-1 tracking-tight">{train.name}</h3>

                {/* Route */}
                <p className="text-xs font-semibold mb-3" style={{ color: train.color }}>
                  {train.route}
                </p>

                {/* Stats row */}
                <div className="grid grid-cols-3 gap-2 mb-3">
                  {[
                    { label: "Distance", value: train.distance },
                    { label: "Duration", value: train.duration },
                    { label: "Class", value: train.class },
                  ].map((s) => (
                    <div key={s.label} className="bg-white/5 rounded-lg p-2 text-center">
                      <p className="text-[11px] font-bold text-white leading-tight">{s.value}</p>
                      <p className="text-[9px] text-white/35 uppercase tracking-wide mt-0.5">{s.label}</p>
                    </div>
                  ))}
                </div>

                {/* Description */}
                <p className="text-white/45 text-xs leading-relaxed flex-1">{train.highlight}</p>
              </div>

              {/* Bottom accent line */}
              <div className="h-[2px] w-full" style={{ background: `linear-gradient(to right, ${train.color}88, transparent)` }} />
            </motion.div>
          ))}
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="border-t border-white/10 py-10 px-6 text-center text-white/30 text-xs">
        <p className="mb-1">
          <span className="text-white/50 font-semibold">RailSense AI</span> — IT3041 Academic Project
        </p>
        <p>Sri Lanka Railways · Intelligent Railway System</p>
      </footer>

      {/* ── Floating chat button ── */}
      <div className="fixed bottom-6 right-6 z-50 flex flex-col items-center gap-1">
        <motion.a href="http://localhost:5280" target="_blank" rel="noopener noreferrer"
          initial={{ scale: 0, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
          transition={{ delay: 1.2, type: "spring", stiffness: 260, damping: 20 }}
          whileHover={{ scale: 1.08 }} whileTap={{ scale: 0.95 }}
          className="relative flex items-center justify-center w-14 h-14 rounded-full bg-[#00c6ff] shadow-[0_0_24px_rgba(0,198,255,0.5)] text-black"
          title="Ask RailSense Passenger Assistant"
        >
          <span className="absolute inset-0 rounded-full bg-[#00c6ff] animate-ping opacity-30" />
          <svg viewBox="0 0 24 24" fill="currentColor" className="w-6 h-6 relative z-10">
            <path d="M12 2C6.477 2 2 6.477 2 12c0 1.89.525 3.66 1.438 5.168L2 22l4.832-1.438A9.957 9.957 0 0012 22c5.523 0 10-4.477 10-10S17.523 2 12 2zm0 18a7.958 7.958 0 01-4.031-1.088l-.289-.173-2.988.889.889-2.988-.173-.289A7.958 7.958 0 014 12c0-4.411 3.589-8 8-8s8 3.589 8 8-3.589 8-8 8zm4.406-5.844c-.242-.121-1.433-.707-1.655-.788-.222-.08-.383-.121-.545.121-.162.242-.626.788-.768.95-.141.161-.282.182-.524.06-.242-.121-1.021-.376-1.944-1.198-.718-.641-1.203-1.432-1.344-1.674-.142-.243-.015-.374.106-.494.109-.109.242-.283.363-.425.121-.141.161-.242.242-.403.08-.162.04-.303-.02-.425-.061-.121-.545-1.314-.747-1.799-.196-.47-.396-.407-.545-.414l-.464-.008c-.161 0-.424.06-.646.303-.222.242-.848.829-.848 2.022s.868 2.346.989 2.508c.121.161 1.71 2.609 4.141 3.659.579.25 1.031.399 1.383.51.581.186 1.11.16 1.528.097.466-.07 1.433-.586 1.634-1.152.202-.565.202-1.049.141-1.152-.06-.1-.222-.161-.464-.282z" />
          </svg>
        </motion.a>
        <span className="text-[10px] text-white/40 font-medium">Passenger AI</span>
      </div>

    </main>
  );
}
