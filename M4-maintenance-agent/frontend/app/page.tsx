"use client";

import { LeverSwitch } from "@/components/ui/lever-switch";
import { DarkModeToggle } from "@/components/ui/dark-mode-toggle";
import { useState } from "react";

export default function DemoOne() {
  const [systemPower, setSystemPower] = useState(false);
  const [trackPower, setTrackPower] = useState(true);
  const [signalPower, setSignalPower] = useState(false);

  return (
    <div className="min-h-screen bg-background transition-colors duration-300">
      {/* Top bar */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3">
          <div>
            <h1 className="text-sm font-bold tracking-tight">RailSense M4</h1>
            <p className="text-xs text-muted-foreground">Control Panel Components</p>
          </div>
          <DarkModeToggle />
        </div>
      </header>

      {/* Main */}
      <main className="mx-auto max-w-5xl px-6 py-12">
        {/* Hero banner */}
        <div className="relative mb-12 overflow-hidden rounded-2xl">
          <img
            src="https://images.unsplash.com/photo-1474487548417-781cb71495f3?w=1200&q=80"
            alt="Railway control panel"
            className="h-56 w-full object-cover object-center brightness-50"
          />
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-white">
            <span className="rounded-full border border-white/30 bg-white/10 px-3 py-1 text-xs font-semibold uppercase tracking-widest backdrop-blur-sm">
              Control Panel
            </span>
            <h2 className="text-3xl font-extrabold tracking-tight drop-shadow-lg">
              Lever Switch Component
            </h2>
            <p className="text-sm text-white/75">
              Physical lever-style toggle — click to switch
            </p>
          </div>
        </div>

        {/* Switch panel */}
        <section className="mb-10">
          <h3 className="mb-6 text-lg font-bold tracking-tight">System Switches</h3>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
            {/* Card 1 */}
            <div className="flex flex-col items-center gap-6 rounded-2xl border border-border bg-card p-8 shadow-sm transition-shadow hover:shadow-md">
              <div className="flex flex-col items-center gap-1">
                <span className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
                  Main Power
                </span>
                <span
                  className={`text-xs font-semibold ${
                    systemPower ? "text-green-500" : "text-red-400"
                  }`}
                >
                  {systemPower ? "● ACTIVE" : "○ INACTIVE"}
                </span>
              </div>
              <LeverSwitch
                defaultChecked={systemPower}
                onChange={setSystemPower}
                label="System"
              />
            </div>

            {/* Card 2 */}
            <div className="flex flex-col items-center gap-6 rounded-2xl border border-border bg-card p-8 shadow-sm transition-shadow hover:shadow-md">
              <div className="flex flex-col items-center gap-1">
                <span className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
                  Track Power
                </span>
                <span
                  className={`text-xs font-semibold ${
                    trackPower ? "text-green-500" : "text-red-400"
                  }`}
                >
                  {trackPower ? "● ACTIVE" : "○ INACTIVE"}
                </span>
              </div>
              <LeverSwitch
                defaultChecked={trackPower}
                onChange={setTrackPower}
                label="Track"
              />
            </div>

            {/* Card 3 */}
            <div className="flex flex-col items-center gap-6 rounded-2xl border border-border bg-card p-8 shadow-sm transition-shadow hover:shadow-md">
              <div className="flex flex-col items-center gap-1">
                <span className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
                  Signal Power
                </span>
                <span
                  className={`text-xs font-semibold ${
                    signalPower ? "text-green-500" : "text-red-400"
                  }`}
                >
                  {signalPower ? "● ACTIVE" : "○ INACTIVE"}
                </span>
              </div>
              <LeverSwitch
                defaultChecked={signalPower}
                onChange={setSignalPower}
                label="Signal"
              />
            </div>
          </div>
        </section>

        {/* Status readout */}
        <section className="rounded-2xl border border-border bg-muted/40 p-6">
          <h3 className="mb-4 text-sm font-bold uppercase tracking-widest text-muted-foreground">
            System Status
          </h3>
          <div className="grid grid-cols-3 gap-4 text-sm">
            {[
              { label: "Main Power", value: systemPower },
              { label: "Track Power", value: trackPower },
              { label: "Signal Power", value: signalPower },
            ].map(({ label, value }) => (
              <div
                key={label}
                className="flex items-center justify-between rounded-lg border border-border bg-background px-4 py-3"
              >
                <span className="text-muted-foreground">{label}</span>
                <span
                  className={`font-bold ${
                    value ? "text-green-500" : "text-red-400"
                  }`}
                >
                  {value ? "ON" : "OFF"}
                </span>
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}
