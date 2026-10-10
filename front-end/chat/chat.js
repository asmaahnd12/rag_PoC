// ===== DOM =====
const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const recordBtn = document.getElementById("recordBtn");
const logoutBtn = document.getElementById("logoutBtn");
const chatTitle = document.getElementById("chatTitle");

const chatOutput = document.createElement("div");
chatOutput.id = "chat-output";
messagesEl.appendChild(chatOutput);

const sidebarUserName = document.getElementById("sidebarUserName");
const sidebarAvatar = document.getElementById("sidebarAvatar");
const newChatBtn = document.getElementById("newChatBtn");
const adminBtn = document.getElementById("adminBtn");
const historyList = document.getElementById("historyList");

// ===== FILE UPLOAD SETUP =====
const fileUploadInput = document.createElement("input");
fileUploadInput.type = "file";
fileUploadInput.id = "fileUploadInput";
fileUploadInput.style.display = "none";
fileUploadInput.accept = ".txt,.md,.pdf,.docx,.pptx";
document.body.appendChild(fileUploadInput);

const uploadBtn = document.querySelector('button[title="Joindre un fichier"]');

// ===== LocalStorage keys =====
const LS_USER = "username";
const LS_TOKEN = "access_token";
const LS_HISTORY = "sont_chat_history"; // base key, suffixée par username
const LS_SELECTED_PERSONALITY = "selected_personality_id";
const LS_PERSONALITIES_VERSION = "personalities_version";
const LS_ACTIVE_CHAT = "sont_active_chat_id";

// ===== State =====
let currentSessionId = null;
let currentChatId = null;
let chats = [];

// ===== Init =====
boot();

async function boot() {
  guardAuth();
  initUserCard();
  bindEvents();
  await initPersonaSelect();
  await loadHistory();

  // Restaurer le dernier chat actif au refresh
  const savedChatId = localStorage.getItem(LS_ACTIVE_CHAT);
  if (savedChatId && chats.find((c) => c.id === savedChatId)) {
    await loadChat(savedChatId);
  }
}

// =========================
//     AUTH GUARD
// =========================
function guardAuth() {
  const token = localStorage.getItem(LS_TOKEN);
  if (!token) {
    window.location.href = "/";
  }
}

function getTokenPayload() {
  const token = localStorage.getItem(LS_TOKEN);
  if (!token) return null;

  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    return JSON.parse(atob(parts[1]));
  } catch (e) {
    return null;
  }
}

// =========================
//        EVENTS
// =========================
function bindEvents() {
  sendBtn.addEventListener("click", handleSend);

  if (inputEl) {
    inputEl.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || e.shiftKey) return;
      if (e.isComposing) return;
      e.preventDefault();
      handleSend();
    });
  }

  if (newChatBtn) {
    newChatBtn.addEventListener("click", handleNewChat);
  }

  if (historyList) {
    historyList.addEventListener("click", (e) => {
      const deleteBtn = e.target.closest(".history-delete-btn");
      if (deleteBtn) {
        e.stopPropagation();
        deleteChat(deleteBtn.dataset.id);
        return;
      }

      const item = e.target.closest(".history-item");
      if (item && historyList.contains(item)) {
        loadChat(item.dataset.id);
      }
    });
  }

  if (uploadBtn) {
    uploadBtn.addEventListener("click", () => fileUploadInput.click());
  }

  fileUploadInput.addEventListener("change", handleFileUpload);

  if (adminBtn) {
    adminBtn.addEventListener("click", () => {
      window.location.href = "/admin";
    });
  }

  logoutBtn.addEventListener("click", async () => {
    const token = localStorage.getItem(LS_TOKEN);
    if (token) {
      try {
        await fetch(API_ENDPOINTS.logout, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });
      } catch (e) {
        console.warn("Logout API failed:", e);
      }
    }

    currentChatId = null;
    currentSessionId = null;
    chats = [];

    localStorage.removeItem(LS_TOKEN);
    localStorage.removeItem(LS_USER);

    window.location.href = "/";
  });
}

// =========================
//      FILE UPLOAD
// =========================
async function ensureSessionForUpload(fileName) {
  if (currentSessionId) return currentSessionId;

  if (!currentChatId) {
    currentChatId = createNewChatEntry(
      `Fichier: ${fileName}`,
      getSelectedPersonalityId(),
    );
    if (chatTitle) chatTitle.textContent = "Nouvelle conversation";
  }

  const token = localStorage.getItem(LS_TOKEN);
  const selectedPersonalityId = getSelectedPersonalityId();
  const response = await fetch(
    `${API_ENDPOINTS.newChat}?personality_id=${encodeURIComponent(selectedPersonalityId)}`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    },
  );

  if (!response.ok) {
    throw new Error("Impossible de creer une session");
  }

  const data = await response.json();
  currentSessionId = data.id;

  const chat = chats.find((c) => c.id === currentChatId);
  if (chat) {
    chat.sessionId = currentSessionId;
    chat.date = Date.now();
    saveHistory();
    renderHistoryList();
  }

  return currentSessionId;
}

