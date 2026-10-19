#!/usr/bin/env sh
# Store the Z.ai GLM-OCR API key in the macOS Keychain without it ever appearing
# in a terminal, a chat or the shell history. The key is typed into a system
# dialog with hidden input, checked against the API (a request without a page,
# which is refused before any work is done and costs nothing), then saved as the
# Keychain item "zai-glm-ocr". Every project reads it from there:
#   security find-generic-password -s zai-glm-ocr -w
# or runs a command with it set as VIE_GLM_OCR_API_KEY:
#   scripts/with-glm-ocr-key.sh <command> ...
set -eu

url=${VIE_GLM_OCR_URL:-https://api.z.ai/api/paas/v4/layout_parsing}

key=$(osascript \
  -e 'set reply to display dialog "粘贴 Z.ai（智谱）GLM-OCR 的 API 密钥（输入内容不会显示）：" default answer "" with hidden answer buttons {"取消", "保存"} default button "保存" with title "设置 GLM-OCR 密钥"' \
  -e 'text returned of reply' 2>/dev/null) || { echo "已取消，未做任何修改。"; exit 1; }
key=$(printf '%s' "$key" | tr -d '[:space:]')
[ -n "$key" ] || { echo "没有输入密钥，未做任何修改。"; exit 1; }

# No file is sent: a valid key gets a request error (400/422), a wrong one 401/403.
status=$(curl -sS -m 30 -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $key" \
  -H "Content-Type: application/json" -d '{"model":"glm-ocr"}' "$url" || echo 000)
case "$status" in
  401|403) echo "智谱没有接受这个密钥（返回 $status），未做任何修改。请确认密钥复制完整且未作废。"; exit 1 ;;
  000) echo "连不上智谱的服务，未做任何修改。请检查网络后再试。"; exit 1 ;;
esac

security add-generic-password -U -s zai-glm-ocr -a "$USER" -l "Z.ai GLM-OCR API key" -w "$key"
echo "密钥已保存到钥匙串（项目名 zai-glm-ocr，服务返回 $status，说明密钥被接受）。"
