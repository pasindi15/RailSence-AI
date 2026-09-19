import { useState } from "react";
import { submitCancellationRequest } from "../api.js";

function renderFormattedText(text) {
  if (!text) return null;

  const lines = text.split("\n");
  return lines.map((line, idx) => {
    const parts = line.split(/(\*\*.*?\*\*)/g);
    const formattedLine = parts.map((part, pIdx) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={pIdx}>{part.slice(2, -2)}</strong>;
      }
      return part;
    });

    const trimmed = line.trim();
    if (trimmed.startsWith("•") || trimmed.startsWith("-")) {
      return (
        <div key={idx} className="msg-bullet">
          {formattedLine}
        </div>
      );
    }

    return (
      <div key={idx} className={trimmed ? "msg-line" : "msg-line empty"}>
        {formattedLine}
      </div>
    );
  });
}

export default function MessageBubble({
  role,
  text,
  source,
  action,
  prefill,
  cancellation,
}) {
  const isUser = role === "user";
  const [submittingCanc, setSubmittingCanc] = useState(false);
  const [cancellationResult, setCancellationResult] = useState(null);
  const [cancError, setCancError] = useState(null);

  const handleContinueBooking = (bookingPrefill) => {
    const data = bookingPrefill || action?.prefill || {};
    const from = encodeURIComponent(data.from_station || "");
    const to = encodeURIComponent(data.to_station || "");
    const dateVal = encodeURIComponent(data.travel_date || "");
    const query = `?from=${from}&to=${to}&date=${dateVal}`;

    if (window.parent && window.parent !== window) {
      window.parent.postMessage(
        {
          type: "NAVIGATE_BOOKING",
          prefill: data,
        },
        "*"
      );
    }

    const targetUrl = `http://localhost:3000/user/booking${query}`;
    if (window.parent === window) {
      window.open(targetUrl, "_blank", "noopener,noreferrer");
    }
  };

  const handleCancelSubmit = async (bookingRef, reason) => {
    setSubmittingCanc(true);
    setCancError(null);
    try {
      const res = await submitCancellationRequest(bookingRef, reason);
      setCancellationResult(res.cancellation || res);
    } catch (err) {
      console.error("Cancellation submission failed:", err);
      setCancError("Unable to submit cancellation request. Please try again.");
    } finally {
      setSubmittingCanc(false);
    }
  };

  return (
    <div className={`bubble-row ${isUser ? "right" : "left"}`}>
      <div className={`bubble ${isUser ? "user" : "bot"}`}>
        <div className="msg-content">{renderFormattedText(text)}</div>

        <div className="msg-meta-row">
          <span className="msg-meta-role">
            {isUser ? "Passenger · You" : "passenger-agent · Assistant"}
          </span>
          {source && !isUser && (
            <span className="msg-meta-source" title={`Verified response from: ${source}`}>
              Source: {source}
            </span>
          )}
        </div>

        {!isUser && (action?.type === "continue_to_booking" || prefill) && (
          <div className="action-card booking-action-card">
            <div className="action-card-header">
              <span className="action-badge booking-badge">🎫 RESERVATION DESK</span>
              <span className="action-card-title">Booking Intent Recognized</span>
            </div>

            <div className="action-chips">
              {(prefill?.from_station || action?.prefill?.from_station) && (
                <div className="action-chip">
                  <span className="chip-label">FROM</span>
                  <span className="chip-value">
                    {prefill?.from_station || action?.prefill?.from_station}
                  </span>
                </div>
              )}
              {(prefill?.to_station || action?.prefill?.to_station) && (
                <div className="action-chip">
                  <span className="chip-label">TO</span>
                  <span className="chip-value">
                    {prefill?.to_station || action?.prefill?.to_station}
                  </span>
                </div>
              )}
              {(prefill?.travel_date || action?.prefill?.travel_date) && (
                <div className="action-chip">
                  <span className="chip-label">DATE</span>
                  <span className="chip-value">
                    {prefill?.travel_date || action?.prefill?.travel_date}
                  </span>
                </div>
              )}
            </div>

            <button
              type="button"
              className="btn-action-primary"
              onClick={() => handleContinueBooking(prefill || action?.prefill)}
            >
              Continue to Booking ➔
            </button>
          </div>
        )}

        {!isUser && action?.type === "cancellation_confirmation_card" && (
          <div className="action-card cancellation-action-card">
            <div className="action-card-header">
              <span className="action-badge danger-badge">⚠️ CANCELLATION GATEWAY</span>
              <span className="action-card-title">Cancellation Request Prepared</span>
            </div>

            <div className="action-chips">
              <div className="action-chip">
                <span className="chip-label">BOOKING REF</span>
                <span className="chip-value mono">
                  {action.booking_reference || "Reference Required"}
                </span>
              </div>
              <div className="action-chip">
                <span className="chip-label">REASON</span>
                <span className="chip-value quote">"{action.reason}"</span>
              </div>
            </div>

            {!cancellationResult ? (
              <>
                <button
                  type="button"
                  className="btn-action-danger"
                  disabled={submittingCanc}
                  onClick={() =>
                    handleCancelSubmit(action.booking_reference, action.reason)
                  }
                >
                  {submittingCanc
                    ? "Transmitting to Agent Hub..."
                    : "Send Cancellation Request ➔"}
                </button>
                {cancError && <div className="action-error">{cancError}</div>}
              </>
            ) : (
              <div className="cancellation-receipt">
                <div className="receipt-title">
                  <span>✅ Cancellation Request Lodged</span>
                  <span className="receipt-pill">
                    {cancellationResult.cancellation_status || "PENDING_ADMIN_REVIEW"}
                  </span>
                </div>
                <div className="receipt-grid">
                  <div className="receipt-item">
                    <span className="receipt-label">Case Ref</span>
                    <span className="receipt-val mono">
                      {cancellationResult.case_reference ||
                        `CR-${action.booking_reference}`}
                    </span>
                  </div>
                  <div className="receipt-item">
                    <span className="receipt-label">Suggested Refund</span>
                    <span className="receipt-val">
                      Rs. {cancellationResult.suggested_refund || "800.00"}
                    </span>
                  </div>
                  <div className="receipt-item">
                    <span className="receipt-label">Eligibility</span>
                    <span className="receipt-val">
                      {cancellationResult.eligibility || "ELIGIBLE (ESTIMATED)"}
                    </span>
                  </div>
                </div>
                <div className="receipt-footer-note">
                  Your request is recorded and awaits administrator review in the Admin Portal.
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