async function handleFileUpload(e) {
  const file = e.target.files[0];
  if (!file) return;

  const loadingBubble = addMessage("", "bot", true);
  loadingBubble.innerHTML = `<span class="upload-spinner"></span> 📊 Analyse de <strong>${file.name}</strong> en cours...`;

  try {
    const sessionId = await ensureSessionForUpload(file.name);
    const token = localStorage.getItem(LS_TOKEN);
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(
      `${API_ENDPOINTS.sessions}/${sessionId}/upload`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      },
    );

    const data = await response.json().catch(() => ({}));
    loadingBubble.classList.remove("typing");

    if (response.ok) {
      loadingBubble.innerHTML = `📄 <strong>${file.name}</strong> importé pour cette session.`;
    } else {
      loadingBubble.innerHTML = `❌ Échec de l'import : ${data.detail || "Erreur inconnue"}`;
    }
  } catch (err) {
    loadingBubble.classList.remove("typing");
    loadingBubble.innerHTML = `❌ Erreur lors de l'import : ${err.message}`;
  }

  fileUploadInput.value = "";
}

// =========================
//        USER CARD
// =========================
function initUserCard() {
  const username = (localStorage.getItem(LS_USER) || "Utilisateur").trim();
  if (sidebarUserName) sidebarUserName.textContent = username;
  if (sidebarAvatar) sidebarAvatar.textContent = makeInitials(username);
  checkAdminRole();
}

function checkAdminRole() {
  try {
    const payload = getTokenPayload();
    if (payload && payload.role === "admin") {
      if (adminBtn) adminBtn.style.display = "block";
      const roleEl = document.getElementById("sidebarUserRole");
      if (roleEl) roleEl.textContent = "Administrateur";
    }
  } catch (e) {
    console.warn("Admin check failed:", e);
  }
}

function makeInitials(name) {
  const clean = name.replace(/\s+/g, " ").trim();
  if (!clean) return "UA";
  const parts = clean.split(" ");
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

// =========================
//     HISTORY SYSTEM
// =========================

// clé localStorage propre à l'utilisateur connecté
function getHistoryKey() {
  const payload = getTokenPayload();
  const userId = payload ? payload.user_id : null;
  if (userId !== null && userId !== undefined) {
    return `${LS_HISTORY}_uid_${userId}`;
  }

  const username = (localStorage.getItem(LS_USER) || "anonymous")
    .trim()
    .toLowerCase();
  return `${LS_HISTORY}_${username}`;
}

function parseSessionDate(session) {
  const raw = session.updated_at || session.created_at;
  const parsed = raw ? Date.parse(raw) : NaN;
  return Number.isFinite(parsed) ? parsed : Date.now();
}

function buildChatsFromSessions(sessions) {
  return sessions.map((session) => ({
    id: `session_${session.id}`,
    title:
      session.title && session.title !== "New chat"
        ? session.title
        : "Nouvelle conversation",
    sessionId: session.id,
    date: parseSessionDate(session),
    messages: [],
  }));
}

function findLegacyHistory(backendSessionIds) {
  if (!backendSessionIds || backendSessionIds.size === 0) return null;

  const currentKey = getHistoryKey();
  const prefix = `${LS_HISTORY}_`;

  for (let i = 0; i < localStorage.length; i += 1) {
    const key = localStorage.key(i);
    if (!key || !key.startsWith(prefix) || key === currentKey) continue;

    const raw = localStorage.getItem(key);
    if (!raw) continue;

    let parsed = null;
    try {
      parsed = JSON.parse(raw);
    } catch (e) {
      parsed = null;
    }

    if (!Array.isArray(parsed)) continue;

    const hasMatch = parsed.some(
      (chat) => chat && chat.sessionId && backendSessionIds.has(chat.sessionId),
    );

    if (hasMatch) {
      return parsed;
    }
  }

  return null;
}

async function loadHistory() {
  // IMPORTANT : on charge bien l'historique du user connecté
  const raw = localStorage.getItem(getHistoryKey());
  chats = raw ? JSON.parse(raw) : [];
  renderHistoryList();

  const token = localStorage.getItem(LS_TOKEN);
  if (!token) return;

  try {
    const response = await fetch(API_ENDPOINTS.sessions, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });

    if (!response.ok) return;

    const sessions = await response.json();

    if (Array.isArray(sessions) && sessions.length === 0 && chats.length > 0) {
      // Keep local history if the backend temporarily returns no sessions.
      return;
    }

    // Garder uniquement les chats locaux appartenant aux sessions backend de CE user
    const backendSessionIds = new Set(sessions.map((s) => s.id));

    if (chats.length === 0 && backendSessionIds.size > 0) {
      const legacyChats = findLegacyHistory(backendSessionIds);
      chats = legacyChats || buildChatsFromSessions(sessions);
    }

    chats = chats.filter((chat) => {
      // On garde les chats pas encore persistés en DB (sessionId null)
      if (!chat.sessionId) return true;
      return backendSessionIds.has(chat.sessionId);
    });

    // Mettre à jour les titres depuis le backend
    for (const session of sessions) {
      const chat = chats.find((c) => c.sessionId === session.id);
      if (chat) {
        if (session.title && session.title !== "New chat") {
          chat.title = session.title;
        }

        if (
          session.personality_id !== undefined &&
          session.personality_id !== null
        ) {
          chat.personalityId = session.personality_id;
        }
      }
    }

    saveHistory();
    renderHistoryList();
  } catch (e) {
    console.warn("Failed to sync sessions from backend:", e);
  }
}

