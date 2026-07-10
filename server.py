# Serveur de chat en sockets (TCP)
# Projet du cours "Sockets en python"
# Pour lancer : python server.py
#
# Le serveur ecoute, accepte plusieurs clients (un thread par client)
# et fait passer les messages entre eux.

import socket
import threading
import json
import os
import re
import datetime

# ------------------- reglages -------------------
HOTE = "0.0.0.0"      # 0.0.0.0 = on accepte tout le monde sur le reseau
PORT = 5000
FICHIER = "users.json"   # fichier ou on stocke les pseudos et les bans
TIMEOUT = 300            # deconnexion automatique apres 300s sans rien ecrire
MAX_LONGUEUR = 500       # longueur maximum d'un message (securite)

# petites couleurs pour faire joli dans la console (bonus QoL)
VERT = "\033[92m"
ROUGE = "\033[91m"
JAUNE = "\033[93m"
CYAN = "\033[96m"
GRIS = "\033[90m"
RESET = "\033[0m"

# les niveaux des roles pour savoir qui a le droit de faire quoi
NIVEAU = {"user": 0, "moderator": 1, "admin": 2}

# ------------------- etat du serveur -------------------
# pour chaque client connecte on garde ses infos
clients = {}   # socket -> {"pseudo", "role", "salon", "muet", "ip"}
salons = {"general": []}   # nom du salon -> liste des sockets dedans
verrou = threading.Lock()  # pour ne pas modifier les listes en meme temps


# ------------------- fichier json -------------------
def charger():
    # on lit le fichier json si il existe, sinon on part de zero
    if os.path.exists(FICHIER):
        try:
            with open(FICHIER, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"users": {}, "bans_pseudos": [], "bans_ips": []}


def sauver():
    # on ecrit la base dans le fichier json
    with open(FICHIER, "w", encoding="utf-8") as f:
        json.dump(base, f, indent=2, ensure_ascii=False)


base = charger()


def y_a_un_admin():
    # est-ce qu'il existe deja un admin dans la base ?
    for infos in base["users"].values():
        if infos.get("role") == "admin":
            return True
    return False


# ------------------- envoi de messages -------------------
def envoyer(sock, texte):
    # envoie une ligne de texte a un client
    try:
        sock.send((texte + "\n").encode("utf-8"))
    except:
        pass


def envoyer_salon(salon, texte, sauf=None):
    # envoie un message a tout le monde dans un salon
    for s in list(salons.get(salon, [])):
        if s != sauf:
            envoyer(s, texte)


def trouver(pseudo):
    # cherche le socket d'un client a partir de son pseudo
    for s, infos in clients.items():
        if infos["pseudo"].lower() == pseudo.lower():
            return s
    return None


def heure():
    return datetime.datetime.now().strftime("%H:%M")


# ------------------- connexion d'un client -------------------
def rejoindre(sock, ip, pseudo):
    # verifie le pseudo et connecte le client. Renvoie True si ok.

    # securite : le pseudo doit etre correct (lettres, chiffres, _ ou -)
    if not re.match(r"^[A-Za-z0-9_\-]{2,16}$", pseudo):
        envoyer(sock, ROUGE + "Pseudo invalide (2 a 16 lettres/chiffres)." + RESET)
        return False

    # securite : les gens bannis ne peuvent pas revenir
    if pseudo in base["bans_pseudos"] or ip in base["bans_ips"]:
        envoyer(sock, ROUGE + "Tu es banni de ce serveur." + RESET)
        return False

    # on refuse deux fois le meme pseudo en meme temps
    if trouver(pseudo) is not None:
        envoyer(sock, ROUGE + "Ce pseudo est deja utilise." + RESET)
        return False

    # on regarde si le pseudo existe deja dans le fichier (pour garder son role)
    if pseudo in base["users"]:
        role = base["users"][pseudo]["role"]
    else:
        # le tout premier inscrit devient admin, les autres sont de simples users
        if y_a_un_admin():
            role = "user"
        else:
            role = "admin"
        base["users"][pseudo] = {"role": role}
        sauver()

    # on ajoute le client dans nos listes
    with verrou:
        clients[sock] = {"pseudo": pseudo, "role": role, "salon": "general",
                         "muet": False, "ip": ip}
        salons["general"].append(sock)

    envoyer(sock, VERT + "Bienvenue " + pseudo + " ! (role : " + role + ")" + RESET)
    envoyer(sock, GRIS + "Tape /help pour voir les commandes." + RESET)
    envoyer_salon("general", VERT + pseudo + " a rejoint le salon." + RESET, sauf=sock)
    print(pseudo + " connecte depuis " + ip + " (role " + role + ")")
    return True


