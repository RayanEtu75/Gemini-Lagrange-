#!/usr/bin/env python3
# Gemini TLS server (PyOpenSSL) — Morpion 2 joueurs via certificats clients (TOFU)
# Python 3.8+

import os, socket, time, hashlib, html, json, uuid
from OpenSSL import SSL, crypto

HOST = ""                 # écoute v4+v6 si possible (via AF_INET6 ci-dessous)
PORT = 1965
BASE_DIR = "capsule"
CERT_DIR = "certs"
DATA_DIR = "data"
GAMES_DIR = os.path.join(DATA_DIR, "games")
SERV_CERT = os.path.join(CERT_DIR, "server.pem")
SERV_KEY  = os.path.join(CERT_DIR, "server.key")
TRUST_FILE = os.path.join(DATA_DIR, "trusted_clients.txt")

READ_BYTES = 2048
TIMEOUT_S = 5

# ---------- Utils & Boot ----------

def ensure_dirs():
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(CERT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(GAMES_DIR, exist_ok=True)
    idx = os.path.join(BASE_DIR, "index.gmi")
    if not os.path.exists(idx):
        with open(idx, "w", encoding="utf-8") as f:
            f.write("# Accueil Gemini (TOFU)\n\n"
                    "Première visite : votre identité sera enregistrée automatiquement.\n\n"
                    "=> /ttt Morpion (2 joueurs)\n")

def require_server_cert():
    if not (os.path.exists(SERV_CERT) and os.path.exists(SERV_KEY)):
        raise SystemExit("❌ Cert serveur manquant.\n"
                         "Génère-le :\n"
                         "openssl req -x509 -newkey rsa:2048 -nodes -days 365 "
                         "-keyout certs/server.key -out certs/server.pem -subj '/CN=localhost'")

def ssl_context() -> SSL.Context:
    ctx = SSL.Context(SSL.TLS_SERVER_METHOD)
    ctx.set_options(SSL.OP_NO_COMPRESSION)
    ctx.use_certificate_file(SERV_CERT)
    ctx.use_privatekey_file(SERV_KEY)
    def verify_cb(conn, cert, errnum, depth, ok):
        return True
    ctx.set_verify(SSL.VERIFY_PEER, verify_cb)
    return ctx

def recv_line(ssl_conn: SSL.Connection) -> str:
    ssl_conn.settimeout(TIMEOUT_S)
    data = b""
    while b"\n" not in data and len(data) < 4096:
        chunk = ssl_conn.recv(READ_BYTES)
        if not chunk:
            break
        data += chunk
    return data.decode("utf-8", "replace").strip()

def gem_send(ssl_conn: SSL.Connection, code: int, meta: str, body: str = ""):
    header = f"{code} {meta}\r\n".encode("utf-8")
    payload = body.encode("utf-8") if isinstance(body, str) else body
    ssl_conn.sendall(header + payload)

def sanitize_path(req: str) -> str:
    # req: "gemini://host[:port]/path?..." ou juste "/"
    path = req
    if path.startswith("gemini://"):
        parts = path.split("/", 3)
        path = parts[3] if len(parts) >= 4 else ""
    # on ignore ?... et #...
    path = path.split("?", 1)[0].split("#", 1)[0]
    path = path.lstrip("/") or "index.gmi"
    # pas de normpath ici pour /ttt/... (routes dynamiques), on protège seulement ../
    if path.startswith(".."):
        path = "index.gmi"
    return path

def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def record_fingerprint(fp: str):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    seen = set()
    if os.path.exists(TRUST_FILE):
        with open(TRUST_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line=line.strip()
                if not line or line.startswith("#"): continue
                seen.add(line.split()[0].lower())
    if fp not in seen:
        with open(TRUST_FILE, "a", encoding="utf-8") as f:
            f.write(f"{fp} {ts}\n")

# ---------- Morpion logic ----------

def game_path(gid: str) -> str:
    return os.path.join(GAMES_DIR, f"{gid}.json")

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

def render_board(board):
    # Représentation simple 3x3 pour Gemtext
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
    other = "O" if you == "X" else ("X" if you == "O" else "?")

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
    # Lister quelques parties récentes (facultatif : on affiche celles présentes)
    items = []
    try:
        files = [f for f in os.listdir(GAMES_DIR) if f.endswith(".json")]
        files.sort(key=lambda x: os.path.getmtime(os.path.join(GAMES_DIR, x)), reverse=True)
        for f in files[:20]:
            with open(os.path.join(GAMES_DIR, f), "r", encoding="utf-8") as fh:
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

# ---------- Routing ----------

def handle_ttt(ssl_conn: SSL.Connection, fp: str, path: str, hostport: str):
    # path sans leading "/" ; ex: "ttt", "ttt/new", "ttt/abcd1234", "ttt/abcd1234/move/5"
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
        # On réaffiche la partie après tentative de coup
        game = load_game(gid)
        body = render_game(game, fp, hostport) + "\n\n" + f"> {html.escape(msg)}"
        gem_send(ssl_conn, 20, "text/gemini; charset=utf-8", body)
        return

    # Route inconnue dans /ttt
    gem_send(ssl_conn, 51, "Not found", "Route Morpion inconnue.")

# ---------- Main request handler ----------

def handle(ssl_conn: SSL.Connection, addr):
    try:
        ssl_conn.set_accept_state()
        ssl_conn.do_handshake()

        req = recv_line(ssl_conn)
        if not req:
            gem_send(ssl_conn, 59, "Bad request")
            return
        print(f"[REQ] {req} from {addr}")

        peer_cert = ssl_conn.get_peer_certificate()
        if peer_cert is None:
            gem_send(ssl_conn, 60, "Client certificate required")
            return

        der = crypto.dump_certificate(crypto.FILETYPE_ASN1, peer_cert)
        fp = sha256_hex(der)
        record_fingerprint(fp)
        print(f"[CERT] {fp}")

        path = sanitize_path(req)

        # Host: pour construire des URLs complètes si besoin
        # Sur Gemini, l'URL complète nous est fournie, mais on reconstruit host:port au besoin
        hostport = f"localhost:{PORT}"

        # Routes Morpion
        if path == "ttt" or path.startswith("ttt/"):
            handle_ttt(ssl_conn, fp, path, hostport)
            return

        # Fichiers statiques gemtext dans ./capsule
        fpath = os.path.join(BASE_DIR, path)
        if os.path.isfile(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            prefix = (
                "# ✅ Certificat client accepté\n\n"
                f"Empreinte SHA-256 : {html.escape(fp)}\n\n"
            )
            gem_send(ssl_conn, 20, "text/gemini; charset=utf-8", prefix + content)
        else:
            gem_send(ssl_conn, 51, "Not found", "Page not found.")
    except SSL.Error as e:
        print("[SSL ERROR]", e)
    except Exception as e:
        print("[ERROR]", e)
        try:
            gem_send(ssl_conn, 50, "Server failure")
        except Exception:
            pass
    finally:
        try:
            ssl_conn.shutdown()
        except Exception:
            pass
        try:
            ssl_conn.close()
        except Exception:
            pass

def main():
    ensure_dirs()
    require_server_cert()
    ctx = ssl_context()

    base = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        base.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    except Exception:
        pass
    base.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    base.bind((HOST, PORT))
    base.listen(16)

    print(f"🚀 Gemini TOFU + Morpion sur gemini://localhost:{PORT}")
    print(f"📄 Capsule: ./{BASE_DIR}   🗂️ Registre: ./{TRUST_FILE}   🎮 Parties: ./{GAMES_DIR}")

    while True:
        client, addr = base.accept()
        try:
            ssl_conn = SSL.Connection(ctx, client)
            handle(ssl_conn, addr)
        except Exception as e:
            print("[ACCEPT ERROR]", e)
        finally:
            try:
                client.close()
            except Exception:
                pass

if __name__ == "__main__":
    main()