function saveHistory() {
  localStorage.setItem(getHistoryKey(), JSON.stringify(chats));
}

function renderHistoryList() {
  if (!historyList) return;

  if (chats.length === 0) {
    historyList.innerHTML = `
      <div class="empty-history">
        <div class="empty-hint">
          Aucune discussion pour le moment.<br/>
          Clique sur <b>Nouveau chat</b> pour commencer.
        </div>
      </div>`;
    return;
  }

  const groups = groupByDate(chats);
  let html = "";

  for (const [label, items] of Object.entries(groups)) {
    if (items.length === 0) continue;

    html += `<div class="history-group-label">${label}</div>`;

    for (const chat of items) {
      const isActive = chat.id === currentChatId;
      html += `
        <div class="history-item ${isActive ? "active" : ""}" data-id="${chat.id}">
          <span class="history-item-title">${escapeHtml(chat.title)}</span>
          <button class="history-delete-btn" data-id="${chat.id}" title="Supprimer">✕</button>
        </div>`;
    }
  }

  historyList.innerHTML = html;
}

function groupByDate(chats) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  const sevenDays = new Date(today);
  sevenDays.setDate(sevenDays.getDate() - 7);

  const groups = {
    "Aujourd'hui": [],
    Hier: [],
    "7 derniers jours": [],
    "Plus ancien": [],
  };

  const sorted = [...chats].sort((a, b) => b.date - a.date);

  for (const chat of sorted) {
    const d = new Date(chat.date);
    d.setHours(0, 0, 0, 0);

    if (d >= today) groups["Aujourd'hui"].push(chat);
    else if (d >= yesterday) groups["Hier"].push(chat);
    else if (d >= sevenDays) groups["7 derniers jours"].push(chat);
    else groups["Plus ancien"].push(chat);
  }

  return groups;
}

function createNewChatEntry(firstMessage, personalityId = 0) {
  const id = "chat_" + Date.now();

  const initialTitle =
    firstMessage && firstMessage.trim()
      ? firstMessage.trim().slice(0, 40)
      : "Nouvelle conversation";

  const chat = {
    id,
    title: initialTitle,
    sessionId: null,
    personalityId,
    date: Date.now(),
    messages: [],
  };

  chats.unshift(chat);
  saveHistory();
  renderHistoryList();
  return id;
}

function appendMessageToChat(chatId, role, text, sources = null) {
  const chat = chats.find((c) => c.id === chatId);
  if (!chat) return;

  chat.messages.push({ role, text, sources, ts: Date.now() });
  chat.date = Date.now();

  saveHistory();
}

function appendMessageToCurrentChat(role, text, sources = null) {
  if (!currentChatId) return;
  appendMessageToChat(currentChatId, role, text, sources);
}

function shouldSyncChatMessages(chat) {
  return !!(chat && chat.sessionId);
}

function normalizeBackendMessage(message) {
  const role = message.role === "assistant" ? "bot" : message.role || "user";
  return {
    role,
    text: message.content || "",
    sources: Array.isArray(message.sources) ? message.sources : [],
    ts: Date.now(),
  };
}

async function fetchSessionMessages(sessionId) {
  const token = localStorage.getItem(LS_TOKEN);
  if (!token) return null;

  try {
    const response = await fetch(
      `${API_BASE_URL}/chat/sessions/${sessionId}/messages`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );

    if (!response.ok) return null;

    const data = await response.json().catch(() => null);
    if (!Array.isArray(data)) return null;

    return data.map(normalizeBackendMessage);
  } catch (e) {
    console.warn("Failed to load session messages:", e);
    return null;
  }
}

