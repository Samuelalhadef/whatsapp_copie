# WhatsApp Clone 💬

Une copie **pixel-perfect** de WhatsApp Web, avec un vrai serveur de chat
**WebSocket en Python** : rooms, rôles, commandes, messages privés, persistance
et sécurité.

## ✨ Fonctionnalités

| Catégorie | Détails |
|-----------|---------|
| **Messagerie** | Plusieurs clients connectés échangent en temps réel ; déconnexion propre (ne fait pas planter les autres) |
| **Pseudo** | Choix du pseudo, **changement** (`/nick`), **persistance dans `data/users.json`** |
| **Messages privés** | `/msg <pseudo> <texte>` (`/w`, `/mp`) |
| **Salons / rooms** | `/create`, `/join`, `/leave`, `/rooms` — messages isolés par salon |
| **Rôles** | `user` · `moderator` · `admin` (le 1ᵉʳ inscrit devient admin) |
| **Modération** | `/kick`, `/mute`, `/unmute` (modo+) · `/ban`, `/unban`, `/setmodo`, `/remmodo`, `/setadmin`, `/remadmin` (admin) |
| **Commandes utiles** | `/time`, `/ping` (latence), `/clear`, `/who`, `/help`, `/auth <jeton>` |
| **Timeout** | Déconnexion automatique après inactivité (10 min par défaut) |
| **Cybersécurité** | Anti-flood, validation des pseudos/entrées, bans par pseudo **et IP**, autorisations par rôle, jeton admin comparé en temps constant (`hmac.compare_digest`), longueur max des messages, échappement HTML côté client |
| **QoL / Bonus** | Interface WhatsApp Web fidèle, couleurs par pseudo, badges de rôle 👑🛡️, horodatage, indicateur « écrit… », messages système colorés, client terminal en couleurs |

## 📦 Installation

```bash
pip install -r requirements.txt
```

## ▶️ Lancement

**1. Serveur** (un terminal) :

```bash
python server.py
```

Il écoute sur le port `5000` et affiche le jeton admin au démarrage.

**2a. Interface web** : ouvre `web/index.html` dans ton navigateur.
Ouvre-le dans **plusieurs onglets** avec des pseudos différents pour discuter.

**2b. (Bonus) Client terminal** :

```bash
python client.py
```

## 🔐 Rôles & sécurité

- Le **premier utilisateur** enregistré devient **admin** automatiquement.
- Sinon, deviens admin avec `/auth <jeton>` (jeton par défaut `admin123`,
  modifiable via la variable d'environnement `CHAT_ADMIN_TOKEN`).
- Hiérarchie : `admin` > `moderator` > `user`. On ne peut pas sanctionner
  un rôle égal ou supérieur au sien.
- Les bans (pseudo + IP) et les rôles sont **persistés** dans `data/users.json`.

## 🗂️ Fichiers

| Fichier            | Rôle                                                        |
|--------------------|-------------------------------------------------------------|
| `server.py`        | Serveur WebSocket (rooms, rôles, commandes, sécurité)       |
| `client.py`        | Client terminal en couleurs (bonus)                         |
| `web/index.html`   | Structure de l'interface WhatsApp                           |
| `web/style.css`    | Style pixel-perfect                                         |
| `web/app.js`       | Logique client (rooms, rôles, MP, commandes)                |
| `data/users.json`  | Base des utilisateurs / bans (générée au 1ᵉʳ lancement)     |
| `requirements.txt` | Dépendances Python                                          |

## 💡 Commandes (récap)

```
/help                 aide
/nick <pseudo>        changer de pseudo
/msg <pseudo> <txt>   message privé
/who                  membres du salon
/rooms                liste des salons
/create <salon>       créer un salon
/join <salon>         rejoindre un salon
/leave                revenir au salon général
/time                 heure du serveur
/ping                 latence
/clear                effacer l'affichage
/auth <jeton>         devenir admin
— modération —        /kick /mute /unmute
— admin —             /ban /unban /setmodo /remmodo /setadmin /remadmin
```
