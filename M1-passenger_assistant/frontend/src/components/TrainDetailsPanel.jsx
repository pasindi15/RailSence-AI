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

function DetailRow({ label, value }) {
  return <div className="train-detail-row"><span>{label}</span><strong>{valueOrNA(value)}</strong></div>;
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
        if (!result) {
          setSnapshot(null);
          setState("not-found");
          return;
        }
        setSnapshot(result.train);
        setLastUpdated(new Date(result.updated_at));
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
  const effectiveDelay = delayMinutes ?? snapshot?.delay_minutes;
  const status = statusInfo(effectiveDelay > 0 && snapshot?.status === "ON_TIME" ? "DELAYED" : snapshot?.status);
  const availability = snapshot?.availability;

  return (
    <aside className="train-details-panel" aria-live="polite">
      <div className="train-details-header">
        <div>
          <p className="panel-eyebrow">Live service</p>
          <h2>Train Details</h2>
        </div>
        {state === "ready" && <span className="live-indicator"><i /> Live</span>}
      </div>

      {state === "empty" && <div className="train-panel-empty"><strong>Ask about a train</strong><span>Live service information will appear here.</span></div>}
      {state === "loading" && <div className="train-panel-loading"><span /><span /><span /></div>}
      {state === "not-found" && <div className="train-panel-message"><strong>Train not found</strong><span>{trainId} is not in the shared train registry.</span></div>}
      {state === "error" && <div className="train-panel-message"><strong>Details unavailable</strong><span>Live service data could not be refreshed.</span></div>}

      {state === "ready" && snapshot && (
        <div className="train-panel-content">
          <div className="train-identity">
            <span className="train-id">{snapshot.train_id}</span>
            <span className="train-name">{valueOrNA(snapshot.train_name)}</span>
          </div>
          <div className="train-route">
            <span>{valueOrNA(schedule?.from_station || snapshot.origin_station)}</span>
            <b>→</b>
            <span>{valueOrNA(schedule?.to_station || snapshot.destination_station)}</span>
          </div>
          <div className={`train-status ${status.className}`}><i /> {status.label}</div>
          <div className="train-detail-list">
            <DetailRow label="Service date" value={schedule?.travel_date} />
            <DetailRow label="Departure" value={schedule?.departure_time} />
            <DetailRow label="Arrival" value={schedule?.arrival_time} />
            <DetailRow label="Delay" value={effectiveDelay === null || effectiveDelay === undefined ? null : `${effectiveDelay} min`} />
            <DetailRow label="Platform" value={schedule?.platform} />
            {availability && Object.entries(availability).map(([seatClass, seats]) => (
              <DetailRow key={seatClass} label={`${seatClass} seats`} value={seats} />
            ))}
          </div>
          <div className="train-panel-footer">Last updated {lastUpdated?.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) || "N/A"}</div>
        </div>
      )}
    </aside>
  );
}