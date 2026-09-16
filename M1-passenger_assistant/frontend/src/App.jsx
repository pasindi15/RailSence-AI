import { useState, useEffect } from "react";
import Sidebar from "./components/Sidebar.jsx";
import ChatWindow from "./components/ChatWindow.jsx";
import { sendMessage, getHistory } from "./api.js";

const CHATS_KEY = "railsense_chats";
const ACTIVE_KEY = "railsense_active_chat";

function newChatId() {
  return crypto.randomUUID();
}

function loadStoredChats() {
  try {
    const raw = localStorage.getItem(CHATS_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (Array.isArray(parsed) && parsed.length > 0) {
      return parsed.map((c) => ({ ...c, messages: [], loaded: false }));
    }
  } catch (err) {
    console.warn("Failed to read saved chats", err);
  }
  return [{ id: newChatId(), title: "New conversation", messages: [], loaded: false }];
}

function mapHistoryMessages(messages) {
  return messages.map((m) => ({
    role: m.role === "assistant" ? "bot" : "user",
    text: m.message,
  }));
}

export default function App() {
  const [chats, setChats] = useState(loadStoredChats);
  const [activeChatId, setActiveChatId] = useState(() => {
    const stored = localStorage.getItem(ACTIVE_KEY);
    return stored && chats.some((c) => c.id === stored) ? stored : chats[0].id;
  });
  const [loading, setLoading] = useState(false);

  const activeChat = chats.find((c) => c.id === activeChatId);

  // Persist the chat list (id + title only) whenever it changes.
  useEffect(() => {
    const meta = chats.map(({ id, title }) => ({ id, title }));
    localStorage.setItem(CHATS_KEY, JSON.stringify(meta));
  }, [chats]);

  useEffect(() => {
    localStorage.setItem(ACTIVE_KEY, activeChatId);
  }, [activeChatId]);

  // Rehydrate messages for the active chat from the backend (survives refresh).
  useEffect(() => {
    if (!activeChat || activeChat.loaded) return;
    let cancelled = false;

    getHistory(activeChatId)
      .then((res) => {
        if (cancelled) return;
        setChats((prev) =>
          prev.map((c) =>
            c.id === activeChatId
              ? { ...c, messages: mapHistoryMessages(res.messages || []), loaded: true }
              : c
          )
        );
      })
      .catch((err) => {
        console.warn("Failed to load chat history", err);
        if (!cancelled) {
          setChats((prev) => prev.map((c) => (c.id === activeChatId ? { ...c, loaded: true } : c)));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeChatId, activeChat]);

  const handleNewChat = () => {
    const chat = { id: newChatId(), title: "New conversation", messages: [], loaded: true };
    setChats((prev) => [chat, ...prev]);
    setActiveChatId(chat.id);
  };

  const handleSelectChat = (id) => setActiveChatId(id);

  const handleSend = async (text) => {
    // optimistic render of the user's message
    setChats((prev) =>
      prev.map((c) =>
        c.id === activeChatId
          ? {
              ...c,
              title: c.messages.length === 0 ? text.slice(0, 30) : c.title,
              messages: [...c.messages, { role: "user", text }],
            }
          : c
      )
    );
    setLoading(true);

    try {
      const res = await sendMessage(activeChatId, text);
      setChats((prev) =>
        prev.map((c) =>
          c.id === activeChatId
            ? {
                ...c,
                messages: [...c.messages, { role: "bot", text: res.reply, source: res.source }],
              }
            : c
        )
      );
    } catch (err) {
      setChats((prev) =>
        prev.map((c) =>
          c.id === activeChatId
            ? { ...c, messages: [...c.messages, { role: "bot", text: "Something went wrong. Please try again." }] }
            : c
        )
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <Sidebar
        chats={chats}
        activeChatId={activeChatId}
        onNewChat={handleNewChat}
        onSelectChat={handleSelectChat}
      />
      <ChatWindow messages={activeChat.messages} onSend={handleSend} loading={loading} />
    </div>
  );
}
