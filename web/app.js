/* =========================================================================
   WhatsApp clone — logique client (WebSocket)
   Gère : rooms, rôles, messages privés, commandes, sécurité côté affichage.
   ========================================================================= */

const WS_URL = `ws://${location.hostname || "localhost"}:5000`;

// --- DOM ---
const loginEl      = document.getElementById("login");
const appEl        = document.getElementById("app");
const loginForm    = document.getElementById("login-form");
const nameInput    = document.getElementById("name-input");
const loginStatus  = document.getElementById("login-status");
const messagesEl   = document.getElementById("messages");
const msgForm      = document.getElementById("msg-form");
const msgInput     = document.getElementById("msg-input");
const sendBtn      = document.getElementById("send-btn");
const myAvatar     = document.getElementById("my-avatar");
const myNameEl     = document.getElementById("my-name");
const myRoleEl     = document.getElementById("my-role");
const convSubtitle = document.getElementById("conv-subtitle");
const convRoomName = document.getElementById("conv-room-name");
const roomsList    = document.getElementById("rooms-list");
const newRoomBtn   = document.getElementById("new-room-btn");
const helpBtn      = document.getElementById("help-btn");

let ws = null;
let myName = "";
let myRole = "user";
let currentRoom = "general";
let typingTimeout = null;
let typingUsers = new Set();

/* ---------- Utilitaires ---------- */

const NAME_COLORS = ["#e542a3","#3ba3ec","#00a884","#f0b429","#a35bcd","#ff6b6b","#009688","#795548"];
function colorFor(name) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h);
  return NAME_COLORS[Math.abs(h) % NAME_COLORS.length];
}
function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}
function scrollToBottom() { messagesEl.scrollTop = messagesEl.scrollHeight; }
function nowTime() {
  return new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}
const ROLE_ICON = { admin: "👑", moderator: "🛡️", user: "" };

/* ---------- Connexion ---------- */

// Normalise un pseudo saisi librement (ex : « Louis Alhadef ») vers un pseudo
// accepté par le serveur : 2-20 caractères, lettres/chiffres/accents/_/-, sans espace.
function sanitizeName(raw) {
  return raw
    .trim()
    .replace(/\s+/g, "_")                          // espaces -> underscore
    .replace(/[^A-Za-z0-9À-ÖØ-öø-ÿ_\-]/g, "")      // retire les caractères interdits (emoji, ponctuation…)
    .slice(0, 20);
}

loginForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const clean = sanitizeName(nameInput.value);
  if (clean.length < 2) {
    showLoginError("Pseudo trop court : 2 à 20 caractères (lettres, chiffres, _ , -).");
    nameInput.focus();
    return;
  }
  if (clean !== nameInput.value.trim()) {
    nameInput.value = clean;                        // montre le pseudo réellement retenu
  }
  myName = clean;
  connect();
});

function inApp() { return !appEl.classList.contains("hidden"); }

function connect() {
  loginStatus.className = "login-status";
  loginStatus.textContent = "Connexion au serveur…";
  if (ws) { try { ws.close(); } catch {} }
  try {
    ws = new WebSocket(WS_URL);
  } catch {
    return showLoginError("Impossible de créer la connexion.");
  }
  ws.onopen = () => ws.send(JSON.stringify({ type: "join", name: myName }));
  ws.onmessage = (ev) => {
    let data; try { data = JSON.parse(ev.data); } catch { return; }
    handleServerMessage(data);
  };
  ws.onerror = () =>
    showLoginError("Connexion impossible. Le serveur (python server.py) est-il lancé ?");
  ws.onclose = () => {
    if (appEl.classList.contains("hidden")) return;
    addSystemMessage("Connexion perdue. Rechargez la page pour vous reconnecter.", "error");
    convSubtitle.textContent = "hors ligne";
  };
}

function showLoginError(text) {
  loginStatus.className = "login-status error";
  loginStatus.textContent = text;
}

/* ---------- Réception ---------- */

function handleServerMessage(data) {
  switch (data.type) {
    case "welcome":    onWelcome(data); break;
    case "message":    addMessage(data); break;
    case "private":    addPrivate(data); break;
    case "system":
      // Avant d'entrer dans l'app, une erreur (pseudo refusé…) doit être
      // visible sur la page de connexion, pas dans la zone de chat cachée.
      if (!inApp() && data.level === "error") showLoginError(data.text);
      else addSystemMessage(data.text, data.level);
      break;
    case "users":      updateUsers(data); break;
    case "rooms":      renderRooms(data.rooms); break;
    case "typing":     onTyping(data); break;
    case "pong":       onPong(data); break;
    case "clear":      clearMessages(); break;
    case "nick":       onNick(data); break;
    case "role":       onRole(data); break;
    case "roomchange": onRoomChange(data); break;
    case "kicked":     onKicked("👢 " + (data.reason || "Expulsé du serveur.")); break;
    case "banned":
      if (!inApp()) showLoginError("🔨 " + (data.reason || "Tu es banni de ce serveur."));
      else onKicked("🔨 " + (data.reason || "Tu es banni."));
      break;
    case "timeout":    onKicked("⌛ Déconnecté pour inactivité."); break;
  }
}

