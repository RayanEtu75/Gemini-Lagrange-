import socket
import ssl
from urllib.parse import urlparse, parse_qs, unquote
import hashlib
import random
import threading
import os

# Fichiers de certificats
CERT_FILE = 'server.crt'
KEY_FILE = 'server.key'
CA_FILE = 'ca.crt'
HOST = '0.0.0.0'
PORT = 1965

# Vérifie que les certificats existent
print(f"📁 Répertoire: {os.getcwd()}")
for f in [CERT_FILE, KEY_FILE, CA_FILE]:
    if os.path.exists(f):
        print(f"✓ {f}")
    else:
        print(f"✗ {f} MANQUANT!")
        exit(1)

print("\n✅ Tous les certificats sont présents!\n")

# Stockage des parties en cours
games = {}
player_names = {}
player_sessions = {}

def get_cert_fingerprint(cert_der):
    if not cert_der:
        return None
    return hashlib.sha256(cert_der).hexdigest()[:16]

def build_response(status_code: str, body: str = ""):
    return f"{status_code}\r\n{body}"

def check_winner(board):
    wins = [(0,1,2), (3,4,5), (6,7,8),
            (0,3,6), (1,4,7), (2,5,8),
            (0,4,8), (2,4,6)]
    for a, b, c in wins:
        if board[a] == board[b] == board[c] and board[a] != '_':
            return board[a]
    if '_' not in board:
        return 'draw'
    return None

def render_board(board):
    def symbol(i):
        return board[i] if board[i] != '_' else str(i + 1)
    lines = []
    for i in range(0, 9, 3):
        row = f"{symbol(i)} | {symbol(i+1)} | {symbol(i+2)}"
        lines.append(row)
    return '\n'.join(lines)

def render_links(board, game_id, player_id):
    game = games[game_id]
    my_symbol = 'X' if game['x_player'] == player_id else 'O'
    
    links = ""
    for i, c in enumerate(board):
        if c == '_':
            new_board = board[:i] + my_symbol + board[i+1:]
            links += f"=> /play?game={game_id}&board={new_board} Jouer dans la case {i + 1}\n"
    return links

