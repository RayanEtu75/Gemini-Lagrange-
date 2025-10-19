import os

# Réseau
HOST = ""        # écoute v4+v6 si possible (AF_INET6 + dual-stack)
PORT = 1965

# Dossiers
BASE_DIR  = "capsule"
CERT_DIR  = "certs"
DATA_DIR  = "data"
GAMES_DIR = os.path.join(DATA_DIR, "games")

# TLS
SERV_CERT = os.path.join(CERT_DIR, "server.pem")
SERV_KEY  = os.path.join(CERT_DIR, "server.key")

# TOFU
TRUST_FILE = os.path.join(DATA_DIR, "trusted_clients.txt")

# I/O
READ_BYTES = 2048
TIMEOUT_S  = 5