function onWelcome(data) {
  myName = data.name;
  myRole = data.role || "user";
  currentRoom = data.room || "general";
  loginEl.classList.add("hidden");
  appEl.classList.remove("hidden");
  myAvatar.textContent = myName.charAt(0).toUpperCase();
  myNameEl.textContent = myName;
  setMyRole(myRole);
  convRoomName.textContent = "# " + currentRoom;
  msgInput.focus();
  addSystemMessage(`Bienvenue ${myName} ! Tape /help pour voir les commandes.`, "success");
}

function setMyRole(role) {
  myRole = role;
  myRoleEl.textContent = (ROLE_ICON[role] ? ROLE_ICON[role] + " " : "") + role;
  myRoleEl.className = "role-badge " + role;
}

/* ---------- Messages ---------- */

function addMessage(data) {
  const isMine = data.name === myName;
  const el = document.createElement("div");
  el.className = "msg " + (isMine ? "out" : "in");
  let inner = "";
  if (!isMine) {
    const icon = ROLE_ICON[data.role] ? ROLE_ICON[data.role] + " " : "";
    inner += `<span class="sender" style="color:${colorFor(data.name)}">${icon}${escapeHtml(data.name)}</span>`;
  }
  inner += `<span class="text">${escapeHtml(data.text)}</span>`;
  inner += `<span class="meta">${escapeHtml(data.time || nowTime())}` +
           (isMine ? ` <span class="tick">${DOUBLE_TICK}</span>` : ``) + `</span>`;
  el.innerHTML = inner;
  messagesEl.appendChild(el);
  scrollToBottom();
}

function addPrivate(data) {
  const isMine = data.from === myName;
  const el = document.createElement("div");
  el.className = "msg private " + (isMine ? "out" : "in");
  const who = isMine ? `Vous → ${escapeHtml(data.to)}` : `${escapeHtml(data.from)} → vous`;
  el.innerHTML =
    `<span class="sender private-tag">🔒 privé · ${who}</span>` +
    `<span class="text">${escapeHtml(data.text)}</span>` +
    `<span class="meta">${escapeHtml(data.time || nowTime())}</span>`;
  messagesEl.appendChild(el);
  scrollToBottom();
}

function addSystemMessage(text, level = "info") {
  const el = document.createElement("div");
  el.className = "system-msg " + level;
  // conserve les retours à la ligne (ex : /help)
  el.innerHTML = escapeHtml(text).replace(/\n/g, "<br>");
  messagesEl.appendChild(el);
  scrollToBottom();
}

function clearMessages() {
  messagesEl.innerHTML = "";
  addSystemMessage("Affichage effacé.", "info");
}

const DOUBLE_TICK =
  `<svg viewBox="0 0 16 11" width="16" height="11"><path fill="currentColor" d="M11.071.653a.457.457 0 0 0-.304-.102.493.493 0 0 0-.381.178l-6.19 7.636-2.405-2.272a.463.463 0 0 0-.336-.146.47.47 0 0 0-.343.146l-.311.31a.445.445 0 0 0-.14.337c0 .136.047.25.14.343l3.11 3.11a.66.66 0 0 0 .439.208.634.634 0 0 0 .506-.257l6.822-8.815a.483.483 0 0 0 .102-.28.436.436 0 0 0-.14-.323zm.512 4.101 6.822-8.815.001-.001a.483.483 0 0 0 .102-.28.436.436 0 0 0-.14-.323l-.376-.31a.457.457 0 0 0-.304-.102.493.493 0 0 0-.381.178l-6.19 7.636"/></svg>`;

/* ---------- Participants / rooms ---------- */

function updateUsers(data) {
  if (data.room && data.room !== currentRoom) return;
  const users = data.users || [];
  if (users.length <= 1) {
    convSubtitle.textContent = "Vous êtes seul ici pour l'instant";
  } else {
    convSubtitle.textContent = users
      .map((u) => (ROLE_ICON[u.role] ? ROLE_ICON[u.role] + " " : "") + u.name)
      .join(", ");
  }
}

