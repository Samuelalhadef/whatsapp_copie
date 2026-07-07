######################################################################################
# server.py — Serveur de chat WebSocket complet (façon WhatsApp)
#
# Fonctionnalités :
#   - Connexion de plusieurs clients, échange de messages en temps réel
#   - Déconnexion propre (ne fait pas planter les autres)
#   - Choix / changement de pseudo, persistance dans data/users.json
#   - Messages privés (/msg), /time, /ping, /clear, /help, /who, /rooms
#   - Rooms/salons : créer, rejoindre, quitter
#   - Rôles : user / moderator / admin  (+ /kick /ban /mute /setadmin ...)
#   - Timeout d'inactivité (déconnexion automatique)
#   - Sécurité : anti-flood, validation des entrées, bans par pseudo + IP,
#                autorisations par rôle, jeton admin comparé en temps constant
#
# Installation :  pip install -r requirements.txt
# Lancement    :  python server.py
######################################################################################

import asyncio
import json
import os
import re
import hmac
import datetime
import socket

import websockets

# ============================ CONFIGURATION ============================

# None = écoute sur toutes les interfaces IPv4 ET IPv6.
# (Sur Windows, le navigateur résout « localhost » en IPv6 ::1 : si on n'écoute
#  qu'en IPv4 sur 0.0.0.0, la connexion est refusée et l'écran de login reste bloqué.)
SERVER = None
PORT = 5000
FORMAT = "utf-8"

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")

DEFAULT_ROOM = "general"

# --- Sécurité ---
ADMIN_TOKEN = os.environ.get("CHAT_ADMIN_TOKEN", "admin123")  # à changer en prod !
MAX_MSG_LEN = 2000                 # longueur max d'un message
NICK_RE = re.compile(r"^[A-Za-z0-9À-ÖØ-öø-ÿ_\-]{2,20}$")  # pseudo autorisé (accents OK, pas d'espace)
FLOOD_WINDOW = 5.0                 # secondes
FLOOD_MAX = 6                      # messages max par fenêtre avant sanction
FLOOD_MUTE = 8.0                   # durée de mute automatique (secondes)
IDLE_TIMEOUT = 600                 # déconnexion après X s sans activité (10 min)

# --- Rôles ---
ROLES = {"user": 0, "moderator": 1, "admin": 2}

# ============================ ÉTAT EN MÉMOIRE ============================

# ws -> Client
CLIENTS = {}
# nom_room -> set(ws)
ROOMS = {DEFAULT_ROOM: set()}


class Client:
    """Représente une session connectée."""
    def __init__(self, ws):
        self.ws = ws
        self.name = None
        self.role = "user"
        self.room = DEFAULT_ROOM
        self.ip = ws.remote_address[0] if ws.remote_address else "?"
        self.msg_times = []       # horodatages récents (anti-flood)
        self.muted_until = 0.0    # timestamp epoch de fin de mute temporaire


# ============================ PERSISTANCE JSON ============================

def load_db():
    """Charge la base des utilisateurs, ou en crée une vide."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding=FORMAT) as f:
                db = json.load(f)
        except (json.JSONDecodeError, OSError):
            db = {}
    else:
        db = {}
    db.setdefault("users", {})   # nom -> {role, muted, created}
    db.setdefault("bans", {"names": [], "ips": []})
    return db


def save_db(db):
    """Écrit la base sur le disque."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USERS_FILE, "w", encoding=FORMAT) as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


DB = load_db()


def register_user(name, role="user"):
    """Enregistre / met à jour un utilisateur dans la base."""
    u = DB["users"].get(name, {})
    u.setdefault("created", datetime.datetime.now().isoformat(timespec="seconds"))
    u.setdefault("muted", False)
    u["role"] = u.get("role", role)
    DB["users"][name] = u
    save_db(DB)


def has_admin():
    return any(u.get("role") == "admin" for u in DB["users"].values())


# ============================ HELPERS RÉSEAU ============================

def now_hms():
    return datetime.datetime.now().strftime("%H:%M")


def now_loop():
    """Horloge monotone de la boucle asyncio (pour flood / mute / idle)."""
    return asyncio.get_event_loop().time()


async def send(ws, payload):
    try:
        await ws.send(json.dumps(payload, ensure_ascii=False))
    except websockets.exceptions.ConnectionClosed:
        pass


async def notify(ws, text, level="info"):
    """Message système adressé à un seul client (info / success / error)."""
    await send(ws, {"type": "system", "text": text, "level": level, "time": now_hms()})


async def broadcast_room(room, payload, exclude=None):
    for ws in list(ROOMS.get(room, set())):
        if ws is exclude:
            continue
        await send(ws, payload)


