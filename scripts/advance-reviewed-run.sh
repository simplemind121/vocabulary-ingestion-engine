#!/usr/bin/env sh
# Re-queue a run each time its Review Queue has been emptied by a human, until
# the run completes. It never resolves a review itself.
set -eu

run_id=${1:?usage: scripts/advance-reviewed-run.sh RUN_ID [BASE_URL]}
base=${2:-http://127.0.0.1:${API_PORT:-8000}}
auth="Authorization: Bearer ${VIE_API_KEY:?set VIE_API_KEY}"
field() { python3 -c "import json,sys; print(json.load(sys.stdin).get('$1'))"; }

while :; do
  status=$(curl -sS --fail -H "$auth" "$base/api/v1/runs/$run_id" | field status)
  case "$status" in
    COMPLETED) echo "run $run_id COMPLETED"; exit 0 ;;
    FAILED|OCR_REQUIRED) echo "run $run_id stopped: $status" >&2; exit 1 ;;
    REVIEW_REQUIRED)
      open=$(curl -sS --fail -H "$auth" "$base/api/v1/runs/$run_id/reviews?status=OPEN" | field count)
      escalated=$(curl -sS --fail -H "$auth" "$base/api/v1/runs/$run_id/reviews?status=ESCALATED" | field count)
      if [ "$open" = "0" ] && [ "$escalated" != "0" ]; then
        echo "run $run_id has $escalated escalated review(s); a human must decide" >&2
        exit 1
      fi
      if [ "$open" = "0" ]; then
        echo "review queue empty; re-queueing $run_id"
        curl -sS --fail -X POST -H "$auth" "$base/api/v1/runs/$run_id/enqueue" >/dev/null
      fi ;;
  esac
  sleep 10
done
