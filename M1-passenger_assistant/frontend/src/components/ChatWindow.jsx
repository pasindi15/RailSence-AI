import { useState } from "react";
import MessageBubble from "./MessageBubble.jsx";
import InputBar from "./InputBar.jsx";

const QUICK_INQUIRIES = [
  {
    icon: "⏰",
    label: "Next Train Schedule",
    text: "What time does the next train to Kandy leave?",
    category: "Schedules",
  },
  {
    icon: "💰",
    label: "Ticket Fare Check",
    text: "How much is a ticket to Galle?",
    category: "Fares",
  },
  {
    icon: "🚦",
    label: "Live Delay Prediction",
    text: "Is the 14:35 Colombo Fort to Kandy train delayed?",
    category: "Operations Hub",
  },
  {
    icon: "🚆",
    label: "Train Reservation Desk",
    text: "I need to book a train from Colombo to Kandy on 3rd December.",
    category: "Booking Desk",
  },
  {
    icon: "🔧",
    label: "Report Broken Amenity",
    text: "The AC is broken in my compartment",
    category: "Maintenance Issue",
  },
  {
    icon: "🔄",
    label: "Cancel Existing Ticket",
    text: "Cancel booking RS-84521 because I booked twice",
    category: "Cancellation",
  },
];

export default function ChatWindow({ messages, onSend, loading }) {
  const [showPromptsBar, setShowPromptsBar] = useState(false);

  return (
    <div className="chat-window">
      {/* Top Bar with Agent State & Quick Inquiries Toggle */}
      <div className="chat-topbar">
        <div className="chat-agent-info">
          <div className="chat-agent-dot"></div>
          <div>
            <span className="chat-agent-name">Multilingual Passenger Assistant</span>
            <span className="chat-agent-langs">English · සිංහල · தமிழ் — Schedules, Fares, Delays & Bookings</span>
          </div>
        </div>
        <button
          type="button"
          className={`btn-prompts-toggle ${showPromptsBar ? "active" : ""}`}
          onClick={() => setShowPromptsBar(!showPromptsBar)}
          title="Toggle Quick Inquiries"
        >
          <span>⚡ Quick Inquiries</span>
          <span className="toggle-chevron">{showPromptsBar ? "▲" : "▼"}</span>
        </button>
      </div>

      {/* Collapsible Quick Inquiries Strip */}
      {showPromptsBar && (
        <div className="quick-prompts-strip">
          <div className="strip-label">SELECT A QUICK INQUIRY:</div>
          <div className="strip-chips">
            {QUICK_INQUIRIES.map((q, idx) => (
              <button
                key={idx}
                type="button"
                className="strip-chip"
                disabled={loading}
                onClick={() => {
                  onSend(q.text);
                  setShowPromptsBar(false);
                }}
              >
                <span className="strip-icon">{q.icon}</span>
                <span className="strip-text">{q.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Messages Scroll Area */}
      <div className="messages">
        {messages.length === 0 ? (
          <div className="empty-state-container">
            <div className="empty-state-card">
              <div className="empty-state-badge">🚆 Central Hub Connected</div>
              <h2 className="empty-state-title">Welcome to RailSense AI</h2>
              <p className="empty-state-desc">
                I can assist with real-time train routes, schedules, ticket fares, delay predictions,
                complaint tracking, and direct seat reservations across Sri Lanka.
              </p>
            </div>

            <div className="quick-inquiries-section">
              <div className="quick-section-heading">
                <span>QUICK INQUIRIES</span>
                <span className="quick-section-sub">Tap any prompt to send immediately</span>
              </div>

              <div className="quick-grid">
                {QUICK_INQUIRIES.map((item, idx) => (
                  <button
                    key={idx}
                    type="button"
                    className="quick-card"
                    disabled={loading}
                    onClick={() => onSend(item.text)}
                  >
                    <div className="quick-card-top">
                      <span className="quick-icon">{item.icon}</span>
                      <span className="quick-category">{item.category}</span>
                    </div>
                    <div className="quick-card-text">"{item.text}"</div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          messages.map((m, i) => <MessageBubble key={i} {...m} />)
        )}

        {loading && (
          <div className="bubble-row left">
            <div className="bubble bot typing-indicator-bubble">
              <span className="typing-dot"></span>
              <span className="typing-dot"></span>
              <span className="typing-dot"></span>
              <span className="typing-label">Consulting RailSense Multi-Agent Hub...</span>
            </div>
          </div>
        )}
      </div>

      {/* Input Bar */}
      <InputBar onSend={onSend} disabled={loading} />
    </div>
  );
}