async def system_to_room(room, text, exclude=None):
    await broadcast_room(room, {"type": "system", "text": text, "level": "info",
                                "time": now_hms()}, exclude=exclude)


def find_client_by_name(name):
    for c in CLIENTS.values():
        if c.name and c.name.lower() == name.lower():
            return c
    return None


async def send_room_users(room):
    """Envoie la liste des membres (avec rôle) d'une room à ses membres."""
    members = [{"name": CLIENTS[ws].name, "role": CLIENTS[ws].role}
               for ws in ROOMS.get(room, set()) if ws in CLIENTS and CLIENTS[ws].name]
    await broadcast_room(room, {"type": "users", "room": room, "users": members})


async def send_rooms_list(ws=None):
    """Envoie la liste des rooms + effectif à un client (ou à tous)."""
    payload = {"type": "rooms",
               "rooms": [{"name": r, "count": len(m)} for r, m in ROOMS.items()]}
    if ws:
        await send(ws, payload)
    else:
        for w in list(CLIENTS.keys()):
            await send(w, payload)


# ============================ AUTORISATIONS ============================

def level(role):
    return ROLES.get(role, 0)


async def require(client, min_role):
    """Vérifie que le client a au moins `min_role`, sinon prévient."""
    if level(client.role) < level(min_role):
        await notify(client.ws, f"⛔ Permission refusée : rôle « {min_role} » requis.", "error")
        return False
    return True


# ============================ COMMANDES ============================

async def cmd_help(client, args):
    lines = [
        "📖 Commandes disponibles :",
        "/help — cette aide",
        "/nick <pseudo> — changer de pseudo",
        "/msg <pseudo> <texte> — message privé",
        "/who — membres de la room courante",
        "/rooms — liste des salons",
        "/create <salon> — créer un salon",
        "/join <salon> — rejoindre un salon",
        "/leave — revenir au salon général",
        "/time — heure du serveur",
        "/ping — latence",
        "/clear — effacer l'affichage",
    ]
    if level(client.role) >= level("moderator"):
        lines += ["— Modération —", "/kick <pseudo>", "/mute <pseudo>", "/unmute <pseudo>"]
    if level(client.role) >= level("admin"):
        lines += ["— Admin —", "/ban <pseudo>", "/unban <pseudo>",
                  "/setmodo <pseudo>", "/remmodo <pseudo>",
                  "/setadmin <pseudo>", "/remadmin <pseudo>"]
    lines.append("/auth <jeton> — obtenir le rôle admin")
    await notify(client.ws, "\n".join(lines), "info")


async def cmd_time(client, args):
    full = datetime.datetime.now().strftime("%A %d %B %Y — %H:%M:%S")
    await notify(client.ws, f"🕐 Heure du serveur : {full}", "info")


async def cmd_ping(client, args, t=None):
    # Le client mesure la latence à partir du timestamp qu'il a joint.
    await send(client.ws, {"type": "pong", "t": t})


async def cmd_clear(client, args):
    await send(client.ws, {"type": "clear"})


async def cmd_nick(client, args):
    if not args:
        await notify(client.ws, "Usage : /nick <nouveau_pseudo>", "error")
        return
    new = args[0].strip()
    if not NICK_RE.match(new):
        await notify(client.ws, "Pseudo invalide (2-20 caractères : lettres, chiffres, _ , -).", "error")
        return
    if find_client_by_name(new):
        await notify(client.ws, "Ce pseudo est déjà utilisé.", "error")
        return
    if new in DB["bans"]["names"]:
        await notify(client.ws, "Ce pseudo est banni.", "error")
        return
    old = client.name
    client.name = new
    # Conserver le rôle : on migre l'entrée de la base
    role = DB["users"].get(old, {}).get("role", client.role)
    register_user(new, role)
    client.role = DB["users"][new]["role"]
    await send(client.ws, {"type": "nick", "name": new, "role": client.role})
    await system_to_room(client.room, f"« {old} » est désormais « {new} »")
    await send_room_users(client.room)


async def cmd_msg(client, args):
    if len(args) < 2:
        await notify(client.ws, "Usage : /msg <pseudo> <message>", "error")
        return
    target_name = args[0]
    text = " ".join(args[1:])[:MAX_MSG_LEN]
    target = find_client_by_name(target_name)
    if not target:
        await notify(client.ws, f"Utilisateur « {target_name} » introuvable ou hors ligne.", "error")
        return
    payload = {"type": "private", "from": client.name, "to": target.name,
               "text": text, "time": now_hms()}
    await send(target.ws, payload)
    await send(client.ws, payload)   # copie pour l'expéditeur


