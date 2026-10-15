#!/usr/bin/env sh
# Store the vision model's API key in an env file without it ever appearing in
# a terminal, a chat or the shell history. macOS only: the key is typed into a
# system dialog with hidden input, checked against the API, then written.
set -eu

env_file=${1:-.env.gold-runtime}
[ -f "$env_file" ] || { echo "找不到配置文件: $env_file" >&2; exit 2; }

key=$(osascript \
  -e 'set reply to display dialog "粘贴新的 OpenAI API 密钥（输入内容不会显示）：" default answer "" with hidden answer buttons {"取消", "保存"} default button "保存" with title "设置裁决模型密钥"' \
  -e 'text returned of reply' 2>/dev/null) || { echo "已取消，未做任何修改。"; exit 1; }
key=$(printf '%s' "$key" | tr -d '[:space:]')

case "$key" in
  sk-*) ;;
  *) echo "这不像是 OpenAI 密钥（应以 sk- 开头），未做任何修改。"; exit 1 ;;
esac

base=$(sed -n 's/^VIE_ARBITER_BASE_URL=//p' "$env_file" | tail -n 1)
base=${base:-https://api.openai.com/v1}
status=$(curl -sS -m 30 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $key" "$base/models" || echo 000)
if [ "$status" != "200" ]; then
  echo "OpenAI 没有接受这个密钥（返回 $status），未做任何修改。请确认它是新生成且未作废的密钥。"
  exit 1
fi

tmp=$(mktemp)
grep -v '^VIE_ARBITER_API_KEY=' "$env_file" > "$tmp" || true
printf 'VIE_ARBITER_API_KEY=%s\n' "$key" >> "$tmp"
cat "$tmp" > "$env_file"
rm -f "$tmp"
chmod 600 "$env_file"
echo "密钥有效，已保存。其他配置没有改动。"
