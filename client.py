######################################################################################
# client.py — Client terminal (bonus) pour le serveur de chat WebSocket
#
# Permet d'utiliser le chat directement depuis la console, avec les mêmes
# commandes que l'interface web (/help, /msg, /join, /time, /ping, /clear, ...).
#
# Installation :  pip install -r requirements.txt
# Lancement    :  python client.py
######################################################################################

import asyncio
import json
import os
import sys
import time

import websockets

URL = os.environ.get("CHAT_URL", "ws://localhost:5000")

# Couleurs ANSI (QoL terminal)
C = {
    "reset": "\033[0m", "gray": "\033[90m", "green": "\033[92m",
    "red": "\033[91m", "yellow": "\033[93m", "cyan": "\033[96m",
    "magenta": "\033[95m", "bold": "\033[1m",
}
if os.name == "nt":
    os.system("")  # active les codes ANSI sous Windows


def color(txt, c):
    return f"{C.get(c,'')}{txt}{C['reset']}"


def show(data):
    """Affiche joliment un message reçu du serveur."""
    t = data.get("type")
    if t == "welcome":
        print(color(f"✅ Connecté en tant que {data['name']} (rôle {data['role']}) "
                    f"dans #{data['room']}", "green"))
    elif t == "message":
        who = color(data["name"], "cyan")
        print(f"[{data['time']}] {who}: {data['text']}")
    elif t == "private":
        tag = color("🔒 privé", "magenta")
        print(f"[{data['time']}] {tag} {data['from']} → {data['to']}: {data['text']}")
    elif t == "system":
        lvl = {"error": "red", "success": "green"}.get(data.get("level"), "gray")
        print(color(data["text"], lvl))
    elif t == "users":
        names = ", ".join(u["name"] for u in data["users"])
        print(color(f"👥 #{data['room']} : {names}", "gray"))
    elif t == "rooms":
        rs = ", ".join(f"{r['name']}({r['count']})" for r in data["rooms"])
        print(color(f"🚪 Salons : {rs}", "gray"))
    elif t == "pong":
        if data.get("t"):
            print(color(f"🏓 Latence : {int(time.time()*1000) - data['t']} ms", "yellow"))
    elif t == "clear":
        os.system("cls" if os.name == "nt" else "clear")
    elif t == "nick":
        print(color(f"✏️ Pseudo changé en {data['name']}", "green"))
    elif t == "role":
        print(color(f"🎖️ Nouveau rôle : {data['role']}", "green"))
    elif t == "roomchange":
        print(color(f"➡️ Tu es dans #{data['room']}", "cyan"))
    elif t in ("kicked", "banned", "timeout"):
        print(color(f"⛔ {data.get('reason', t)}", "red"))


async def receiver(ws):
    try:
        async for raw in ws:
            try:
                show(json.loads(raw))
            except json.JSONDecodeError:
                pass
    except websockets.exceptions.ConnectionClosed:
        print(color("\n[Déconnecté du serveur]", "red"))


async def sender(ws):
    loop = asyncio.get_event_loop()
    while True:
        # input() bloquant exécuté dans un thread pour ne pas figer asyncio
        text = await loop.run_in_executor(None, sys.stdin.readline)
        if not text:
            break
        text = text.rstrip("\n")
        if not text:
            continue
        if text in ("/quit", "/exit"):
            await ws.close()
            break
        await ws.send(json.dumps({"type": "message", "text": text, "t": int(time.time() * 1000)}))


async def main():
    name = input("Choisis ton pseudo : ").strip()
    print(color(f"Connexion à {URL} ...", "gray"))
    try:
        async with websockets.connect(URL) as ws:
            await ws.send(json.dumps({"type": "join", "name": name}))
            print(color("Tape /help pour les commandes, /quit pour partir.\n", "gray"))
            await asyncio.gather(receiver(ws), sender(ws))
    except (OSError, websockets.exceptions.WebSocketException) as e:
        print(color(f"Connexion impossible : {e}. Le serveur est-il lancé ?", "red"))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAu revoir !")