async def cmd_who(client, args):
    members = [f"{CLIENTS[ws].name} ({CLIENTS[ws].role})"
               for ws in ROOMS.get(client.room, set()) if ws in CLIENTS]
    await notify(client.ws, f"👥 Salon « {client.room} » : " + ", ".join(sorted(members)), "info")


async def cmd_rooms(client, args):
    listing = ", ".join(f"{r} ({len(m)})" for r, m in ROOMS.items())
    await notify(client.ws, f"🚪 Salons : {listing}", "info")


async def move_to_room(client, new_room):
    old = client.room
    ROOMS.get(old, set()).discard(client.ws)
    ROOMS.setdefault(new_room, set()).add(client.ws)
    client.room = new_room
    await system_to_room(old, f"{client.name} a quitté le salon", exclude=None)
    await send(client.ws, {"type": "roomchange", "room": new_room})
    await system_to_room(new_room, f"{client.name} a rejoint le salon", exclude=client.ws)
    await send_room_users(old)
    await send_room_users(new_room)
    await send_rooms_list()


async def cmd_create(client, args):
    if not args:
        await notify(client.ws, "Usage : /create <nom_du_salon>", "error")
        return
    room = args[0].strip()
    if not NICK_RE.match(room):
        await notify(client.ws, "Nom de salon invalide (2-20 caractères).", "error")
        return
    if room in ROOMS:
        await notify(client.ws, "Ce salon existe déjà. Utilise /join.", "error")
        return
    ROOMS[room] = set()
    await notify(client.ws, f"✅ Salon « {room} » créé.", "success")
    await move_to_room(client, room)


async def cmd_join(client, args):
    if not args:
        await notify(client.ws, "Usage : /join <nom_du_salon>", "error")
        return
    room = args[0].strip()
    if room not in ROOMS:
        await notify(client.ws, "Ce salon n'existe pas. Crée-le avec /create.", "error")
        return
    if room == client.room:
        await notify(client.ws, "Tu es déjà dans ce salon.", "info")
        return
    await move_to_room(client, room)


async def cmd_leave(client, args):
    if client.room == DEFAULT_ROOM:
        await notify(client.ws, "Tu es déjà dans le salon général.", "info")
        return
    await move_to_room(client, DEFAULT_ROOM)


# --- Modération / Admin ---

async def cmd_kick(client, args):
    if not await require(client, "moderator"):
        return
    if not args:
        await notify(client.ws, "Usage : /kick <pseudo>", "error")
        return
    target = find_client_by_name(args[0])
    if not target:
        await notify(client.ws, "Utilisateur introuvable.", "error")
        return
    if level(target.role) >= level(client.role):
        await notify(client.ws, "Tu ne peux pas expulser un membre de rôle égal ou supérieur.", "error")
        return
    await send(target.ws, {"type": "kicked", "reason": f"Expulsé par {client.name}"})
    await system_to_room(target.room, f"👢 {target.name} a été expulsé par {client.name}")
    await target.ws.close()


async def cmd_mute(client, args):
    if not await require(client, "moderator"):
        return
    if not args:
        await notify(client.ws, "Usage : /mute <pseudo>", "error")
        return
    target = find_client_by_name(args[0])
    if not target:
        await notify(client.ws, "Utilisateur introuvable.", "error")
        return
    if level(target.role) >= level(client.role):
        await notify(client.ws, "Impossible de rendre muet un rôle égal ou supérieur.", "error")
        return
    DB["users"].setdefault(target.name, {})["muted"] = True
    save_db(DB)
    await notify(target.ws, "🔇 Tu as été rendu muet par un modérateur.", "error")
    await system_to_room(target.room, f"🔇 {target.name} a été rendu muet par {client.name}")


async def cmd_unmute(client, args):
    if not await require(client, "moderator"):
        return
    if not args:
        await notify(client.ws, "Usage : /unmute <pseudo>", "error")
        return
    name = args[0]
    if name in DB["users"]:
        DB["users"][name]["muted"] = False
        save_db(DB)
    target = find_client_by_name(name)
    if target:
        target.muted_until = 0.0
        await notify(target.ws, "🔊 Tu peux de nouveau parler.", "success")
    await notify(client.ws, f"🔊 {name} n'est plus muet.", "success")


