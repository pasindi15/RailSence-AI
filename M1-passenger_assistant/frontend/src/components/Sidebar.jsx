import ThemeToggle from "./ThemeToggle.jsx";

const PinIcon = ({ filled = false }) => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 2l1.5 5.5L19 9l-4 4 1 6-4-3-4 3 1-6-4-4 5.5-1.5z" />
  </svg>
);

const TrashIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" />
  </svg>
);

function ChatItem({ chat, isActive, onSelect, onPin, onDeleteRequest }) {
  return (
    <div
      className={`chat-item ${isActive ? "active" : ""}`}
      onClick={() => onSelect(chat.id)}
    >
      {chat.isPinned && (
        <span className="chat-item-pin" aria-label="Pinned chat">
          <PinIcon filled />
        </span>
      )}
      <span className="chat-item-title">{chat.title || "New conversation"}</span>
      <span className="chat-item-actions">
        <button
          type="button"
          className="chat-item-icon-btn"
          aria-label={chat.isPinned ? "Unpin chat" : "Pin chat"}
          title={chat.isPinned ? "Unpin chat" : "Pin chat"}
          onClick={(e) => {
            e.stopPropagation();
            onPin(chat.id, !chat.isPinned);
          }}
        >
          <PinIcon filled={chat.isPinned} />
        </button>
        <button
          type="button"
          className="chat-item-icon-btn chat-item-icon-btn-danger"
          aria-label="Delete chat"
          title="Delete chat"
          onClick={(e) => {
            e.stopPropagation();
            onDeleteRequest(chat.id);
          }}
        >
          <TrashIcon />
        </button>
      </span>
    </div>
  );
}

export default function Sidebar({ chats, activeChatId, onNewChat, onSelectChat, onPin, onDeleteRequest, passenger, onLogout }) {
  const pinned = chats.filter((c) => c.isPinned);
  const recent = chats.filter((c) => !c.isPinned);

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

      <div className="chat-groups">
        {pinned.length > 0 && (
          <div className="chat-group">
            <div className="chat-group-label">Pinned</div>
            <div className="chat-group-list">
              {pinned.map((chat) => (
                <ChatItem
                  key={chat.id}
                  chat={chat}
                  isActive={chat.id === activeChatId}
                  onSelect={onSelectChat}
                  onPin={onPin}
                  onDeleteRequest={onDeleteRequest}
                />
              ))}
            </div>
          </div>
        )}

        <div className="chat-group chat-group-recent">
          <div className="chat-group-label">Recent</div>
          <div className="chat-group-list">
            {recent.map((chat) => (
              <ChatItem
                key={chat.id}
                chat={chat}
                isActive={chat.id === activeChatId}
                onSelect={onSelectChat}
                onPin={onPin}
                onDeleteRequest={onDeleteRequest}
              />
            ))}
          </div>
        </div>
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
        <div className="sidebar-footer-actions">
          <ThemeToggle />
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
    </div>
  );
}
