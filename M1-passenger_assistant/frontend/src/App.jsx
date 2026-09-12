import { useState } from "react";
import Sidebar from "./components/Sidebar.jsx";
import ChatWindow from "./components/ChatWindow.jsx";
import { sendMessage } from "./api.js";

function newChatId() {
  return crypto.randomUUID();
}

export default function App() {
  const [chats, setChats] = useState([{ id: newChatId(), title: "New conversation", messages: [] }]);
  const [activeChatId, setActiveChatId] = useState(chats[0].id);
  const [loading, setLoading] = useState(false);

  const activeChat = chats.find((c) => c.id === activeChatId);

  const handleNewChat = () => {
    const chat = { id: newChatId(), title: "New conversation", messages: [] };
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
