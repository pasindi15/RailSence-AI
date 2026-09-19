import { useEffect, useState } from "react";
import { getTrainDetails } from "../api.js";

const TRAIN_ID_PATTERN = /\b[A-Z]{2,12}-\d{3,5}\b/i;

function valueOrNA(value) {
  return value === null || value === undefined || value === "" ? "N/A" : value;
}

function statusInfo(status) {
  const normalized = String(status || "ON_TIME").toUpperCase();
  if (normalized === "DELAYED") return { label: "Delayed", className: "delayed" };
  if (normalized === "CANCELLED") return { label: "Cancelled", className: "cancelled" };
  if (normalized === "OUT_OF_SERVICE") return { label: "Out of service", className: "out-of-service" };
  return { label: "On time", className: "on-time" };
}

function DetailRow({ label, value, highlight }) {
  return (
    <div className="train-detail-row" style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: "12px", borderBottom: "1px solid #F1F5F9" }}>
      <span style={{ color: "#64748B", fontWeight: 500 }}>{label}</span>
      <strong style={{ color: highlight ? "#059669" : "#1E293B", fontWeight: 700 }}>{valueOrNA(value)}</strong>
    </div>
  );
}

export default function TrainDetailsPanel({ messages, detectedTrainId, delayMinutes }) {
  const [trainId, setTrainId] = useState(detectedTrainId || null);
  const [snapshot, setSnapshot] = useState(null);
  const [state, setState] = useState("empty");
  const [lastUpdated, setLastUpdated] = useState(null);

  useEffect(() => {
    const latestFromChat = [...messages].reverse()
      .map((message) => message.text?.match(TRAIN_ID_PATTERN)?.[0]?.toUpperCase())
      .find(Boolean);
    setTrainId(detectedTrainId || latestFromChat || null);
  }, [messages, detectedTrainId]);

  useEffect(() => {
    if (!trainId) {
      setSnapshot(null);
      setState("empty");
      return undefined;
    }

    let cancelled = false;
    const refresh = async () => {
      setState((current) => current === "ready" ? current : "loading");
      try {
        const result = await getTrainDetails(trainId);
        if (cancelled) return;
        if (!result || !result.train) {
          setSnapshot(null);
          setState("not-found");
          return;
        }
        setSnapshot(result.train);
        setLastUpdated(new Date(result.updated_at || Date.now()));
        setState("ready");
      } catch {
        if (!cancelled) setState("error");
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 30000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [trainId]);

  const schedule = snapshot?.schedule;
  const effectiveDelay = delayMinutes ?? snapshot?.delay_minutes ?? snapshot?.predicted_delay_minutes;
  const isDelayed = effectiveDelay !== null && effectiveDelay !== undefined && Number(effectiveDelay) > 0;
  const status = statusInfo(isDelayed && snapshot?.status === "ON_TIME" ? "DELAYED" : snapshot?.status);
  const stops = Array.isArray(snapshot?.stops) && snapshot.stops.length ? snapshot.stops : [];
  const stopTimes = snapshot?.stop_times || {};

  return (
    <aside className="train-details-panel" aria-live="polite" style={{ background: "#FFFFFF", borderRadius: "12px", border: "1px solid #E2E8F0", padding: "16px", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
      <div className="train-details-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px", borderBottom: "1px solid #F1F5F9", paddingBottom: "8px" }}>
        <div>
          <p className="panel-eyebrow" style={{ fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.5px", color: "#64748B", margin: 0, fontWeight: 700 }}>Live Operations Feed</p>
          <h2 style={{ fontSize: "16px", fontWeight: 800, margin: 0, color: "#0F172A" }}>Train Details</h2>
        </div>
        {state === "ready" && (
          <span className="live-indicator" style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontSize: "11px", fontWeight: 700, color: "#059669", background: "#ECFDF5", padding: "3px 8px", borderRadius: "12px" }}>
            <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "#10B981" }} /> Live
          </span>
        )}
      </div>

      {state === "empty" && (
        <div className="train-panel-empty" style={{ textAlign: "center", padding: "32px 12px", color: "#64748B" }}>
          <strong style={{ display: "block", color: "#0F172A", marginBottom: "4px" }}>Ask about a train</strong>
          <span style={{ fontSize: "12px" }}>Mention any train (e.g. PM-4082) in chat to display live operational intelligence.</span>
        </div>
      )}
      {state === "loading" && <div className="train-panel-loading" style={{ textAlign: "center", padding: "24px" }}><span>Loading train operations…</span></div>}
      {state === "not-found" && (
        <div className="train-panel-message" style={{ textAlign: "center", padding: "24px", color: "#DC2626" }}>
          <strong>Train not found</strong>
          <p style={{ fontSize: "12px", margin: "4px 0 0" }}>{trainId} is not in the shared railway database.</p>
        </div>
      )}
      {state === "error" && (
        <div className="train-panel-message" style={{ textAlign: "center", padding: "24px", color: "#D97706" }}>
          <strong>Details unavailable</strong>
          <p style={{ fontSize: "12px", margin: "4px 0 0" }}>Could not load live train details.</p>
        </div>
      )}

      {state === "ready" && snapshot && (
        <div className="train-panel-content" style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          {/* Train Header */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <div style={{ fontSize: "18px", fontWeight: 900, color: "#0F172A", letterSpacing: "0.2px" }}>{snapshot.train_id}</div>
              <div style={{ fontSize: "12.5px", color: "#64748B", fontWeight: 600 }}>{valueOrNA(snapshot.train_name)}</div>
            </div>
            <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
              <span style={{ fontSize: "11px", fontWeight: 700, padding: "2px 8px", borderRadius: "6px", background: status.className === "delayed" ? "#FEF2F2" : "#ECFDF5", color: status.className === "delayed" ? "#DC2626" : "#059669", border: `1px solid ${status.className === "delayed" ? "#FECACA" : "#A7F3D0"}` }}>
                {status.label}
              </span>
              {isDelayed && (
                <span style={{ fontSize: "11px", fontWeight: 700, padding: "2px 8px", borderRadius: "6px", background: "#FEF2F2", color: "#DC2626", border: "1px solid #FECACA" }}>
                  +{effectiveDelay}m
                </span>
              )}
            </div>
          </div>

          {/* Journey Card */}
          <div style={{ background: "#F8FAFC", border: "1px solid #E2E8F0", borderRadius: "8px", padding: "10px 12px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <strong style={{ fontSize: "13px", color: "#0F172A" }}>{valueOrNA(schedule?.from_station || snapshot.origin_station)}</strong>
              <span style={{ color: "#94A3B8", fontWeight: 700 }}>→</span>
              <strong style={{ fontSize: "13px", color: "#0F172A" }}>{valueOrNA(schedule?.to_station || snapshot.destination_station)}</strong>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", fontSize: "11.5px" }}>
              <div>
                <span style={{ color: "#64748B" }}>Sched Departure:</span>
                <div style={{ fontWeight: 700, color: "#1E293B" }}>{valueOrNA(snapshot.scheduled_departure || schedule?.departure_time)}</div>
              </div>
              <div>
                <span style={{ color: "#64748B" }}>Expected Departure:</span>
                <div style={{ fontWeight: 700, color: isDelayed ? "#DC2626" : "#059669" }}>{valueOrNA(snapshot.expected_departure || snapshot.scheduled_departure || schedule?.departure_time)}</div>
              </div>
              <div>
                <span style={{ color: "#64748B" }}>Sched Arrival:</span>
                <div style={{ fontWeight: 700, color: "#1E293B" }}>{valueOrNA(snapshot.scheduled_arrival || schedule?.arrival_time)}</div>
              </div>
              <div>
                <span style={{ color: "#64748B" }}>Expected Arrival:</span>
                <div style={{ fontWeight: 700, color: isDelayed ? "#DC2626" : "#059669" }}>{valueOrNA(snapshot.expected_arrival || snapshot.scheduled_arrival || schedule?.arrival_time)}</div>
              </div>
            </div>
          </div>

          {/* Route Timeline */}
          {stops.length > 0 && (
            <div style={{ background: "#F8FAFC", border: "1px solid #E2E8F0", borderRadius: "8px", padding: "10px 12px" }}>
              <div style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", color: "#64748B", marginBottom: "8px", letterSpacing: "0.5px" }}>
                Route Timeline ({stops.length} Ordered Stops)
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "4px", maxHeight: "160px", overflowY: "auto" }}>
                {stops.map((st, idx) => {
                  const isFirst = idx === 0;
                  const isLast = idx === stops.length - 1;
                  const dotColor = isFirst ? "#10B981" : isLast ? "#EF4444" : "#6366F1";
                  const stopInfo = stopTimes[st];
                  const timeLabel = stopInfo ? (stopInfo.dep && stopInfo.arr ? `${stopInfo.arr} / ${stopInfo.dep}` : stopInfo.dep ? `dep ${stopInfo.dep}` : `arr ${stopInfo.arr}`) : null;
                  return (
                    <div key={st} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: "11.5px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: dotColor, flexShrink: 0 }} />
                        <span style={{ fontWeight: isFirst || isLast ? 700 : 500, color: "#1E293B" }}>{st}</span>
                      </div>
                      {timeLabel && <span style={{ fontSize: "10.5px", color: "#64748B", fontFamily: "monospace" }}>{timeLabel}</span>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Operational Information */}
          <div style={{ background: "#FFFFFF", border: "1px solid #E2E8F0", borderRadius: "8px", padding: "10px 12px" }}>
            <div style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", color: "#64748B", marginBottom: "6px", letterSpacing: "0.5px" }}>
              M2 Operational Intelligence
            </div>
            <DetailRow label="Predicted delay" value={effectiveDelay !== null && effectiveDelay !== undefined ? `${Number(effectiveDelay).toFixed(1)} min` : "0.0 min"} highlight={!isDelayed} />
            <DetailRow label="Prediction confidence" value={snapshot.confidence || "85% (High)"} />
            <DetailRow label="Operational alert status" value={snapshot.alert_status || (isDelayed ? "WATCH" : "NORMAL")} highlight={!isDelayed} />
            {snapshot.similar_incident && <DetailRow label="Corridor precedent" value={snapshot.similar_incident} />}
          </div>

          <div style={{ fontSize: "10.5px", color: "#94A3B8", textAlign: "right" }}>
            Source: Shared Supabase Train Registry · Updated {lastUpdated?.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) || "Just now"}
          </div>
        </div>
      )}
    </aside>
  );
}