def partir(sock):
    # quand un client s'en va on le retire proprement (sans crash pour les autres)
    with verrou:
        infos = clients.get(sock)
        if infos is None:
            return
        pseudo = infos["pseudo"]
        salon = infos["salon"]
        if sock in salons.get(salon, []):
            salons[salon].remove(sock)
        del clients[sock]
    envoyer_salon(salon, JAUNE + pseudo + " a quitte le salon." + RESET)
    print(pseudo + " deconnecte")
    try:
        sock.close()
    except:
        pass


# ------------------- les roles -------------------
def niveau(role):
    return NIVEAU.get(role, 0)


def a_le_droit(sock, role_mini):
    # verifie que le client a au moins le role demande
    infos = clients[sock]
    if niveau(infos["role"]) < niveau(role_mini):
        envoyer(sock, ROUGE + "Tu n'as pas la permission (role " + role_mini + " requis)." + RESET)
        return False
    return True


# ------------------- traitement des commandes -------------------
def traiter(sock, ligne):
    infos = clients[sock]
    pseudo = infos["pseudo"]

    # si ce n'est pas une commande, c'est un message normal
    if not ligne.startswith("/"):
        # securite : on coupe les messages trop longs
        if len(ligne) > MAX_LONGUEUR:
            ligne = ligne[:MAX_LONGUEUR]
        # securite : une personne rendue muette ne peut pas parler
        if infos["muet"]:
            envoyer(sock, ROUGE + "Tu es muet, tu ne peux pas ecrire." + RESET)
            return
        salon = infos["salon"]
        message = GRIS + "[" + heure() + "] " + RESET + CYAN + pseudo + RESET + " : " + ligne
        envoyer_salon(salon, message)
        print("[" + salon + "] " + pseudo + " : " + ligne)
        return

    # sinon on decoupe la commande
    morceaux = ligne.split(" ")
    commande = morceaux[0].lower()
    args = morceaux[1:]

    if commande == "/help":
        aide = [
            "Commandes :",
            "/help - cette aide",
            "/nick <pseudo> - changer de pseudo",
            "/msg <pseudo> <message> - message prive",
            "/time - heure du serveur",
            "/ping - mesurer la latence",
            "/clear - effacer l'ecran",
            "/who - qui est dans le salon",
            "/rooms - liste des salons",
            "/create <salon> - creer un salon",
            "/join <salon> - rejoindre un salon",
            "/leave - revenir au salon general",
        ]
        if niveau(infos["role"]) >= 1:
            aide.append("--- moderateur --- /kick /mute /unmute")
        if niveau(infos["role"]) >= 2:
            aide.append("--- admin --- /ban /unban /setmodo /remmodo /setadmin /remadmin")
        for l in aide:
            envoyer(sock, l)

    elif commande == "/nick":
        if len(args) < 1:
            envoyer(sock, "Usage : /nick <nouveau_pseudo>")
            return
        nouveau = args[0]
        if not re.match(r"^[A-Za-z0-9_\-]{2,16}$", nouveau):
            envoyer(sock, ROUGE + "Pseudo invalide." + RESET)
            return
        if trouver(nouveau) is not None:
            envoyer(sock, ROUGE + "Ce pseudo est deja pris." + RESET)
            return
        ancien = infos["pseudo"]
        # on garde le role et on met a jour le fichier json
        role = base["users"].get(ancien, {}).get("role", infos["role"])
        base["users"][nouveau] = {"role": role}
        sauver()
        infos["pseudo"] = nouveau
        envoyer_salon(infos["salon"], JAUNE + ancien + " s'appelle maintenant " + nouveau + RESET)

    elif commande == "/msg" or commande == "/mp":
        if len(args) < 2:
            envoyer(sock, "Usage : /msg <pseudo> <message>")
            return
        cible = trouver(args[0])
        if cible is None:
            envoyer(sock, ROUGE + "Ce pseudo n'est pas connecte." + RESET)
            return
        texte = " ".join(args[1:])
        envoyer(cible, JAUNE + "[prive de " + pseudo + "] " + RESET + texte)
        envoyer(sock, JAUNE + "[prive a " + args[0] + "] " + RESET + texte)

    elif commande == "/time":
        maintenant = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        envoyer(sock, "Heure du serveur : " + maintenant)

    elif commande == "/ping":
        # le client mesure lui meme le temps, on repond juste PONG
        envoyer(sock, "PONG")

    elif commande == "/who":
        salon = infos["salon"]
        noms = []
        for s in salons.get(salon, []):
            noms.append(clients[s]["pseudo"] + "(" + clients[s]["role"] + ")")
        envoyer(sock, "Dans #" + salon + " : " + ", ".join(noms))

    elif commande == "/rooms":
        liste = []
        for nom, membres in salons.items():
            liste.append(nom + "(" + str(len(membres)) + ")")
        envoyer(sock, "Salons : " + ", ".join(liste))

    elif commande == "/create":
        if len(args) < 1:
            envoyer(sock, "Usage : /create <salon>")
            return
        nom = args[0]
        if nom in salons:
            envoyer(sock, ROUGE + "Ce salon existe deja." + RESET)
            return
        salons[nom] = []
        envoyer(sock, VERT + "Salon " + nom + " cree." + RESET)
        changer_salon(sock, nom)

    elif commande == "/join":
        if len(args) < 1:
            envoyer(sock, "Usage : /join <salon>")
            return
        nom = args[0]
        if nom not in salons:
            envoyer(sock, ROUGE + "Ce salon n'existe pas (utilise /create)." + RESET)
            return
        changer_salon(sock, nom)

    elif commande == "/leave":
        if infos["salon"] == "general":
            envoyer(sock, "Tu es deja dans le salon general.")
        else:
            changer_salon(sock, "general")

    # ----- commandes de moderation -----
    elif commande == "/kick":
        if not a_le_droit(sock, "moderator"):
            return
        kick(sock, args)

    elif commande == "/mute":
        if not a_le_droit(sock, "moderator"):
            return
        muter(sock, args, True)

    elif commande == "/unmute":
        if not a_le_droit(sock, "moderator"):
            return
        muter(sock, args, False)

    # ----- commandes admin -----
    elif commande == "/ban":
        if not a_le_droit(sock, "admin"):
            return
        bannir(sock, args)

    elif commande == "/unban":
        if not a_le_droit(sock, "admin"):
            return
        if len(args) < 1:
            envoyer(sock, "Usage : /unban <pseudo>")
            return
        if args[0] in base["bans_pseudos"]:
            base["bans_pseudos"].remove(args[0])
            sauver()
            envoyer(sock, VERT + args[0] + " n'est plus banni." + RESET)
        else:
            envoyer(sock, "Ce pseudo n'est pas banni.")

    elif commande == "/setmodo":
        changer_role(sock, args, "moderator")
    elif commande == "/remmodo":
        changer_role(sock, args, "user")
    elif commande == "/setadmin":
        changer_role(sock, args, "admin")
    elif commande == "/remadmin":
        changer_role(sock, args, "user")

    else:
        envoyer(sock, "Commande inconnue : " + commande + " (tape /help)")


