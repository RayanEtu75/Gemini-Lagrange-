import os
import shutil
import subprocess
from OpenSSL import SSL
import config

def require_server_cert():
    """
    Vérifie la présence du certificat/clé serveur, sinon les génère automatiquement
    via openssl (auto-signé, 365 jours, CN=localhost).
    """
    have_cert = os.path.exists(config.SERV_CERT)
    have_key  = os.path.exists(config.SERV_KEY)

    if have_cert and have_key:
        return  # déjà présent

    print("⚠️  Certificat serveur manquant ou incomplet. Génération automatique...")
    os.makedirs(config.CERT_DIR, exist_ok=True)

    # Si un seul existe, on supprime pour repartir proprement
    try:
        if have_cert and not have_key:
            os.remove(config.SERV_CERT)
        if have_key and not have_cert:
            os.remove(config.SERV_KEY)
    except Exception:
        pass

    if shutil.which("openssl") is None:
        raise SystemExit(
            "❌ OpenSSL introuvable dans le PATH.\n"
            "Installe-le, ou génère manuellement :\n"
            f"openssl req -x509 -newkey rsa:2048 -nodes -days 365 "
            f"-keyout {config.SERV_KEY} -out {config.SERV_CERT} -subj '/CN=localhost'"
        )

    cmd = [
        "openssl", "req",
        "-x509",
        "-newkey", "rsa:2048",
        "-nodes",
        "-days", "365",
        "-keyout", config.SERV_KEY,
        "-out",   config.SERV_CERT,
        "-subj", "/CN=localhost",
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise SystemExit("❌ Échec de la génération du certificat serveur via OpenSSL.") from e

    if not (os.path.exists(config.SERV_CERT) and os.path.exists(config.SERV_KEY)):
        raise SystemExit("❌ Les fichiers certs générés sont introuvables après exécution.")

    print("✅ Certificat serveur généré avec succès !")

def ssl_context() -> SSL.Context:
    ctx = SSL.Context(SSL.TLS_SERVER_METHOD)
    ctx.set_options(SSL.OP_NO_COMPRESSION)
    ctx.use_certificate_file(config.SERV_CERT)
    ctx.use_privatekey_file(config.SERV_KEY)

    def verify_cb(conn, cert, errnum, depth, ok):
        # On accepte tout (TOFU géré plus haut)
        return True

    ctx.set_verify(SSL.VERIFY_PEER, verify_cb)
    return ctx