async function loadChat(chatId) {
  const chat = chats.find((c) => c.id === chatId);
  if (!chat) return;

  currentChatId = chatId;
  currentSessionId = chat.sessionId || null;
  localStorage.setItem(LS_ACTIVE_CHAT, chatId);

  const activeChatId = chatId;
  if (shouldSyncChatMessages(chat)) {
    const syncedMessages = await fetchSessionMessages(currentSessionId);
    if (syncedMessages && currentChatId === activeChatId) {
      chat.messages = syncedMessages;
      saveHistory();
    }
  }

  messagesEl.innerHTML = "";
  const chatOutputNew = document.createElement("div");
  chatOutputNew.id = "chat-output";
  messagesEl.appendChild(chatOutputNew);

  for (const msg of chat.messages) {
    addMessage(msg.text, msg.role, false, msg.sources || null);
  }

  if (chatTitle) chatTitle.textContent = chat.title;

  const selectEl = document.getElementById("persona");
  if (selectEl) {
    const exists = [...selectEl.options].some(
      (o) => o.value === String(chat.personalityId),
    );

    if (
      chat.personalityId !== undefined &&
      chat.personalityId !== null &&
      exists
    ) {
      selectEl.value = String(chat.personalityId);
      localStorage.setItem(LS_SELECTED_PERSONALITY, String(chat.personalityId));
    } else {
      selectEl.value = "0";
      localStorage.setItem(LS_SELECTED_PERSONALITY, "0");
    }
  }

  renderHistoryList();
  inputEl.focus();
}

async function deleteChat(chatId) {
  const chat = chats.find((c) => c.id === chatId);
  if (!chat) return;

  // Si la session existe côté backend, on la supprime aussi
  if (chat.sessionId) {
    const token = localStorage.getItem(LS_TOKEN);

    try {
      await fetch(`${API_BASE_URL}/chat/sessions/${chat.sessionId}`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
    } catch (e) {
      console.warn("Failed to delete chat session from backend:", e);
    }
  }

  chats = chats.filter((c) => c.id !== chatId);
  saveHistory();

  if (currentChatId === chatId) {
    handleNewChat();
  } else {
    renderHistoryList();
  }
}

// =========================
//        CHAT LOGIC
// =========================
function applyChatMetadataAfterResponse(
  data,
  selectedPersonalityId,
  targetChatId = currentChatId,
) {
  if (!data || !data.session_id) return;

  const chatId = targetChatId || currentChatId;
  if (!chatId) return;

  const chat = chats.find((c) => c.id === chatId);
  if (!chat) return;

  chat.sessionId = data.session_id;

  if (chatId === currentChatId) {
    currentSessionId = data.session_id;
  }

  if (!chat.personalityId && chat.personalityId !== 0) {
    chat.personalityId = selectedPersonalityId;
  }

  if (data.title) {
    chat.title = data.title;
    if (chatTitle && chatId === currentChatId) {
      chatTitle.textContent = data.title;
    }
  }

  chat.date = Date.now();
  saveHistory();
  renderHistoryList();
}

function parseSSEEvents(rawChunk) {
  const events = [];
  const blocks = rawChunk.split("\n\n");

  for (const block of blocks) {
    if (!block.trim()) continue;
    const lines = block.split("\n");
    const dataLines = lines
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim());

    if (dataLines.length === 0) continue;

    const dataText = dataLines.join("\n");
    try {
      events.push(JSON.parse(dataText));
    } catch (e) {
      // Ignore malformed event chunks.
    }
  }

  return events;
}

async function streamChatResponse(
  payload,
  token,
  botBubble,
  selectedPersonalityId,
  targetChatId,
) {
  const response = await fetch(API_ENDPOINTS.chatStream, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok || !response.body) {
    const data = await response.json().catch(() => ({}));
    const errorMsg = data.detail || `Erreur serveur (${response.status})`;
    throw new Error(errorMsg);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let pending = "";
  let streamedText = "";
  let finalSources = [];
  let donePayload = null;

  const isActiveChat = () => currentChatId === targetChatId;

  if (isActiveChat()) {
    botBubble.classList.remove("typing");
    renderBotContent(botBubble, "", []);
  }

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    pending += decoder.decode(value, { stream: true });
    const parts = pending.split("\n\n");
    pending = parts.pop() || "";

    for (const part of parts) {
      const events = parseSSEEvents(`${part}\n\n`);
      for (const event of events) {
        if (event.type === "token") {
          streamedText += event.content || "";
          if (isActiveChat()) {
            renderBotContent(botBubble, streamedText, []);
            scrollToBottom();
          }
        } else if (event.type === "done") {
          donePayload = event;
          finalSources = Array.isArray(event.sources) ? event.sources : [];
        } else if (event.type === "error") {
          throw new Error(event.message || "Erreur streaming");
        }
      }
    }
  }

  if (pending.trim()) {
    const events = parseSSEEvents(pending);
    for (const event of events) {
      if (event.type === "token") {
        streamedText += event.content || "";
      } else if (event.type === "done") {
        donePayload = event;
        finalSources = Array.isArray(event.sources) ? event.sources : [];
      } else if (event.type === "error") {
        throw new Error(event.message || "Erreur streaming");
      }
    }
  }

  const answerText =
    streamedText || (donePayload && donePayload.answer) || "No answer";
  if (isActiveChat()) {
    renderBotContent(botBubble, answerText, finalSources);
  }

  if (donePayload) {
    applyChatMetadataAfterResponse(
      donePayload,
      selectedPersonalityId,
      targetChatId,
    );
  }

  appendMessageToChat(targetChatId, "bot", answerText, finalSources);
  if (isActiveChat()) {
    speakText(answerText);
  }
}