async def cmd_ban(client, args):
    if not await require(client, "admin"):
        return
    if not args:
        await notify(client.ws, "Usage : /ban <pseudo>", "error")
        return
    name = args[0]
    target = find_client_by_name(name)
    if target and level(target.role) >= level(client.role):
        await notify(client.ws, "Tu ne peux pas bannir un rôle égal ou supérieur.", "error")
        return
    if name not in DB["bans"]["names"]:
        DB["bans"]["names"].append(name)
    if target and target.ip not in DB["bans"]["ips"]:
        DB["bans"]["ips"].append(target.ip)
    save_db(DB)
    if target:
        await send(target.ws, {"type": "banned", "reason": f"Banni par {client.name}"})
        await system_to_room(target.room, f"🔨 {target.name} a été banni par {client.name}")
        await target.ws.close()
    await notify(client.ws, f"🔨 {name} est banni.", "success")


async def cmd_unban(client, args):
    if not await require(client, "admin"):
        return
    if not args:
        await notify(client.ws, "Usage : /unban <pseudo>", "error")
        return
    name = args[0]
    if name in DB["bans"]["names"]:
        DB["bans"]["names"].remove(name)
        save_db(DB)
        await notify(client.ws, f"✅ {name} n'est plus banni.", "success")
    else:
        await notify(client.ws, "Ce pseudo n'est pas banni.", "info")


async def set_role(client, args, role, min_giver="admin"):
    if not await require(client, min_giver):
        return
    if not args:
        await notify(client.ws, f"Usage : /set… <pseudo>", "error")
        return
    name = args[0]
    DB["users"].setdefault(name, {"created": datetime.datetime.now().isoformat(timespec='seconds'),
                                   "muted": False})
    DB["users"][name]["role"] = role
    save_db(DB)
    target = find_client_by_name(name)
    if target:
        target.role = role
        await send(target.ws, {"type": "role", "role": role})
        await notify(target.ws, f"🎖️ Ton rôle est maintenant : {role}", "success")
        await send_room_users(target.room)
    await notify(client.ws, f"🎖️ {name} est désormais {role}.", "success")


async def cmd_auth(client, args):
    """Bootstrap admin via jeton (comparaison en temps constant)."""
    if not args:
        await notify(client.ws, "Usage : /auth <jeton>", "error")
        return
    if hmac.compare_digest(args[0], ADMIN_TOKEN):
        client.role = "admin"
        register_user(client.name, "admin")
        DB["users"][client.name]["role"] = "admin"
        save_db(DB)
        await send(client.ws, {"type": "role", "role": "admin"})
        await notify(client.ws, "🎖️ Authentification réussie : tu es admin.", "success")
        await send_room_users(client.room)
    else:
        await notify(client.ws, "⛔ Jeton invalide.", "error")
        print(f"[SECURITE] Tentative d'auth échouée depuis {client.ip} ({client.name})")


COMMANDS = {
    "help": cmd_help, "aide": cmd_help,
    "nick": cmd_nick, "pseudo": cmd_nick,
    "msg": cmd_msg, "mp": cmd_msg, "w": cmd_msg,
    "who": cmd_who, "rooms": cmd_rooms,
    "create": cmd_create, "join": cmd_join, "leave": cmd_leave,
    "time": cmd_time, "clear": cmd_clear, "help_": cmd_help,
    "kick": cmd_kick, "mute": cmd_mute, "unmute": cmd_unmute,
    "ban": cmd_ban, "unban": cmd_unban,
    "setmodo": lambda c, a: set_role(c, a, "moderator"),
    "remmodo": lambda c, a: set_role(c, a, "user"),
    "setadmin": lambda c, a: set_role(c, a, "admin"),
    "remadmin": lambda c, a: set_role(c, a, "user"),
    "auth": cmd_auth,
}


# ============================ ANTI-FLOOD ============================

def check_flood(client):
    """Retourne True si le client peut envoyer, applique un mute auto sinon."""
    t = now_loop()
    if t < client.muted_until:
        return False
    client.msg_times = [x for x in client.msg_times if t - x < FLOOD_WINDOW]
    client.msg_times.append(t)
    if len(client.msg_times) > FLOOD_MAX:
        client.muted_until = t + FLOOD_MUTE
        return False
    return True


# ============================ TRAITEMENT D'UN MESSAGE ============================

