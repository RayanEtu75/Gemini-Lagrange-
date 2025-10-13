import socket, ssl, os

HOST = "0.0.0.0"
PORT = 1965
BASE_DIR = "capsule"

# Charger le certificat et la clé
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")

# Création du socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.bind((HOST, PORT))
sock.listen(5)

print(f"Serveur Gemini lancé sur gemini://localhost:{PORT}")

while True:
    client, addr = sock.accept()
    try:
        with context.wrap_socket(client, server_side=True) as conn:
            request = conn.recv(1024).decode("utf-8").strip()
            if not request:
                continue
            print(f"Requête : {request}")

            path = request.replace("gemini://localhost", "").lstrip("/")
            if path == "":
                path = "index.gmi"

            file_path = os.path.join(BASE_DIR, path)
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                header = "20 text/gemini\r\n"
                conn.sendall(header.encode("utf-8") + content.encode("utf-8"))
            else:
                header = "51 Not found\r\n"
                conn.sendall(header.encode("utf-8") + b"Page not found.")
    except Exception as e:
        print("Erreur :", e)
