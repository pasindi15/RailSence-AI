export default function MessageBubble({ role, text }) {
  const isUser = role === "user";
  return (
    <div className={`bubble-row ${isUser ? "right" : "left"}`}>
      <div className={`bubble ${isUser ? "user" : "bot"}`}>
        <div>{text}</div>
      </div>
    </div>
  );
}