function renderRooms(rooms) {
  roomsList.innerHTML = "";
  rooms.forEach((r) => {
    const item = document.createElement("div");
    item.className = "chat-item" + (r.name === currentRoom ? " active" : "");
    item.innerHTML = `
      <div class="avatar group-avatar">#</div>
      <div class="chat-item-body">
        <div class="chat-item-top">
          <span class="chat-name"># ${escapeHtml(r.name)}</span>
        </div>
        <div class="chat-item-bottom">
          <span class="chat-preview">${r.count} participant${r.count > 1 ? "s" : ""}</span>
        </div>
      </div>`;
    item.onclick = () => {
      if (r.name !== currentRoom) sendRaw("/join " + r.name);
    };
    roomsList.appendChild(item);
  });
}

function onRoomChange(data) {
  currentRoom = data.room;
  convRoomName.textContent = "# " + currentRoom;
  clearMessages();
  addSystemMessage(`Tu es dans le salon « ${currentRoom} ».`, "info");
  // rafraîchir la surbrillance
  [...roomsList.children].forEach((el) => {
    el.classList.toggle("active", el.querySelector(".chat-name").textContent === "# " + currentRoom);
  });
}

/* ---------- Nick / rôle ---------- */

function onNick(data) {
  myName = data.name;
  myRole = data.role || myRole;
  myAvatar.textContent = myName.charAt(0).toUpperCase();
  myNameEl.textContent = myName;
  setMyRole(myRole);
  addSystemMessage(`Ton pseudo est maintenant « ${myName} ».`, "success");
}

function onRole(data) {
  setMyRole(data.role);
  addSystemMessage(`Ton rôle est maintenant : ${data.role}.`, "success");
}

/* ---------- Ping ---------- */

function onPong(data) {
  if (data.t) {
    const latency = Date.now() - data.t;
    addSystemMessage(`🏓 Pong ! Latence : ${latency} ms`, "info");
  }
}

/* ---------- Kick / ban / timeout ---------- */

function onKicked(text) {
  addSystemMessage(text, "error");
  if (ws) ws.close();
  msgInput.disabled = true;
  sendBtn.disabled = true;
  convSubtitle.textContent = "déconnecté";
}

/* ---------- Typing ---------- */

function onTyping(data) {
  if (data.state) typingUsers.add(data.name);
  else typingUsers.delete(data.name);
  if (typingUsers.size > 0) {
    const list = [...typingUsers];
    convSubtitle.textContent =
      list.length === 1 ? `${list[0]} est en train d'écrire…` : `${list.join(", ")} écrivent…`;
  }
}

/* ---------- Envoi ---------- */

function sendRaw(text) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: "message", text, t: Date.now() }));
}

// Les commandes /nick, /create et /join attendent un nom sans espace (2-20 car.).
// On normalise l'argument comme sur l'écran de login (« mon salon » -> « mon_salon »)
// pour éviter les erreurs « nom invalide ».
function normalizeCommand(text) {
  const m = text.match(/^\/(nick|pseudo|create|join)\s+(.+)$/i);
  if (!m) return text;
  const arg = sanitizeName(m[2]);
  return arg ? `/${m[1].toLowerCase()} ${arg}` : text;
}

function sendMessage() {
  const text = normalizeCommand(msgInput.value.trim());
  if (!text) return;
  // /clear est traité localement en plus (réponse serveur possible aussi)
  sendRaw(text);
  msgInput.value = "";
  if (ws && ws.readyState === WebSocket.OPEN)
    ws.send(JSON.stringify({ type: "typing", state: false }));
  msgInput.focus();
}

msgForm.addEventListener("submit", (e) => { e.preventDefault(); sendMessage(); });
sendBtn.addEventListener("click", sendMessage);

msgInput.addEventListener("input", () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (msgInput.value.startsWith("/")) return; // pas d'indicateur pour les commandes
  ws.send(JSON.stringify({ type: "typing", state: true }));
  clearTimeout(typingTimeout);
  typingTimeout = setTimeout(
    () => ws.send(JSON.stringify({ type: "typing", state: false })), 1500);
});

/* ---------- Boutons d'en-tête ---------- */

newRoomBtn.addEventListener("click", () => {
  const name = sanitizeName(prompt("Nom du nouveau salon :") || "");
  if (name.length >= 2) sendRaw("/create " + name);
  else if (name.length > 0) addSystemMessage("Nom de salon trop court (2 à 20 caractères).", "error");
});
helpBtn.addEventListener("click", () => sendRaw("/help"));