def changer_salon(sock, nouveau):
    # deplace un client d'un salon a un autre
    infos = clients[sock]
    ancien = infos["salon"]
    with verrou:
        if sock in salons.get(ancien, []):
            salons[ancien].remove(sock)
        salons[nouveau].append(sock)
        infos["salon"] = nouveau
    envoyer_salon(ancien, JAUNE + infos["pseudo"] + " a quitte le salon." + RESET)
    envoyer(sock, VERT + "Tu es maintenant dans #" + nouveau + RESET)
    envoyer_salon(nouveau, VERT + infos["pseudo"] + " a rejoint le salon." + RESET, sauf=sock)


def kick(sock, args):
    if len(args) < 1:
        envoyer(sock, "Usage : /kick <pseudo>")
        return
    cible = trouver(args[0])
    if cible is None:
        envoyer(sock, ROUGE + "Ce pseudo n'est pas connecte." + RESET)
        return
    # securite : on ne peut pas kick quelqu'un de role egal ou superieur
    if niveau(clients[cible]["role"]) >= niveau(clients[sock]["role"]):
        envoyer(sock, ROUGE + "Tu ne peux pas kick ce role." + RESET)
        return
    envoyer(cible, ROUGE + "Tu as ete expulse par " + clients[sock]["pseudo"] + RESET)
    partir(cible)


