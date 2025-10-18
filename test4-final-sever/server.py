#!/usr/bin/env python3
# Gemini TLS server (PyOpenSSL) — accepte tous les certificats clients (auto-signés inclus)
# et enregistre leur empreinte (TOFU). Python 3.8+

import os, socket, time, hashlib, html
from OpenSSL import SSL, crypto  # <-- crypto importé ici

HOST = ""                 # écoute v4+v6 si possible (via AF_INET6 ci-dessous)
PORT = 1965
BASE_DIR = "capsule"
CERT_DIR = "certs"
DATA_DIR = "data"
SERV_CERT = os.path.join(CERT_DIR, "server.pem")
SERV_KEY  = os.path.join(CERT_DIR, "server.key")
TRUST_FILE = os.path.join(DATA_DIR, "trusted_clients.txt")

READ_BYTES = 2048
TIMEOUT_S = 5

def ensure_dirs():
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(CERT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    idx = os.path.join(BASE_DIR, "index.gmi")
    if not os.path.exists(idx):
        with open(idx, "w", encoding="utf-8") as f:
            f.write("# Accueil Gemini (TOFU)\n\n"
                    "Première visite : votre identité sera enregistrée automatiquement.\n")

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

    # 🔑 Demande un certificat client, mais on accepte tout (auto-signés inclus)
    def verify_cb(conn, cert, errnum, depth, ok):
        # Retourner True => on accepte ce certificat quel que soit son statut
        return True

    ctx.set_verify(SSL.VERIFY_PEER, verify_cb)  # ne PAS mettre VERIFY_FAIL_IF_NO_PEER_CERT
    # ctx.set_verify_depth(3)  # optionnel
    return ctx

def recv_line(ssl_conn: SSL.Connection) -> str:
    ssl_conn.settimeout(TIMEOUT_S)
    data = b""
    # on lit jusqu'au premier \n (les clients envoient souvent \r\n)
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
    path = path.split("?", 1)[0].split("#", 1)[0]
    path = path.lstrip("/") or "index.gmi"
    path = os.path.normpath(path)
    if path.startswith("..") or path == ".":
        path = "index.gmi"
    return path

def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def record_fingerprint(fp: str):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # n’ajoute qu’une fois
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

def handle(ssl_conn: SSL.Connection, addr):
    try:
        # 1) Handshake (important avec PyOpenSSL)
        ssl_conn.set_accept_state()
        ssl_conn.do_handshake()

        # 2) Lire la requête Gemini (une seule ligne)
        req = recv_line(ssl_conn)
        if not req:
            gem_send(ssl_conn, 59, "Bad request")
            return
        print(f"[REQ] {req} from {addr}")

        # 3) Récupérer le certificat client (s’il existe)
        peer_cert = ssl_conn.get_peer_certificate()  # OpenSSL.crypto.X509 ou None
        if peer_cert is None:
            # Pas de cert → demander au niveau protocole
            gem_send(ssl_conn, 60, "Client certificate required")
            return

        # 4) Empreinte SHA-256 du DER
        der = crypto.dump_certificate(crypto.FILETYPE_ASN1, peer_cert)  # <-- crypto utilisé ici
        fp = sha256_hex(der)
        record_fingerprint(fp)
        print(f"[CERT] {fp}")

        # 5) Servir la ressource
        path = sanitize_path(req)
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
        # Ex: ('Unexpected EOF',) ou erreurs de handshake/IO
        print("[SSL ERROR]", e)
        # si le handshake a échoué, on ne peut pas envoyer d’en-tête
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

    # Socket IPv6 dual-stack (couvre IPv4 aussi si kernel le permet)
    base = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        base.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    except Exception:
        pass
    base.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    base.bind((HOST, PORT))
    base.listen(16)

    print(f"🚀 Gemini TOFU auto-accept sur gemini://localhost:{PORT}")
    print(f"📄 Capsule: ./{BASE_DIR}   🗂️ Registre: ./{TRUST_FILE}")

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