async function handleSend() {
  const text = inputEl.value.trim();
  if (!text) return;

  const selectedPersonalityId = getSelectedPersonalityId();

  const activeChat = chats.find((c) => c.id === currentChatId);
  if (
    currentSessionId &&
    activeChat &&
    activeChat.personalityId !== undefined &&
    activeChat.personalityId !== null &&
    Number(activeChat.personalityId) !== Number(selectedPersonalityId)
  ) {
    handleNewChat();
  }

  if (!currentChatId) {
    currentChatId = createNewChatEntry(text, selectedPersonalityId);
    localStorage.setItem(LS_ACTIVE_CHAT, currentChatId);
    if (chatTitle) chatTitle.textContent = "Nouvelle conversation";
  }

  const targetChatId = currentChatId;
  const targetSessionId = currentSessionId;

  addMessage(text, "user");
  appendMessageToChat(targetChatId, "user", text);

  inputEl.value = "";
  inputEl.focus();

  const botBubble = addMessage("...", "bot", true);
  const token = localStorage.getItem(LS_TOKEN);

  try {
    const payload = {
      message: text,
      session_id: targetSessionId,
      ...(targetSessionId ? {} : { personality_id: selectedPersonalityId }),
    };

    try {
      await streamChatResponse(
        payload,
        token,
        botBubble,
        selectedPersonalityId,
        targetChatId,
      );
      return;
    } catch (streamErr) {
      console.warn(
        "Streaming failed, fallback to classic chat endpoint:",
        streamErr,
      );
    }

    const response = await fetch(API_ENDPOINTS.chat, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      botBubble.classList.remove("typing");
      const errorMsg = data.detail || `Erreur serveur (${response.status})`;

      if (window.marked && typeof window.marked.parse === "function") {
        botBubble.innerHTML = window.marked.parse(errorMsg);
      } else {
        botBubble.textContent = errorMsg;
      }

      if (response.status === 401 || response.status === 403) {
        localStorage.removeItem(LS_TOKEN);
        localStorage.removeItem(LS_USER);
        setTimeout(() => {
          window.location.href = "/";
        }, 400);
      }
      return;
    }

    if (currentChatId === targetChatId) {
      botBubble.classList.remove("typing");
    }
    const answerText = data.answer || "No answer";
    const sources = Array.isArray(data.sources) ? data.sources : [];

    if (currentChatId === targetChatId) {
      renderBotContent(botBubble, answerText, sources);
    }
    applyChatMetadataAfterResponse(data, selectedPersonalityId, targetChatId);
    appendMessageToChat(targetChatId, "bot", answerText, sources);
    if (currentChatId === targetChatId) {
      speakText(answerText);
    }
  } catch (err) {
    if (currentChatId === targetChatId) {
      botBubble.classList.remove("typing");
      botBubble.textContent = "Erreur de connexion au serveur";
    }
  }
}

function handleNewChat() {
  currentChatId = null;
  currentSessionId = null;
  localStorage.removeItem(LS_ACTIVE_CHAT);

  messagesEl.innerHTML = "";
  const chatOutputNew = document.createElement("div");
  chatOutputNew.id = "chat-output";
  messagesEl.appendChild(chatOutputNew);

  if (chatTitle) chatTitle.textContent = "Nouveau chat";
  inputEl.value = "";

  const selectEl = document.getElementById("persona");
  const saved = localStorage.getItem(LS_SELECTED_PERSONALITY) || "0";
  if (selectEl && [...selectEl.options].some((o) => o.value === saved)) {
    selectEl.value = saved;
  } else if (selectEl) {
    selectEl.value = "0";
    localStorage.setItem(LS_SELECTED_PERSONALITY, "0");
  }

  inputEl.focus();
  renderHistoryList();
}

// =========================
//        UI HELPERS
// =========================
function addMessage(text, role, isTyping = false, sources = null) {
  const bubble = document.createElement("div");
  bubble.className = `message ${role}` + (isTyping ? " typing" : "");

  if (role === "user") {
    bubble.textContent = text;
  } else if (role === "bot") {
    renderBotContent(bubble, text, sources || []);
  }

  messagesEl.appendChild(bubble);
  scrollToBottom();
  return bubble;
}

