import os, html
from urllib.parse import urlparse, parse_qs
from OpenSSL import SSL, crypto
from server import (
    ssl_context, recv_line, gem_send, sha256_hex, ensure_dirs,
    require_server_cert, record_fingerprint
)

PORT = 1965

waiting_player = None
games = {}  

def render_board(board: str) -> str:
    def symb(i):
        return board[i] if board[i] != "_" else str(i + 1)
    return "\n---+---+---\n".join(
        f"{symb(i)} | {symb(i+1)} | {symb(i+2)}" for i in range(0, 9, 3)
    )

def check_winner(board: str):
    wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
    for a,b,c in wins:
        if board[a] != "_" and board[a] == board[b] == board[c]:
            return board[a]
    if "_" not in board:
        return "draw"
    return None

def render_links(board, fp, game):
    links = ""
    symbol = "X" if game["players"][0] == fp else "O"

    for i, c in enumerate(board):
        if c == "_":
            new_board = board[:i] + symbol + board[i+1:]
            links += f"=> /morpion?board={new_board} Jouer dans la case {i + 1}\n"
    if not links:
        links = "=> /morpion Rejouer Rejouer\n"
    return links

def find_or_create_game(fp):
    global waiting_player

    if waiting_player is None:
        waiting_player = fp
        key = (fp,)
        games[key] = {"board": "_"*9, "players": [fp], "turn": None}
        return key, games[key]
    else:
        other = waiting_player
        waiting_player = None
        key = tuple(sorted([fp, other]))
        games[key] = {"board": "_"*9, "players": [other, fp], "turn": other}
        return key, games[key]

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

        parsed = urlparse(req)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in ["/", "index.gmi"]:
            body = "# 🎮 Morpion multijoueur\n\n"
            body += "=> /morpion Rejoindre une partie\n"
            gem_send(ssl_conn, 20, "text/gemini; charset=utf-8", body)
            return

        if path == "/morpion":
            board_param = query.get("board", [None])[0]

            found = None
            for k, g in games.items():
                if fp in g["players"]:
                    found = (k, g)
                    break

            if not found:
                found = find_or_create_game(fp)

            key, game = found
            board = list(game["board"])
            players = game["players"]

            if len(players) == 1:
                body = "# 🎮 Morpion multijoueur\n\n"
                body += "Tu es le joueur **X**.\n\n"
                body += f"```\n{render_board('_'*9)}\n```\n\n"
                body += "⏳ En attente d’un adversaire..."
                gem_send(ssl_conn, 20, "text/gemini; charset=utf-8", body)
                return

            symbol = "X" if players[0] == fp else "O"

            if game["turn"] is None:
                game["turn"] = players[0]

            if board_param and game["turn"] == fp:
                game["board"] = board_param
                game["turn"] = players[1] if players[0] == fp else players[0]

            winner = check_winner(game["board"])

            body = "# 🎮 Morpion multijoueur\n\n"
            body += f"Tu es le joueur **{symbol}**.\n\n"
            body += f"```\n{render_board(game['board'])}\n```\n\n"

            if winner:
                if winner == "draw":
                    body += "⚖️ Match nul !\n\n=> /morpion Rejouer\n"
                elif winner == symbol:
                    body += "🎉 Tu as gagné !\n\n=> /morpion Rejouer\n"
                else:
                    body += "😢 Ton adversaire a gagné.\n\n=> /morpion Rejouer\n"
            elif game["turn"] == fp:
                body += "👉 À ton tour :\n\n"
                body += render_links(game["board"], fp, game)
            else:
                body += "⏳ En attente du tour de ton adversaire...\n"

            gem_send(ssl_conn, 20, "text/gemini; charset=utf-8", body)
            return

        gem_send(ssl_conn, 51, "Not found", "Page not found.")
        return

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
    import socket
    ensure_dirs()
    require_server_cert()
    ctx = ssl_context()

    base = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        base.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    except Exception:
        pass
    base.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    base.bind(("", PORT))
    base.listen(16)

    print(f"🎮 Morpion Gemini sur gemini://localhost:{PORT}")
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
