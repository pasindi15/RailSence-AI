import { useState, useEffect } from "react";
import Sidebar from "./components/Sidebar.jsx";
import ChatWindow from "./components/ChatWindow.jsx";
import LoginPage from "./components/LoginPage.jsx";
import ConfirmDialog from "./components/ConfirmDialog.jsx";
import Toast from "./components/Toast.jsx";
import TrainDetailsPanel from "./components/TrainDetailsPanel.jsx";
import { sendMessage, getHistory, listChats, deleteChat, pinChat } from "./api.js";

const CHATS_KEY = "railsense_chats";
const ACTIVE_KEY = "railsense_active_chat";
const PASSENGER_KEY = "railsense_passenger";

function loadStoredPassenger() {
  try {
    const raw = localStorage.getItem(PASSENGER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function newChatId() {
  return crypto.randomUUID();
}

function emptyChat() {
  return { id: newChatId(), title: "New conversation", messages: [], loaded: true, isPinned: false, persisted: false };
}

function loadStoredChats() {
  try {
    const raw = localStorage.getItem(CHATS_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (Array.isArray(parsed) && parsed.length > 0) {
      return parsed.map((c) => ({ ...c, messages: [], loaded: false, isPinned: !!c.isPinned, persisted: true }));
    }
  } catch (err) {
    console.warn("Failed to read saved chats", err);
  }
  return [emptyChat()];
}

function mapHistoryMessages(messages) {
  return messages.map((m) => ({
    role: m.role === "assistant" ? "bot" : "user",
    text: m.message,
  }));
}

const ChevronLeft = () => (
  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="15 18 9 12 15 6"/>
  </svg>
);

const ChevronRight = () => (
  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="9 18 15 12 9 6"/>
  </svg>
);

export default function App() {
  const [passenger, setPassenger] = useState(loadStoredPassenger);
  const [chats, setChats] = useState(loadStoredChats);
  const [activeChatId, setActiveChatId] = useState(() => {
    const stored = localStorage.getItem(ACTIVE_KEY);
    return stored && chats.some((c) => c.id === stored) ? stored : chats[0].id;
  });
  const [loading, setLoading] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState(null);
  const [toastMessage, setToastMessage] = useState(null);
  const [detectedTrainId, setDetectedTrainId] = useState(null);
  const [delayMinutes, setDelayMinutes] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(() => {
    return localStorage.getItem("railsense_sidebar") !== "false";
  });

  useEffect(() => {
    localStorage.setItem("railsense_sidebar", sidebarOpen ? "true" : "false");
  }, [sidebarOpen]);

  const activeChat = chats.find((c) => c.id === activeChatId);

  const showToast = (message) => setToastMessage(message);

  // Persist the chat list (id + title + pin state) whenever it changes.
  useEffect(() => {
    const meta = chats.map(({ id, title, isPinned }) => ({ id, title, isPinned }));
    localStorage.setItem(CHATS_KEY, JSON.stringify(meta));
  }, [chats]);

  useEffect(() => {
    localStorage.setItem(ACTIVE_KEY, activeChatId);
  }, [activeChatId]);

  // Hydrate the sidebar from the backend on load - it's the source of truth
  // for titles and pin state (a chat pinned on another device/refresh should
  // show pinned here too). Any chat the user just created locally that
  // hasn't had a first message sent yet isn't in the backend list (sessions
  // are created lazily on first send), so it's kept alongside untouched.
  useEffect(() => {
    let cancelled = false;
    listChats()
      .then((sessions) => {
        if (cancelled) return;
        setChats((prev) => {
          const backendById = new Map(sessions.map((s) => [s.session_id, s]));
          // Union, not filter: a chat already in view (e.g. loaded from this
          // browser's localStorage) is never dropped just because the backend
          // list didn't include it - that list can legitimately be empty or
          // stale (backend not configured, a fetch hiccup, migration not run
          // yet) and losing an already-open chat to that would be a crash-y,
          // data-losing UX for something the user did nothing wrong to cause.
          const merged = prev.map((c) => {
            const fromBackend = backendById.get(c.id);
            if (!fromBackend) return c;
            backendById.delete(c.id);
            return { ...c, title: fromBackend.title, isPinned: fromBackend.is_pinned, persisted: true };
          });
          for (const s of backendById.values()) {
            merged.push({
              id: s.session_id,
              title: s.title,
              isPinned: s.is_pinned,
              persisted: true,
              messages: [],
              loaded: false,
            });
          }
          return merged.length > 0 ? merged : [emptyChat()];
        });
      })
      .catch((err) => console.warn("Failed to load chat list", err));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Safety net: if activeChatId ever points at a chat that no longer exists
  // (deleted elsewhere, or dropped by a state update), fall back to the first
  // available chat instead of leaving activeChat undefined, which crashes the
  // render below to a blank page.
  useEffect(() => {
    if (chats.length > 0 && !chats.some((c) => c.id === activeChatId)) {
      setActiveChatId(chats[0].id);
    }
  }, [chats, activeChatId]);

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
    const chat = emptyChat();
    setChats((prev) => [chat, ...prev]);
    setActiveChatId(chat.id);
    setDetectedTrainId(null);
    setDelayMinutes(null);
  };

  const handleSelectChat = (id) => {
    setDetectedTrainId(null);
    setDelayMinutes(null);
    setActiveChatId(id);
  };

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
      setDetectedTrainId(res.entities?.train_id?.toUpperCase() || null);
      setDelayMinutes(res.delay_minutes ?? null);
      let botAction = res.action || null;
      let botPrefill = res.prefill || null;
      let botCancellation = res.cancellation || null;

      // Fallback client-side synthesis for booking request if not populated by backend
      if (!botAction && (res.intent === "booking_request" || /\b(book|reserve|reservation)\b/i.test(text))) {
        const fromMatch = text.match(/\b(?:from)\s+([A-Za-z\s]+?)(?=\s+(?:to|on|at|\d)|$)/i);
        const toMatch = text.match(/\b(?:to)\s+([A-Za-z\s]+?)(?=\s+(?:on|at|from|\d)|$)/i);
        const dateMatch = text.match(/\b(\d{4}-\d{2}-\d{2})\b/);
        const pre = {
          from_station: res.entities?.from_station || (fromMatch ? fromMatch[1].trim() : ""),
          to_station: res.entities?.to_station || (toMatch ? toMatch[1].trim() : ""),
          travel_date: res.entities?.travel_date || (dateMatch ? dateMatch[1].trim() : ""),
        };
        botPrefill = pre;
        botAction = {
          type: "continue_to_booking",
          label: "Continue to Booking ➔",
          prefill: pre,
        };
      }

      // Fallback client-side synthesis for cancellation if not populated by backend
      if (!botAction && (res.intent === "cancel_booking" || /\b(cancel|cancellation|refund)\b/i.test(text))) {
        const refMatch = text.match(/\b(RS-[A-Za-z0-9]{4,10})\b/i);
        const reasonMatch = text.match(/\b(?:because|due to|as|reason:)\s+(.+)$/i);
        botAction = {
          type: "cancellation_confirmation_card",
          label: "Send Cancellation Request ➔",
          booking_reference: refMatch ? refMatch[1].toUpperCase() : (res.entities?.booking_reference || ""),
          reason: reasonMatch ? reasonMatch[1].trim() : (res.entities?.reason || text),
        };
      }

      // The backend creates the session row on this first save, so this chat
      // is now real - subsequent pin/delete on it are backend-backed.
      setChats((prev) =>
        prev.map((c) =>
          c.id === activeChatId
            ? {
                ...c,
                persisted: true,
                messages: [
                  ...c.messages,
                  {
                    role: "bot",
                    text: res.reply,
                    source: res.source,
                    intent: res.intent,
                    action: botAction,
                    prefill: botPrefill,
                    cancellation: botCancellation,
                  },
                ],
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

  const handlePin = async (id, nextPinned) => {
    const chat = chats.find((c) => c.id === id);
    if (!chat) return;
    if (!chat.persisted) {
      showToast("Send a message first, then you can pin this chat.");
      return;
    }

    // optimistic update
    setChats((prev) => prev.map((c) => (c.id === id ? { ...c, isPinned: nextPinned } : c)));

    try {
      await pinChat(id, nextPinned);
    } catch (err) {
      setChats((prev) => prev.map((c) => (c.id === id ? { ...c, isPinned: !nextPinned } : c)));
      showToast("Couldn't update pin. Please try again.");
    }
  };

  const handleDeleteRequest = (id) => setPendingDeleteId(id);
  const handleCancelDelete = () => setPendingDeleteId(null);

  const handleConfirmDelete = async () => {
    const id = pendingDeleteId;
    const chat = chats.find((c) => c.id === id);
    setPendingDeleteId(null);
    if (!chat) return;

    const removeLocally = () => {
      setChats((prev) => {
        const next = prev.filter((c) => c.id !== id);
        const finalChats = next.length > 0 ? next : [emptyChat()];
        if (id === activeChatId) {
          setActiveChatId(finalChats[0].id);
        }
        return finalChats;
      });
    };

    // A chat with no messages sent yet has no database row to delete.
    if (!chat.persisted) {
      removeLocally();
      return;
    }

    try {
      await deleteChat(id);
      removeLocally();
    } catch (err) {
      showToast("Couldn't delete this chat. Please try again.");
    }
  };

  const handleLogin = (p) => {
    setPassenger(p);
    try {
      localStorage.setItem(PASSENGER_KEY, JSON.stringify(p));
    } catch {}
  };

  const handleLogout = () => {
    setPassenger(null);
    try {
      localStorage.removeItem(PASSENGER_KEY);
    } catch {}
  };

  if (!passenger) {
    return <LoginPage onLogin={handleLogin} />;
  }

  return (
    <div className="app">
      <Sidebar
        chats={chats}
        activeChatId={activeChatId}
        onNewChat={handleNewChat}
        onSelectChat={handleSelectChat}
        onPin={handlePin}
        onDeleteRequest={handleDeleteRequest}
        passenger={passenger}
        onLogout={handleLogout}
        isOpen={sidebarOpen}
      />
      <button
        className="sidebar-toggle-btn"
        onClick={() => setSidebarOpen((v) => !v)}
        title={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
        aria-label={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
      >
        {sidebarOpen ? <ChevronLeft /> : <ChevronRight />}
      </button>
      <ChatWindow messages={activeChat?.messages || []} onSend={handleSend} loading={loading} />
      <TrainDetailsPanel messages={activeChat?.messages || []} detectedTrainId={detectedTrainId} delayMinutes={delayMinutes} />
      <ConfirmDialog
        open={pendingDeleteId !== null}
        title="Delete this chat?"
        message="This can't be undone."
        confirmLabel="Delete"
        cancelLabel="Cancel"
        onConfirm={handleConfirmDelete}
        onCancel={handleCancelDelete}
      />
      <Toast message={toastMessage} onDismiss={() => setToastMessage(null)} />
    </div>
  );
}