def handle_request(connstream):
    try:
        request = connstream.recv(1024).decode('utf-8').strip()
        print("📨 Requête:", request)
        
        cert_der = None
        cert_fingerprint = None
        try:
            cert_der = connstream.getpeercert(binary_form=True)
            cert_fingerprint = get_cert_fingerprint(cert_der)
            print(f"🔑 Certificat: {cert_fingerprint}")
        except:
            print("⚠️  Pas de certificat")
        
        parsed = urlparse(request)
        path = parsed.path
        query = parse_qs(parsed.query)
        
        if path in ["/", "gemini://localhost/", "gemini://localhost"]:
            if cert_fingerprint and cert_fingerprint in player_sessions:
                player_name = player_names.get(cert_fingerprint, 'Inconnu')
                response = build_response("20 text/gemini", f"""# Bienvenue 🎮

Connecté : {player_name}

=> /menu Menu
""")
            else:
                response = build_response("20 text/gemini", """# Bienvenue 🎮

=> /register S'enregistrer
""")
        
        elif path == "/register":
            if not cert_fingerprint:
                response = build_response("20 text/gemini", """❌ Certificat requis

=> / Retour
""")
            elif cert_fingerprint in player_sessions:
                response = build_response("20 text/gemini", f"""# Déjà enregistré

Nom : {player_names[cert_fingerprint]}

=> /menu Menu
""")
            else:
                if parsed.query:
                    player_name = unquote(request.split('?')[1]).strip()
                    if player_name:
                        player_sessions[cert_fingerprint] = cert_fingerprint
                        player_names[cert_fingerprint] = player_name
                        response = build_response("20 text/gemini", f"""# Bienvenue {player_name} ! 👋

=> /menu Menu
""")
                    else:
                        response = build_response("20 text/gemini", "❌ Nom invalide")
                else:
                    response = build_response("10 Entre ton nom")
        
        elif path == "/menu":
            if not cert_fingerprint or cert_fingerprint not in player_sessions:
                response = build_response("20 text/gemini", "❌ Non authentifié\n\n=> /register S'enregistrer")
            else:
                player_id = cert_fingerprint
                player_name = player_names[cert_fingerprint]
                current_game = None
                for gid, game in games.items():
                    if game['x_player'] == player_id or game['o_player'] == player_id:
                        current_game = gid
                        break
                
                body = f"# Menu - {player_name}\n\n"
                if current_game:
                    body += "=> /mygame 🎮 Ma partie\n"
                else:
                    body += "=> /new ➕ Créer une partie\n=> /join 🔗 Rejoindre\n"
                
                response = build_response("20 text/gemini", body)
        
        elif path == "/new":
            if not cert_fingerprint or cert_fingerprint not in player_sessions:
                response = build_response("20 text/gemini", "❌ Non authentifié")
            else:
                player_id = cert_fingerprint
                game_id = ''.join(random.choices('0123456789ABCDEF', k=6))
                games[game_id] = {'board': '_' * 9, 'x_player': player_id, 'o_player': None, 'turn': 'X'}
                response = build_response("20 text/gemini", f"""# Partie créée ! 🎮

ID : {game_id}
Symbole : X

=> /mygame Voir
""")
        
        elif path == "/join":
            if not cert_fingerprint or cert_fingerprint not in player_sessions:
                response = build_response("20 text/gemini", "❌ Non authentifié")
            else:
                player_id = cert_fingerprint
                available_game = None
                for gid, game in games.items():
                    if game['o_player'] is None and game['x_player'] != player_id:
                        available_game = gid
                        break
                
                if available_game:
                    games[available_game]['o_player'] = player_id
                    response = build_response("20 text/gemini", "# Partie rejointe ! 🎮\n\nSymbole : O\n\n=> /mygame Voir")
                else:
                    response = build_response("20 text/gemini", "# Aucune partie\n\n=> /menu Menu")
        
        elif path == "/mygame":
            if not cert_fingerprint or cert_fingerprint not in player_sessions:
                response = build_response("20 text/gemini", "❌ Non authentifié")
            else:
                player_id = cert_fingerprint
                current_game = None
                for gid, game in games.items():
                    if game['x_player'] == player_id or game['o_player'] == player_id:
                        current_game = gid
                        break
                
                if not current_game:
                    response = build_response("20 text/gemini", "# Aucune partie\n\n=> /menu Menu")
                else:
                    game = games[current_game]
                    board = game['board']
                    my_symbol = 'X' if game['x_player'] == player_id else 'O'
                    opponent_symbol = 'O' if my_symbol == 'X' else 'X'
                    winner = check_winner(board)
                    
                    body = f"# Morpion\n\n{player_names[cert_fingerprint]} ({my_symbol})\nID : {current_game}\n\n```\n{render_board(board)}\n```\n\n"
                    
                    if winner == my_symbol:
                        body += "🎉 Victoire !\n\n=> /menu Menu\n"
                        del games[current_game]
                    elif winner == opponent_symbol:
                        body += "😢 Défaite\n\n=> /menu Menu\n"
                        del games[current_game]
                    elif winner == 'draw':
                        body += "⚖️ Match nul\n\n=> /menu Menu\n"
                        del games[current_game]
                    else:
                        if game['o_player'] is None:
                            body += "⏳ En attente...\n\n=> /mygame Rafraîchir\n"
                        elif game['turn'] == my_symbol:
                            body += "✅ Ton tour !\n\n" + render_links(board, current_game, player_id)
                        else:
                            body += "⏳ Adversaire...\n\n=> /mygame Rafraîchir\n"
                    
                    response = build_response("20 text/gemini", body)
        
        elif path == "/play":
            if not cert_fingerprint or cert_fingerprint not in player_sessions:
                response = build_response("20 text/gemini", "❌ Non authentifié")
            else:
                player_id = cert_fingerprint
                game_id = query.get("game", [None])[0]
                new_board = query.get("board", [None])[0]
                
                if game_id and new_board and game_id in games:
                    game = games[game_id]
                    my_symbol = 'X' if game['x_player'] == player_id else 'O'
                    if game['turn'] == my_symbol:
                        game['board'] = new_board
                        game['turn'] = 'O' if my_symbol == 'X' else 'X'
                    response = build_response("20 text/gemini", "# Coup joué !\n\n=> /mygame Voir")
                else:
                    response = build_response("20 text/gemini", "❌ Erreur")
        
        else:
            response = build_response("51 Not found")
        
        connstream.send(response.encode('utf-8'))
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
    finally:
        connstream.close()

def run_server():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
    context.load_verify_locations(cafile=CA_FILE)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_OPTIONAL
    
    with socket.create_server((HOST, PORT)) as server:
        with context.wrap_socket(server, server_side=True) as tls_server:
            print(f"🚀 Serveur sur gemini://localhost:{PORT}\n")
            while True:
                try:
                    conn, addr = tls_server.accept()
                    thread = threading.Thread(target=handle_request, args=(conn,))
                    thread.daemon = True
                    thread.start()
                except Exception as e:
                    print(f"⚠️  {e}")

if __name__ == '__main__':
    run_server()
