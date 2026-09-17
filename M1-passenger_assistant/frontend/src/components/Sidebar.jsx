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

export default function Sidebar({ chats, activeChatId, onNewChat, onSelectChat, onPin, onDeleteRequest }) {
  const pinned = chats.filter((c) => c.isPinned);
  const recent = chats.filter((c) => !c.isPinned);

  return (
    <div className="sidebar">
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
        <span>Passenger Account</span>
        <ThemeToggle />
      </div>
    </div>
  );
}
