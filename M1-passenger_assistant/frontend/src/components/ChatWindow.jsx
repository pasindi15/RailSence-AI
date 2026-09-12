import MessageBubble from "./MessageBubble.jsx";
import InputBar from "./InputBar.jsx";

export default function ChatWindow({ messages, onSend, loading }) {
  return (
    <div className="chat-window">
      <div className="messages">
        {messages.length === 0 && (
          <div className="empty-state">
            Hi! I can help with schedules, fares, delays, or reporting an issue.
            Ask me in Sinhala, Tamil, or English.
          </div>
        )}
        {messages.map((m, i) => (
          <MessageBubble key={i} {...m} />
        ))}
        {loading && <div className="typing-indicator">Typing...</div>}
      </div>
      <InputBar onSend={onSend} disabled={loading} />
    </div>
  );
}
