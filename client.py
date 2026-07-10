# Client de chat en sockets (TCP)
# Pour lancer : python client.py  (le serveur doit deja tourner)

import socket
import threading
import os
import sys
import time

HOTE = "127.0.0.1"   # adresse du serveur (mettre l'ip du serveur si autre machine)
PORT = 5000

# pour activer les couleurs dans la console Windows
if os.name == "nt":
    os.system("")

# on retient le moment ou on a fait /ping pour calculer la latence
temps_ping = [0]


def recevoir(sock):
    # thread qui recoit les messages du serveur et les affiche
    tampon = ""
    while True:
        try:
            morceau = sock.recv(1024)
        except:
            break
        if not morceau:
            print("\033[91mDeconnecte du serveur.\033[0m")
            break
        tampon += morceau.decode("utf-8", "ignore")
        while "\n" in tampon:
            ligne, tampon = tampon.split("\n", 1)
            if ligne == "PONG":
                # le serveur a repondu a notre /ping : on calcule le temps
                latence = int((time.time() - temps_ping[0]) * 1000)
                print("\033[93mPing : " + str(latence) + " ms\033[0m")
            elif ligne != "":
                print(ligne)


def main():
    pseudo = input("Choisis ton pseudo : ").strip()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((HOTE, PORT))
    except:
        print("Impossible de se connecter. Le serveur est-il lance ?")
        return

    # on envoie notre pseudo en premier
    sock.send((pseudo + "\n").encode("utf-8"))

    # on lance la reception dans un thread pour afficher en meme temps qu'on ecrit
    t = threading.Thread(target=recevoir, args=(sock,))
    t.daemon = True
    t.start()

    print("Connecte ! Tape /help pour l'aide, /quit pour partir.")

    # boucle principale : on lit ce que l'utilisateur ecrit
    while True:
        try:
            texte = sys.stdin.readline()
        except:
            break
        if not texte:
            break
        texte = texte.strip()
        if texte == "":
            continue

        # /quit : on quitte
        if texte == "/quit":
            break
        # /clear : on efface l'ecran (cote client)
        if texte == "/clear":
            os.system("cls" if os.name == "nt" else "clear")
            continue
        # /ping : on note l'heure avant d'envoyer pour mesurer la latence
        if texte == "/ping":
            temps_ping[0] = time.time()

        # on envoie le message au serveur
        try:
            sock.send((texte + "\n").encode("utf-8"))
        except:
            print("Erreur d'envoi.")
            break

    sock.close()
    print("A bientot !")


if __name__ == "__main__":
    main()