def muter(sock, args, valeur):
    if len(args) < 1:
        envoyer(sock, "Usage : /mute <pseudo>")
        return
    cible = trouver(args[0])
    if cible is None:
        envoyer(sock, ROUGE + "Ce pseudo n'est pas connecte." + RESET)
        return
    if niveau(clients[cible]["role"]) >= niveau(clients[sock]["role"]):
        envoyer(sock, ROUGE + "Tu ne peux pas mute ce role." + RESET)
        return
    clients[cible]["muet"] = valeur
    if valeur:
        envoyer(cible, ROUGE + "Tu as ete rendu muet." + RESET)
        envoyer(sock, VERT + args[0] + " est muet." + RESET)
    else:
        envoyer(cible, VERT + "Tu peux de nouveau parler." + RESET)
        envoyer(sock, VERT + args[0] + " n'est plus muet." + RESET)


def bannir(sock, args):
    if len(args) < 1:
        envoyer(sock, "Usage : /ban <pseudo>")
        return
    nom = args[0]
    cible = trouver(nom)
    if cible is not None and niveau(clients[cible]["role"]) >= niveau(clients[sock]["role"]):
        envoyer(sock, ROUGE + "Tu ne peux pas bannir ce role." + RESET)
        return
    # on ajoute le pseudo (et l'ip si la personne est connectee) a la liste des bans
    if nom not in base["bans_pseudos"]:
        base["bans_pseudos"].append(nom)
    if cible is not None:
        ip = clients[cible]["ip"]
        if ip not in base["bans_ips"]:
            base["bans_ips"].append(ip)
    sauver()
    envoyer(sock, ROUGE + nom + " a ete banni." + RESET)
    if cible is not None:
        envoyer(cible, ROUGE + "Tu as ete banni du serveur." + RESET)
        partir(cible)


def changer_role(sock, args, role):
    # seuls les admins peuvent donner des roles
    if not a_le_droit(sock, "admin"):
        return
    if len(args) < 1:
        envoyer(sock, "Usage : /set... <pseudo>")
        return
    nom = args[0]
    # on met a jour le fichier json
    if nom not in base["users"]:
        base["users"][nom] = {"role": role}
    else:
        base["users"][nom]["role"] = role
    sauver()
    # et si la personne est connectee on change son role tout de suite
    cible = trouver(nom)
    if cible is not None:
        clients[cible]["role"] = role
        envoyer(cible, VERT + "Ton nouveau role est : " + role + RESET)
    envoyer(sock, VERT + nom + " est maintenant " + role + RESET)


# ------------------- boucle qui s'occupe d'un client -------------------
def gerer_client(sock, adresse):
    ip = adresse[0]
    sock.settimeout(TIMEOUT)   # pour la deconnexion automatique
    tampon = ""
    pseudo_ok = False
    try:
        while True:
            # on recoit des donnees (des bytes)
            try:
                morceau = sock.recv(1024)
            except socket.timeout:
                envoyer(sock, ROUGE + "Deconnecte pour inactivite." + RESET)
                break
            if not morceau:
                break   # le client est parti

            tampon += morceau.decode("utf-8", "ignore")
            # il peut y avoir plusieurs lignes d'un coup, on les traite une par une
            while "\n" in tampon:
                ligne, tampon = tampon.split("\n", 1)
                ligne = ligne.strip()
                if ligne == "":
                    continue
                if not pseudo_ok:
                    # la toute premiere ligne envoyee est le pseudo
                    if rejoindre(sock, ip, ligne):
                        pseudo_ok = True
                    else:
                        return   # pseudo refuse, on arrete
                else:
                    traiter(sock, ligne)
    except:
        # si erreur (deconnexion brutale) on ne fait pas planter le serveur
        pass
    finally:
        partir(sock)


# ------------------- demarrage du serveur -------------------
def demarrer():
    serveur = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # pour pouvoir relancer le serveur tout de suite sans erreur "adresse deja utilisee"
    serveur.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    serveur.bind((HOTE, PORT))
    serveur.listen()
    print("Serveur demarre sur le port " + str(PORT) + " (Ctrl+C pour arreter)")

    while True:
        # on attend qu'un client se connecte
        sock, adresse = serveur.accept()
        # on lance un thread pour ce client (comme ca on peut en gerer plusieurs)
        t = threading.Thread(target=gerer_client, args=(sock, adresse))
        t.daemon = True
        t.start()


if __name__ == "__main__":
    try:
        demarrer()
    except KeyboardInterrupt:
        print("\nArret du serveur.")
