import os
import time
import json
import uuid
import html
import config
from utils import gem_send

# ---------- Persistance ----------

def game_path(gid: str) -> str:
    return os.path.join(config.GAMES_DIR, f"{gid}.json")

def new_game(creator_fp: str) -> str:
    gid = uuid.uuid4().hex[:8]
    data = {
        "id": gid,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "players": {"X": creator_fp, "O": None},
        "turn": "X",
        "board": [" "] * 9,  # 0..8
        "status": "playing", # playing | X_won | O_won | draw
        "last_move_ts": None
    }
    save_game(data)
    return gid

def load_game(gid: str):
    f = game_path(gid)
    if not os.path.exists(f):
        return None
    with open(f, "r", encoding="utf-8") as fh:
        return json.load(fh)

def save_game(data: dict):
    f = game_path(data["id"])
    tmp = f + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, f)

# ---------- Règles ----------

def winner(board):
    lines = [
        (0,1,2),(3,4,5),(6,7,8),
        (0,3,6),(1,4,7),(2,5,8),
        (0,4,8),(2,4,6)
    ]
    for a,b,c in lines:
        if board[a] != " " and board[a] == board[b] == board[c]:
            return board[a]  # "X" ou "O"
    if all(s != " " for s in board):
        return "draw"
    return None

def join_if_needed(game, fp: str):
    if game["players"]["O"] is None and fp != game["players"]["X"]:
        game["players"]["O"] = fp
        save_game(game)

def can_play(game, fp: str) -> bool:
    t = game["turn"]
    return (game["status"] == "playing") and (game["players"].get(t) == fp)

def play_move(game, fp: str, cell: int, hostport: str) -> str:
    if game["status"] != "playing":
        return "La partie est déjà terminée."
    if not (0 <= cell <= 8):
        return "Coup invalide."
    if not can_play(game, fp):
        return "Ce n'est pas votre tour."
    if game["board"][cell] != " ":
        return "Case déjà occupée."

    game["board"][cell] = game["turn"]
    game["last_move_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    w = winner(game["board"])
    if w == "X":
        game["status"] = "X_won"
    elif w == "O":
        game["status"] = "O_won"
    elif w == "draw":
        game["status"] = "draw"
    else:
        game["turn"] = "O" if game["turn"] == "X" else "X"
    save_game(game)
    return f"Coup joué. => gemini://{hostport}/ttt/{game['id']}"

# ---------- Rendu Gemtext ----------

def render_board(board):
    def s(i): return board[i] if board[i] != " " else "·"
    rows = [
        f"{s(0)} | {s(1)} | {s(2)}",
        "--+---+--",
        f"{s(3)} | {s(4)} | {s(5)}",
        "--+---+--",
        f"{s(6)} | {s(7)} | {s(8)}",
    ]
    return "\n".join(rows)

def render_game(game, fp: str, hostport: str):
    you = "X" if game["players"]["X"] == fp else ("O" if game["players"]["O"] == fp else "?")

    head = [
        "# Morpion",
        "",
        f"*Partie* : **{game['id']}**",
        f"*Vous êtes* : **{you}**",
        f"*Tour* : **{game['turn']}**",
        f"*Statut* : **{game['status']}**",
        ""
    ]

    if game["players"]["O"] is None:
        head += ["*En attente d'un second joueur...*",
                 "",
                 "Partage ce lien :",
                 f"=> gemini://{hostport}/ttt/{game['id']} Rejoindre la partie",
                 ""]

    body = [
        "## Plateau",
        "```",
        render_board(game["board"]),
        "```",
        ""
    ]

    tail = []

    if game["status"] == "playing":
        if can_play(game, fp):
            tail.append("## À vous de jouer")
            tail.append("Choisissez une case :")
            for i in range(9):
                if game["board"][i] == " ":
                    tail.append(f"=> /ttt/{game['id']}/move/{i} Case {i+1}")
        else:
            tail.append("## En attente")
            tail.append(f"C'est au tour de **{game['turn']}**.")
    else:
        if game["status"] == "X_won":
            tail.append("## 🎉 Victoire de **X** !")
        elif game["status"] == "O_won":
            tail.append("## 🎉 Victoire de **O** !")
        else:
            tail.append("## 🤝 Match nul")
        tail += [
            "",
            "=> /ttt/new Rejouer (nouvelle partie)"
        ]

    tail += [
        "",
        "=> /ttt Retour au menu Morpion",
        "=> /index.gmi Accueil"
    ]

    return "\n".join(head + body + tail)

def render_menu(hostport: str):
    items = []
    try:
        files = [f for f in os.listdir(config.GAMES_DIR) if f.endswith(".json")]
        files.sort(key=lambda x: os.path.getmtime(os.path.join(config.GAMES_DIR, x)), reverse=True)
        for f in files[:20]:
            with open(os.path.join(config.GAMES_DIR, f), "r", encoding="utf-8") as fh:
                g = json.load(fh)
            status = g["status"]
            players = f"X:{g['players']['X'][:6]} O:{(g['players']['O'] or '...')[:6]}"
            items.append(f"=> /ttt/{g['id']} Partie {g['id']} — {status} — {players}")
    except Exception:
        pass

    return "\n".join([
        "# Morpion (2 joueurs)",
        "",
        "Le serveur utilise votre certificat client pour vous identifier.",
        "",
        "=> /ttt/new Nouvelle partie (vous serez X)",
        ""
    ] + (items if items else ["_Aucune partie enregistrée pour le moment._"]) + [
        "",
        "=> /index.gmi Accueil"
    ])

# ---------- Routeur Morpion ----------

def handle_ttt(ssl_conn, fp: str, path: str, hostport: str):
    parts = path.split("/")
    # /ttt
    if len(parts) == 1:
        body = render_menu(hostport)
        gem_send(ssl_conn, 20, "text/gemini; charset=utf-8", body)
        return

    # /ttt/new
    if len(parts) == 2 and parts[1] == "new":
        gid = new_game(fp)
        body = "\n".join([
            "# Nouvelle partie créée",
            "",
            f"ID : **{gid}**",
            "",
            "Partage ce lien avec un ami :",
            f"=> /ttt/{gid} Ouvrir la partie",
            "",
            "=> /ttt Retour"
        ])
        gem_send(ssl_conn, 20, "text/gemini; charset=utf-8", body)
        return

    # /ttt/{id}
    if len(parts) == 2:
        gid = parts[1]
        game = load_game(gid)
        if not game:
            gem_send(ssl_conn, 51, "Not found", "Partie introuvable.")
            return
        join_if_needed(game, fp)
        body = render_game(game, fp, hostport)
        gem_send(ssl_conn, 20, "text/gemini; charset=utf-8", body)
        return

    # /ttt/{id}/move/{cell}
    if len(parts) == 4 and parts[2] == "move":
        gid = parts[1]
        try:
            cell = int(parts[3])
        except ValueError:
            gem_send(ssl_conn, 59, "Bad request", "Case invalide.")
            return
        game = load_game(gid)
        if not game:
            gem_send(ssl_conn, 51, "Not found", "Partie introuvable.")
            return
        join_if_needed(game, fp)
        msg = play_move(game, fp, cell, hostport)
        game = load_game(gid)  # rechargé
        body = render_game(game, fp, hostport) + "\n\n" + f"> {html.escape(msg)}"
        gem_send(ssl_conn, 20, "text/gemini; charset=utf-8", body)
        return

    gem_send(ssl_conn, 51, "Not found", "Route Morpion inconnue.")
