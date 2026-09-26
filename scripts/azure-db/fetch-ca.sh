#!/usr/bin/env bash
# Azure Database for MySQL Flexible Server 接続用の CA 証明書を取得し、
# 1 つの PEM ファイルに束ねる。
#
# 取得元（2026-09-25 確認。Microsoft Learn 公式ページ）:
#   - 概要・SSL 接続手順:
#     https://learn.microsoft.com/en-us/azure/mysql/security/security-tls-how-to-connect
#   - 証明書のローテーション（移行期間中に必要な3証明書の案内）:
#     https://learn.microsoft.com/en-us/azure/mysql/security/security-tls-root-certificate-rotation
#
# 上記ページによれば、現行の DigiCert Global Root CA（SHA-1・旧）は
# DigiCert Global Root G2 と Microsoft RSA Root Certificate Authority 2017 の
# 2 証明書に置き換わる移行期間中であり、確実に接続するには次の 3 証明書を
# 束ねたファイルを使うことが案内されている（"Other clients"＝Python 等の節）。
#   1. DigiCert Global Root CA   https://cacerts.digicert.com/DigiCertGlobalRootCA.crt.pem
#   2. DigiCert Global Root G2   https://cacerts.digicert.com/DigiCertGlobalRootG2.crt.pem
#   3. Microsoft RSA Root Certificate Authority 2017（DER 形式のため PEM に変換する）
#      https://www.microsoft.com/pkiops/certs/Microsoft%20RSA%20Root%20Certificate%20Authority%202017.crt
#
# 証明書は公開されている公的認証局の証明書であり秘密情報ではないが、
# リポジトリには置かず、既定でリポジトリ外（~/.config/guapp/）に保存する。
#
# 使い方:
#   scripts/azure-db/fetch-ca.sh
#   GUAPP_CA_DIR=/path/to/dir scripts/azure-db/fetch-ca.sh   # 保存先を変える場合

set -euo pipefail

OUT_DIR="${GUAPP_CA_DIR:-$HOME/.config/guapp}"
OUT_FILE="$OUT_DIR/azure-mysql-ca.pem"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"

echo "[fetch-ca] CA 証明書を取得します..."
curl -fsSL -o "$TMP_DIR/DigiCertGlobalRootCA.crt.pem" \
  "https://cacerts.digicert.com/DigiCertGlobalRootCA.crt.pem"
curl -fsSL -o "$TMP_DIR/DigiCertGlobalRootG2.crt.pem" \
  "https://cacerts.digicert.com/DigiCertGlobalRootG2.crt.pem"
curl -fsSL -o "$TMP_DIR/MicrosoftRSARootCertificateAuthority2017.crt" \
  "https://www.microsoft.com/pkiops/certs/Microsoft%20RSA%20Root%20Certificate%20Authority%202017.crt"

echo "[fetch-ca] Microsoft の証明書（DER）を PEM に変換します..."
openssl x509 -inform der \
  -in "$TMP_DIR/MicrosoftRSARootCertificateAuthority2017.crt" \
  -out "$TMP_DIR/MicrosoftRSARootCertificateAuthority2017.crt.pem"

echo "[fetch-ca] 3 証明書を 1 つの PEM に束ねます: $OUT_FILE"
cat \
  "$TMP_DIR/DigiCertGlobalRootCA.crt.pem" \
  "$TMP_DIR/DigiCertGlobalRootG2.crt.pem" \
  "$TMP_DIR/MicrosoftRSARootCertificateAuthority2017.crt.pem" \
  > "$OUT_FILE"
chmod 600 "$OUT_FILE"

echo "[fetch-ca] 完了。束ねた証明書の一覧（Subject/Issuer）:"
openssl crl2pkcs7 -nocrl -certfile "$OUT_FILE" | openssl pkcs7 -print_certs -noout

echo "[fetch-ca] 保存先: $OUT_FILE"
