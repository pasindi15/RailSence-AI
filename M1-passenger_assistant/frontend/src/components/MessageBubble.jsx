export default function MessageBubble({ role, text, source, language }) {
  const isUser = role === "user";
  return (
    <div className={`bubble-row ${isUser ? "right" : "left"}`}>
      <div className={`bubble ${isUser ? "user" : "bot"}`}>
        {isUser && language && <span className="lang-tag">{language.toUpperCase()}</span>}
        <div>{text}</div>
        {!isUser && source && <div className="source-tag">Source: {source}</div>}
      </div>
    </div>
  );
}
