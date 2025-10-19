import os
import time
import html
import hashlib
from OpenSSL import SSL
import config

def ensure_dirs():
    os.makedirs(config.BASE_DIR, exist_ok=True)
    os.makedirs(config.CERT_DIR, exist_ok=True)
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.GAMES_DIR, exist_ok=True)

    idx = os.path.join(config.BASE_DIR, "index.gmi")
    if not os.path.exists(idx):
        with open(idx, "w", encoding="utf-8") as f:
            f.write("# Accueil Gemini (TOFU)\n\n"
                    "Première visite : votre identité sera enregistrée automatiquement.\n\n"
                    "=> /ttt Morpion (2 joueurs)\n")

def recv_line(ssl_conn: SSL.Connection) -> str:
    ssl_conn.settimeout(config.TIMEOUT_S)
    data = b""
    while b"\n" not in data and len(data) < 4096:
        chunk = ssl_conn.recv(config.READ_BYTES)
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
    # pas de normpath (routes dynamiques), on protège seulement ../
    if path.startswith(".."):
        path = "index.gmi"
    return path

def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def record_fingerprint(fp: str):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    seen = set()
    if os.path.exists(config.TRUST_FILE):
        with open(config.TRUST_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line=line.strip()
                if not line or line.startswith("#"): continue
                seen.add(line.split()[0].lower())
    if fp not in seen:
        with open(config.TRUST_FILE, "a", encoding="utf-8") as f:
            f.write(f"{fp} {ts}\n")