function renderBotContent(container, text, sources) {
  try {
    const markedLib =
      window.marked || (typeof marked !== "undefined" ? marked : null);

    if (markedLib && typeof markedLib.parse === "function") {
      container.innerHTML = markedLib.parse(text);
    } else {
      container.textContent = text;
    }
  } catch (err) {
    container.textContent = text;
  }

  if (!Array.isArray(sources) || sources.length === 0) return;

  const sourcesEl = document.createElement("div");
  sourcesEl.className = "sources";

  const title = document.createElement("div");
  title.className = "sources-title";
  title.textContent = "Sources";
  sourcesEl.appendChild(title);

  const list = document.createElement("div");
  list.className = "sources-list";

  sources.forEach((item, idx) => {
    const row = document.createElement("div");
    row.className = "source-item";

    const index = document.createElement("span");
    index.className = "source-index";
    index.textContent = `[${idx + 1}]`;

    const label = document.createElement("span");
    label.className = "source-label";
    const file = item.filename || "Document";
    const fileType = item.file_type ? ` (${item.file_type})` : "";
    const pages = item.page_count ? ` - ${item.page_count} pages` : "";
    const pageNumber =
      item.page_number !== null && item.page_number !== undefined
        ? ` - page ${item.page_number}`
        : "";
    const chunk = item.chunk_label ? ` - ${item.chunk_label}` : "";
    label.textContent = `${file}${fileType}${pages}${pageNumber}${chunk}`;

    row.appendChild(index);
    row.appendChild(label);
    list.appendChild(row);

    if (item.score !== null && item.score !== undefined) {
      const meta = document.createElement("div");
      meta.className = "source-meta";
      meta.textContent = `Pertinence: ${Number(item.score).toFixed(3)}`;
      list.appendChild(meta);
    }
  });

  sourcesEl.appendChild(list);
  container.appendChild(sourcesEl);
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// =========================
//   PERSONA SELECT SYNC
// =========================
async function initPersonaSelect() {
  const selectEl = document.getElementById("persona");
  if (!selectEl) return;

  const refreshPersonaList = async () => {
    const previousValue =
      localStorage.getItem(LS_SELECTED_PERSONALITY) || selectEl.value || "0";

    await populatePersonaSelect();

    // Toujours restaurer depuis localStorage d'abord
    const savedValue = localStorage.getItem(LS_SELECTED_PERSONALITY) || previousValue;
    const stillExists = [...selectEl.options].some(
      (o) => o.value === String(savedValue),
    );

    if (stillExists) {
      selectEl.value = String(savedValue);
      localStorage.setItem(LS_SELECTED_PERSONALITY, String(savedValue));
      return;
    }

    selectEl.value = "0";
    localStorage.setItem(LS_SELECTED_PERSONALITY, "0");
    // Ne créer un nouveau chat que si aucun chat n'est actif
    if (!currentChatId) {
      handleNewChat();
    }
  };

  await refreshPersonaList();

  selectEl.addEventListener("change", () => {
    localStorage.setItem(LS_SELECTED_PERSONALITY, selectEl.value || "0");
    handleNewChat();
  });

  // retour sur la page, même depuis cache navigateur
  window.addEventListener("pageshow", refreshPersonaList);

  // retour sur l'onglet
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      refreshPersonaList();
    }
  });

  // mise à jour si l'admin change les personnalités dans un autre onglet
  window.addEventListener("storage", (e) => {
    if (e.key === LS_PERSONALITIES_VERSION) {
      refreshPersonaList();
    }
  });

  // ouverture manuelle du select
  selectEl.addEventListener("mousedown", refreshPersonaList);
}

