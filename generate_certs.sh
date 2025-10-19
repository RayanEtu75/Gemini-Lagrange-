#!/bin/bash

echo "Génération de l'infrastructure PKI..."

# 1. Crée la CA (Autorité de Certification)
echo "Création de la CA..."
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 365 -out ca.crt \
    -subj "/C=FR/ST=IDF/L=Paris/O=GeminiCA/CN=Gemini Root CA"

# 2. Crée le certificat serveur
echo "Création du certificat serveur..."
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr \
    -subj "/C=FR/ST=IDF/L=Paris/O=GeminiServer/CN=localhost"

# Signe le certificat serveur avec la CA
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out server.crt -days 365 -sha256

# 3. Crée le certificat client Alice
echo "Création du certificat Alice..."
openssl genrsa -out alice.key 2048
openssl req -new -key alice.key -out alice.csr \
    -subj "/C=FR/ST=IDF/L=Paris/O=GeminiClient/CN=Alice"

# Signe le certificat Alice avec la CA
openssl x509 -req -in alice.csr -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out alice.crt -days 365 -sha256

# 4. Crée le certificat client Bob
echo "Création du certificat Bob..."
openssl genrsa -out bob.key 2048
openssl req -new -key bob.key -out bob.csr \
    -subj "/C=FR/ST=IDF/L=Paris/O=GeminiClient/CN=Bob"

# Signe le certificat Bob avec la CA
openssl x509 -req -in bob.csr -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out bob.crt -days 365 -sha256

# 5. Crée des fichiers .p12 pour Lagrange (optionnel, plus facile à importer)
echo "Création des fichiers PKCS#12..."
openssl pkcs12 -export -out alice.p12 -inkey alice.key -in alice.crt -passout pass:
openssl pkcs12 -export -out bob.p12 -inkey bob.key -in bob.crt -passout pass:

# 6. Nettoie les fichiers temporaires
rm -f *.csr *.srl

echo "✅ Certificats générés avec succès !"
echo ""
echo "Fichiers créés :"
echo "  - ca.crt (à importer comme certificat de confiance dans Lagrange)"
echo "  - server.crt + server.key (pour le serveur Python)"
echo "  - alice.crt + alice.key (identité Alice)"
echo "  - bob.crt + bob.key (identité Bob)"
echo "  - alice.p12 + bob.p12 (pour import facile dans Lagrange)"
