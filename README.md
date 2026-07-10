# Chat en sockets (Python)

Un chat en ligne dans le terminal, fait avec les **sockets** TCP de Python.
Projet du cours "Sockets en python".

Il y a un serveur (`server.py`) et un client (`client.py`). Plusieurs personnes
peuvent se connecter en meme temps et discuter.

## Lancer le projet

Aucune installation : on utilise seulement la bibliotheque standard de Python.

1. Lancer le serveur dans un terminal :

```bash
python server.py
```

2. Lancer un ou plusieurs clients (dans d'autres terminaux) :

```bash
python client.py
```

Choisis un pseudo et discute ! Le **premier** qui se connecte devient **admin**.

## Les fonctionnalites

- Plusieurs clients connectes en meme temps qui echangent des messages
- Un client peut partir sans faire planter les autres
- Choix du pseudo, stocke dans un fichier `users.json`
- Changer de pseudo : `/nick <pseudo>`
- Message prive : `/msg <pseudo> <message>`
- `/time` : l'heure du serveur
- `/ping` : la latence
- Deconnexion automatique apres 5 minutes sans rien ecrire (timeout)
- `/clear` : effacer l'ecran
- Roles : **user**, **moderator**, **admin**
- Commandes de roles :
  - moderateur : `/kick`, `/mute`, `/unmute`
  - admin : `/ban`, `/unban`, `/setmodo`, `/remmodo`, `/setadmin`, `/remadmin`
- Salons : `/create <salon>`, `/join <salon>`, `/leave`, `/rooms`
- Securite : pseudos verifies, bans par pseudo et par IP, on ne peut pas
  sanctionner un role egal ou superieur, messages trop longs coupes
- Bonus : couleurs dans la console, heure devant chaque message

## Toutes les commandes

```
/help                aide
/nick <pseudo>       changer de pseudo
/msg <pseudo> <txt>  message prive
/time                heure du serveur
/ping                latence
/clear               effacer l'ecran
/who                 qui est dans le salon
/rooms               liste des salons
/create <salon>      creer un salon
/join <salon>        rejoindre un salon
/leave               revenir au salon general
/quit                quitter le chat
--- moderateur ---   /kick /mute /unmute
--- admin ---        /ban /unban /setmodo /remmodo /setadmin /remadmin
```

## Les fichiers

- `server.py` : le serveur (accepte les clients, gere les salons, les roles...)
- `client.py` : le client (se connecte et affiche les messages)
- `users.json` : les pseudos et les bans (cree tout seul au lancement)
