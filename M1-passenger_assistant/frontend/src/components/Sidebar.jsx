export default function Sidebar({ chats, activeChatId, onNewChat, onSelectChat }) {
  return (
    <div className="sidebar">
      <button className="new-chat-btn" onClick={onNewChat}>+ New Chat</button>
      <div className="chat-list">
        {chats.map((chat) => (
          <div
            key={chat.id}
            className={`chat-item ${chat.id === activeChatId ? "active" : ""}`}
            onClick={() => onSelectChat(chat.id)}
          >
            {chat.title || "New conversation"}
          </div>
        ))}
      </div>
      <div className="sidebar-footer">Passenger Account</div>
    </div>
  );
}
