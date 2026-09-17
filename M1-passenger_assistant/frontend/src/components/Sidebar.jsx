export default function Sidebar({ chats, activeChatId, onNewChat, onSelectChat, passenger, onLogout }) {
  return (
    <div className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-brand-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" width="14" height="14">
            <rect x="2" y="7" width="20" height="13" rx="2"/>
            <path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/>
            <line x1="12" y1="12" x2="12" y2="16"/>
            <line x1="8" y1="14" x2="16" y2="14"/>
          </svg>
        </div>
        <span className="sidebar-brand-name">RailSense AI</span>
      </div>

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

      <div className="sidebar-footer">
        {passenger && (
          <div className="sidebar-user">
            <div className="sidebar-avatar">
              {passenger.name.charAt(0).toUpperCase()}
            </div>
            <div className="sidebar-user-info">
              <p className="sidebar-user-name">{passenger.name}</p>
              <p className="sidebar-user-id">{passenger.id}</p>
            </div>
          </div>
        )}
        <button className="sidebar-logout-btn" onClick={onLogout}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
            <polyline points="16 17 21 12 16 7"/>
            <line x1="21" y1="12" x2="9" y2="12"/>
          </svg>
          Logout
        </button>
      </div>
    </div>
  );
}
