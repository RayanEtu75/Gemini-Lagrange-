#!/usr/bin/env python3
# Gemini TLS server (PyOpenSSL) — Morpion 2 joueurs via certificats clients (TOFU)

import os
import socket
import html
from OpenSSL import SSL, crypto

import config
from tls import require_server_cert, ssl_context
from utils import ensure_dirs, recv_line, gem_send, sanitize_path, sha256_hex, record_fingerprint
from ttt import handle_ttt

def handle(ssl_conn: SSL.Connection, addr):
    try:
        # 1) Handshake
        ssl_conn.set_accept_state()
        ssl_conn.do_handshake()

        # 2) Requête (1 ligne Gemini)
        req = recv_line(ssl_conn)
        if not req:
            gem_send(ssl_conn, 59, "Bad request")
            return
        print(f"[REQ] {req} from {addr}")

        # 3) Cert client
        peer_cert = ssl_conn.get_peer_certificate()
        if peer_cert is None:
            gem_send(ssl_conn, 60, "Client certificate required")
            return

        der = crypto.dump_certificate(crypto.FILETYPE_ASN1, peer_cert)
        fp = sha256_hex(der)
        record_fingerprint(fp)
        print(f"[CERT] {fp}")

        # 4) Router
        path = sanitize_path(req)
        hostport = f"localhost:{config.PORT}"

        if path == "ttt" or path.startswith("ttt/"):
            handle_ttt(ssl_conn, fp, path, hostport)
            return

        # 5) Fichiers statiques Gemtext
        fpath = os.path.join(config.BASE_DIR, path)
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

    # Socket IPv6 dual-stack 
    base = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        base.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    except Exception:
        pass
    base.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    base.bind((config.HOST, config.PORT))
    base.listen(16)

    print(f"🚀 Gemini TOFU + Morpion sur gemini://localhost:{config.PORT}")
    print(f"📄 Capsule: ./{config.BASE_DIR}   🗂️ Registre: ./{config.TRUST_FILE}   🎮 Parties: ./{config.GAMES_DIR}")

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