async def handle_text(client, text, t=None):
    """Traite le texte d'un message : commande (/…) ou message de room."""
    text = text.strip()
    if not text:
        return

    # --- Commande ---
    if text.startswith("/"):
        parts = text[1:].split()
        if not parts:
            return
        cmd = parts[0].lower()
        args = parts[1:]
        if cmd == "ping":
            await cmd_ping(client, args, t=t)
            return
        handler = COMMANDS.get(cmd)
        if handler:
            await handler(client, args)
        else:
            await notify(client.ws, f"Commande inconnue : /{cmd}. Tape /help.", "error")
        return

    # --- Message normal : vérifs de sécurité ---
    if DB["users"].get(client.name, {}).get("muted"):
        await notify(client.ws, "🔇 Tu es muet, tu ne peux pas écrire.", "error")
        return
    if not check_flood(client):
        await notify(client.ws, "🚫 Trop de messages : ralentis (anti-flood).", "error")
        return
    if len(text) > MAX_MSG_LEN:
        text = text[:MAX_MSG_LEN]

    payload = {"type": "message", "room": client.room, "name": client.name,
               "role": client.role, "text": text, "time": now_hms(), "id": None}
    await broadcast_room(client.room, payload)
    print(f"[{client.room}] {client.name}: {text}")


# ============================ CONNEXION ============================

async def do_join(client, requested_name):
    """Enregistre le pseudo, applique bans, charge le rôle."""
    name = (requested_name or "").strip()

    # Sécurité : validation du pseudo
    if not NICK_RE.match(name):
        await notify(client.ws, "Pseudo invalide (2-20 caractères : lettres, chiffres, _ , -).", "error")
        return False
    if client.ip in DB["bans"]["ips"] or name in DB["bans"]["names"]:
        await send(client.ws, {"type": "banned", "reason": "Tu es banni de ce serveur."})
        return False
    if find_client_by_name(name):
        await notify(client.ws, "Ce pseudo est déjà connecté. Choisis-en un autre.", "error")
        return False

    client.name = name

    # Premier utilisateur enregistré -> admin (bootstrap)
    role = DB["users"].get(name, {}).get("role")
    if role is None:
        role = "admin" if not has_admin() else "user"
    register_user(name, role)
    client.role = DB["users"][name]["role"]

    ROOMS.setdefault(client.room, set()).add(client.ws)
    await send(client.ws, {"type": "welcome", "name": client.name, "role": client.role,
                           "room": client.room})
    await system_to_room(client.room, f"{client.name} a rejoint la discussion", exclude=client.ws)
    await send_room_users(client.room)
    await send_rooms_list(client.ws)
    print(f"[SERVER] {client.name} ({client.ip}) connecté — rôle {client.role}")
    return True


async def handle_client(ws):
    """Boucle de vie d'une connexion, avec timeout d'inactivité."""
    client = Client(ws)
    CLIENTS[ws] = client
    print(f"[SERVER] Nouvelle connexion : {client.ip}  (actives : {len(CLIENTS)})")

    try:
        while True:
            # --- Timeout d'inactivité ---
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                await notify(ws, "⌛ Déconnecté pour inactivité.", "error")
                await send(ws, {"type": "timeout"})
                break

            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue  # entrée malformée ignorée (robustesse / sécurité)

            mtype = msg.get("type")

            if mtype == "join":
                await do_join(client, msg.get("name"))

            elif mtype == "message":
                if client.name:
                    await handle_text(client, str(msg.get("text", "")), t=msg.get("t"))

            elif mtype == "typing":
                if client.name:
                    await broadcast_room(client.room,
                                         {"type": "typing", "name": client.name,
                                          "state": bool(msg.get("state"))}, exclude=ws)

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:  # robustesse : une erreur d'un client n'affecte pas les autres
        print(f"[SERVER] Erreur avec {client.ip} : {e!r}")
    finally:
        CLIENTS.pop(ws, None)
        ROOMS.get(client.room, set()).discard(ws)
        if client.name:
            print(f"[SERVER] {client.name} déconnecté  (actives : {len(CLIENTS)})")
            await system_to_room(client.room, f"{client.name} a quitté la discussion")
            await send_room_users(client.room)
            await send_rooms_list()
        else:
            print(f"[SERVER] {client.ip} déconnecté sans pseudo")


# ============================ DÉMARRAGE ============================

async def start():
    local_ip = socket.gethostbyname(socket.gethostname())
    print(f"[SERVER] Base utilisateurs : {USERS_FILE}")
    print(f"[SERVER] Serveur WebSocket sur toutes les interfaces (IPv4 + IPv6), port {PORT}")
    print(f"[SERVER] Navigateur : ws://localhost:{PORT}  (réseau : ws://{local_ip}:{PORT})")
    print(f"[SERVER] Jeton admin : {ADMIN_TOKEN!r}  (variable CHAT_ADMIN_TOKEN pour changer)")
    print("[SERVER] En attente de connexions...")
    # ping_interval : keepalive TCP intégré (détection des coupures réseau)
    async with websockets.serve(handle_client, SERVER, PORT,
                                 ping_interval=20, ping_timeout=20, max_size=2 ** 16):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        print("\n[SERVER] Arrêt du serveur.")
