import socket
import ssl
from urllib.parse import urlparse, parse_qs
import random

CERT_FILE = 'cert.pem'
KEY_FILE = 'key.pem'
HOST = 'localhost'
#HOST = '0.0.0.0'
PORT = 1965

def build_response(body: str):
    return f"20 text/gemini\r\n{body}"

def check_winner(board):
    wins = [(0,1,2), (3,4,5), (6,7,8),  # lignes
            (0,3,6), (1,4,7), (2,5,8),  # colonnes
            (0,4,8), (2,4,6)]           # diagonales
    for a, b, c in wins:
        if board[a] == board[b] == board[c] and board[a] != '_':
            return board[a]
    if '_' not in board:
        return 'draw'
    return None

def bot_move(board):
    empty = [i for i, c in enumerate(board) if c == '_']
    if not empty:
        return board
    choice = random.choice(empty)
    board = board[:choice] + 'O' + board[choice+1:]
    return board

def render_board(board):
    def symbol(i):
        return board[i] if board[i] != '_' else str(i + 1)

    lines = []
    for i in range(0, 9, 3):
        row = f"{symbol(i)} | {symbol(i+1)} | {symbol(i+2)}"
        lines.append(row)
    return '\n'.join(lines)

def render_links(board):
    links = ""
    for i, c in enumerate(board):
        if c == '_':
            new_board = board[:i] + 'X' + board[i+1:]
            new_board = bot_move(new_board)
            links += f"=> /morpion?board={new_board} Jouer dans la case {i + 1}\n"
    return links

def handle_request(connstream):
    request = connstream.recv(1024).decode('utf-8').strip()
    print("Requête Gemini reçue :", request)

    parsed = urlparse(request)
    path = parsed.path
    query = parse_qs(parsed.query)

    if path in ["/", "gemini://localhost/", "gemini://localhost"]:
        response = build_response("""# Bienvenue sur le serveur Gemini 🎮

=> /morpion Lancer une partie de morpion
""")

    elif path == "/morpion":
        board = query.get("board", ["_" * 9])[0]
        winner = check_winner(board)

        body = "# Morpion (Tic-Tac-Toe)\n\n"
        body += "Tu joues avec : X\n\n"
        body += "Plateau actuel :\n\n"
        body += f"```\n{render_board(board)}\n```\n\n"

        if winner == 'X':
            body += "🎉 Tu as gagné !\n\n"
            body += "=> /morpion Rejouer\n"
        elif winner == 'O':
            body += "🤖 L’ordinateur a gagné !\n\n"
            body += "=> /morpion Rejouer\n"
        elif winner == 'draw':
            body += "⚖️ Match nul !\n\n"
            body += "=> /morpion Rejouer\n"
        else:
            body += "À toi de jouer :\n\n"
            body += render_links(board)

        response = build_response(body)

    else:
        response = "51 Not found\r\n"

    connstream.send(response.encode('utf-8'))

def run_server():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)

    with socket.create_server((HOST, PORT)) as server:
        with context.wrap_socket(server, server_side=True) as tls_server:
            print(f"Gemini server running on gemini://{HOST}:{PORT}")
            while True:
                conn, addr = tls_server.accept()
                with conn:
                    handle_request(conn)

if __name__ == '__main__':
    run_server()