async function populatePersonaSelect() {
  const selectEl = document.getElementById("persona");
  if (!selectEl) return;

  const token = localStorage.getItem(LS_TOKEN);
  if (!token) return;

  try {
    const response = await fetch(API_ENDPOINTS.personalities, {
      method: "GET",
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${token}`,
        "Cache-Control": "no-cache",
        Pragma: "no-cache",
      },
    });

    const data = await response.json().catch(() => []);

    if (!response.ok) {
      selectEl.innerHTML = `<option value="0">Standard</option>`;
      return;
    }

    const personas = Array.isArray(data) ? data : [];

    selectEl.innerHTML = personas
      .map((p) => `<option value="${p.id}">${p.name}</option>`)
      .join("");

    if (![...selectEl.options].some((o) => o.value === "0")) {
      selectEl.innerHTML =
        `<option value="0">Standard</option>` + selectEl.innerHTML;
    }
  } catch (e) {
    console.warn("Failed to load personalities:", e);
    selectEl.innerHTML = `<option value="0">Standard</option>`;
  }
}

function getSelectedPersonalityId() {
  const selectEl = document.getElementById("persona");
  if (!selectEl || !selectEl.value) return 0;

  const id = Number(selectEl.value);
  return Number.isFinite(id) ? id : 0;
}

// ----------------------------------------------------------------------------
// MICROPHONE / STT (Web Audio API)
// ----------------------------------------------------------------------------
let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];
let activeStream = null;
const recordBtnIdleLabel = recordBtn ? recordBtn.textContent.trim() : "REC";

if (recordBtn) {
  const canRecord =
    typeof window !== "undefined" &&
    "MediaRecorder" in window &&
    navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === "function";

  if (!canRecord) {
    setRecordButtonState("unsupported");
  } else {
    setRecordButtonState("idle");
    recordBtn.addEventListener("click", () => {
      if (isRecording) {
        stopRecording();
      } else {
        startRecording();
      }
    });
  }
}

function setRecordButtonState(state) {
  if (!recordBtn) return;

  recordBtn.disabled = false;
  recordBtn.style.color = "";
  recordBtn.classList.remove("is-recording", "is-processing", "is-disabled");

  if (state === "recording") {
    recordBtn.textContent = "STOP";
    recordBtn.style.color = "#ff6b6b";
    recordBtn.classList.add("is-recording");
    recordBtn.title = "Stop recording";
  } else if (state === "processing") {
    recordBtn.textContent = "WAIT";
    recordBtn.classList.add("is-processing");
    recordBtn.title = "Processing audio";
  } else if (state === "unsupported") {
    recordBtn.textContent = "N/A";
    recordBtn.disabled = true;
    recordBtn.classList.add("is-disabled");
    recordBtn.title = "Microphone not supported";
  } else {
    recordBtn.textContent = recordBtnIdleLabel || "REC";
    recordBtn.title = "Start recording";
  }
}

async function startRecording() {
  try {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setRecordButtonState("unsupported");
      alert("Microphone is not supported in this browser.");
      return;
    }

    activeStream = await navigator.mediaDevices.getUserMedia({ audio: true });

    let options = { mimeType: "audio/webm" };
    if (!MediaRecorder.isTypeSupported("audio/webm")) {
      options = { mimeType: "audio/mp4" };
      if (!MediaRecorder.isTypeSupported("audio/mp4")) {
        options = {};
      }
    }

    mediaRecorder = new MediaRecorder(activeStream, options);
    audioChunks = [];

    mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        audioChunks.push(event.data);
      }
    };

    mediaRecorder.onstop = async () => {
      isRecording = false;
      setRecordButtonState("processing");

      const audioBlob = new Blob(audioChunks, {
        type: mediaRecorder.mimeType || "audio/webm",
      });

      try {
        const wavBlob = await convertToWavRecord(audioBlob);
        await uploadAudioForSTT(wavBlob);
      } catch (err) {
        console.error("Error converting/uploading audio:", err);
        alert("Failed to process audio.");
      } finally {
        setRecordButtonState("idle");
        if (activeStream) {
          activeStream.getTracks().forEach((track) => track.stop());
          activeStream = null;
        }
      }
    };

    mediaRecorder.start();
    isRecording = true;
    setRecordButtonState("recording");
  } catch (err) {
    console.error("Microphone error:", err);
    setRecordButtonState("idle");
    alert("Microphone access denied or not available.");
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
}

// Convert browser audio to standard 16kHz PCM WAV
async function convertToWavRecord(blob) {
  const arrayBuffer = await blob.arrayBuffer();

  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const audioBuffer = await new Promise((resolve, reject) => {
    ctx.decodeAudioData(arrayBuffer, resolve, reject);
  });
  ctx.close();

  const targetSampleRate = 16000;
  const frameCount = Math.ceil(audioBuffer.duration * targetSampleRate);
  const oac = new OfflineAudioContext(1, frameCount, targetSampleRate);

  const source = oac.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(oac.destination);
  source.start();

  const renderedBuffer = await oac.startRendering();
  const floatData = renderedBuffer.getChannelData(0);

  const wavBuffer = encodeWAV(floatData, targetSampleRate);
  return new Blob([wavBuffer], { type: "audio/wav" });
}

function encodeWAV(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  // RIFF chunk descriptor
  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(view, 8, "WAVE");

  // fmt sub-chunk
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true); // chunkSize
  view.setUint16(20, 1, true); // audioFormat (1 = PCM)
  view.setUint16(22, 1, true); // numChannels
  view.setUint32(24, sampleRate, true); // sampleRate
  view.setUint32(28, sampleRate * 2, true); // byteRate
  view.setUint16(32, 2, true); // blockAlign
  view.setUint16(34, 16, true); // bitsPerSample

  // data sub-chunk
  writeString(view, 36, "data");
  view.setUint32(40, samples.length * 2, true);

  // write PCM samples
  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    let s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }

  return buffer;
}

function writeString(view, offset, string) {
  for (let i = 0; i < string.length; i++) {
    view.setUint8(offset + i, string.charCodeAt(i));
  }
}

async function uploadAudioForSTT(wavBlob) {
  if (!wavBlob) return;
  const token = localStorage.getItem(LS_TOKEN);
  if (!token) return;

  const formData = new FormData();
  formData.append("file", wavBlob, "recording.wav");

  try {
    const response = await fetch(`${API_BASE_URL}/chat/speech-to-text`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
      },
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Erreur STT HTTP ${response.status}`);
    }

    const data = await response.json();
    if (data.text) {
      if (inputEl.value) {
        inputEl.value += " " + data.text;
      } else {
        inputEl.value = data.text;
      }
      inputEl.focus();
    }
  } catch (err) {
    console.error("STT Error:", err);
    alert("Impossible de transcrire l'audio.");
  }
}

