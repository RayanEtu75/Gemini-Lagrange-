openssl genrsa -out key.pem 2048

openssl req -new -x509 -key key.pem -out cert.pem -days 365 -config "Chemin vers le fichier openssl.cnf"

