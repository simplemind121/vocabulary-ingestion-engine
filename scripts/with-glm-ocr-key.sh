#!/usr/bin/env sh
# Run a command with the GLM-OCR key from the macOS Keychain as VIE_GLM_OCR_API_KEY.
# The key is not printed and not written to any file.
set -eu
VIE_GLM_OCR_API_KEY=$(security find-generic-password -s zai-glm-ocr -w 2>/dev/null) || {
  echo "钥匙串里没有 GLM-OCR 密钥：先运行 scripts/set-glm-ocr-key.sh" >&2; exit 2; }
export VIE_GLM_OCR_API_KEY
exec "$@"