// ──────────────────────────────────────────────────────────────────────────────
//  STATE
// ──────────────────────────────────────────────────────────────────────────────

const TTS_STORAGE_KEY = "sont_tts_enabled";

let ttsEnabled = localStorage.getItem(TTS_STORAGE_KEY) === "true";
let ttsAudio = null; // current HTMLAudioElement
let ttsSpeaking = false;

// ──────────────────────────────────────────────────────────────────────────────
//  STRIP MARKDOWN  (léger, côté client — le service le fait aussi en fallback)
// ──────────────────────────────────────────────────────────────────────────────

function ttsStripMarkdown(text) {
  return text
    .replace(/```[\s\S]*?```/g, "") // blocs code
    .replace(/`[^`]*`/g, "") // code inline
    .replace(/^#{1,6}\s+/gm, "") // headers
    .replace(/\*{1,3}([^*]+)\*{1,3}/g, "$1") // bold/italic
    .replace(/_{1,3}([^_]+)_{1,3}/g, "$1") // underscore bold/italic
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1") // liens → label
    .replace(/^\s*[-*+]\s+/gm, "") // listes à puces
    .replace(/^\s*\d+\.\s+/gm, "") // listes numérotées
    .replace(/^[-_*]{3,}\s*$/gm, "") // séparateurs
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

// ──────────────────────────────────────────────────────────────────────────────
//  CORE : appel API TTS
// ──────────────────────────────────────────────────────────────────────────────

const TTS_MAX_CHARS = 2000;

async function speakText(rawText) {
  if (!ttsEnabled) return;

  // Stop l'audio en cours si l'utilisateur demande une nouvelle réponse
  ttsStop();

  const text = ttsStripMarkdown(rawText).slice(0, TTS_MAX_CHARS);
  if (!text) return;

  const token = localStorage.getItem(LS_TOKEN);
  if (!token) return;

  try {
    const response = await fetch(`${API_BASE_URL}/chat/tts`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ text }),
    });

    if (!response.ok) {
      console.warn("TTS request failed:", response.status);
      return;
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);

    ttsAudio = new Audio(url);
    ttsSpeaking = true;
    updateTtsToggleUI();

    ttsAudio.addEventListener("ended", () => {
      URL.revokeObjectURL(url);
      ttsSpeaking = false;
      ttsAudio = null;
      updateTtsToggleUI();
    });

    ttsAudio.play();
  } catch (err) {
    console.error("TTS error:", err);
    ttsSpeaking = false;
    updateTtsToggleUI();
  }
}

function ttsStop() {
  if (ttsAudio) {
    ttsAudio.pause();
    ttsAudio.src = "";
    ttsAudio = null;
  }
  ttsSpeaking = false;
  updateTtsToggleUI();
}

// ──────────────────────────────────────────────────────────────────────────────
//  BOUTON TOGGLE TTS (injecté dans la sidebar-footer)
// ──────────────────────────────────────────────────────────────────────────────

function createTtsToggleButton() {
  const btn = document.createElement("button");
  btn.id = "ttsToggleBtn";
  btn.type = "button";
  btn.className = "btn btn-block tts-toggle-btn";
  updateTtsToggleLabel(btn);

  btn.addEventListener("click", () => {
    if (ttsSpeaking) {
      // Si lecture en cours → stop immédiat
      ttsStop();
      return;
    }
    ttsEnabled = !ttsEnabled;
    localStorage.setItem(TTS_STORAGE_KEY, ttsEnabled);
    updateTtsToggleUI();
  });

  return btn;
}

function updateTtsToggleLabel(btn) {
  const el = btn || document.getElementById("ttsToggleBtn");
  if (!el) return;

  if (ttsSpeaking) {
    el.textContent = "⏹ Stop TTS";
    el.classList.add("tts-active");
  } else if (ttsEnabled) {
    el.textContent = "🔊 TTS : Activé";
    el.classList.add("tts-active");
  } else {
    el.textContent = "🔇 TTS : Désactivé";
    el.classList.remove("tts-active");
  }
}

function updateTtsToggleUI() {
  updateTtsToggleLabel();
}

// ──────────────────────────────────────────────────────────────────────────────
//  INJECTION DANS LE DOM  (sidebar-footer, avant le user-card)
// ──────────────────────────────────────────────────────────────────────────────

function injectTtsButton() {
  const footer = document.querySelector(".sidebar-footer");
  if (!footer) return;

  const userCard = footer.querySelector(".user-card");
  const btn = createTtsToggleButton();

  if (userCard) {
    footer.insertBefore(btn, userCard);
  } else {
    footer.appendChild(btn);
  }
}

// ──────────────────────────────────────────────────────────────────────────────
//  INIT
// ──────────────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  injectTtsButton();
  updateTtsToggleUI();
});

// Si DOMContentLoaded déjà passé (script chargé en defer/async)
if (document.readyState !== "loading") {
  injectTtsButton();
  updateTtsToggleUI();
}