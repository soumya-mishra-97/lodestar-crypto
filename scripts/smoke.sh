#!/usr/bin/env bash
# Acceptance smoke test against a running stack (default: `make up` on http://localhost:8080).
#   1. the dashboard is populated (seeded watchlist, holdings, a report)
#   2. Polygon (POL) has a verified report
#   3. adding a coin starts a pipeline run that ends with a verified report awaiting approval
#   4. the live event stream and both exports work
#   5. trader skills: the scanner ranks a shortlist, selecting a coin produces a verified trade-plan card,
#      the backtest is saved, and an approved plan becomes a paper position (paper only, no orders)
set -euo pipefail
BASE="${BASE_URL:-http://localhost:8080}/api/v1"
COIN="${SMOKE_COIN:-cardano}"
json() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

echo "waiting for the API at $BASE ..."
for _ in $(seq 1 90); do
  if [[ "$(curl -sf "$BASE/overview" | json "len(d['watchlist'])" 2>/dev/null || echo 0)" -gt 0 ]]; then break; fi
  sleep 2
done
overview=$(curl -sf "$BASE/overview") || fail "overview unreachable"
echo "$overview" | json "d['portfolio']['total_value_usd'] > 0 and d['latest_report'] is not None" | grep -q True || fail "dashboard not populated"
echo "ok  dashboard populated: $(echo "$overview" | json "len(d['watchlist'])") watched coins, portfolio \$$(echo "$overview" | json "round(d['portfolio']['total_value_usd'])")"

pol=$(curl -sf "$BASE/assets" | json "[a['id'] for a in d if a['symbol']=='POL'][0]") || fail "POL not tracked"
curl -sf "$BASE/assets/$pol/report" | json "d['content']['verification']['passed']" | grep -q True || fail "POL has no verified report"
echo "ok  POL report verified"

run=$(curl -sf -X POST "$BASE/assets" -H 'content-type: application/json' -d "{\"coingecko_id\":\"$COIN\"}" | json "d['run']['id']") || fail "could not add $COIN"
echo "ok  added $COIN, run $run"
events=$(curl -sN --max-time 120 "$BASE/runs/$run/events" | grep -c '^data: {"run_id' || true)
status=$(curl -sf "$BASE/runs/$run" | json "d['status']")
if [[ "$status" == "queued" || "$status" == "running" ]]; then fail "run still $status after stream ended"; fi
[[ "$status" == "awaiting_approval" || "$status" == "approved" ]] || fail "run ended $status"
echo "ok  run streamed $events events and ended: $status"

report=$(curl -sf "$BASE/runs/$run" | json "d['report_id']")
curl -sf "$BASE/reports/$report/export.md" | grep -q "Disclaimer" || fail "markdown export"
curl -sf "$BASE/reports/$report/export.pdf" | head -c 4 | grep -q "%PDF" || fail "pdf export"
echo "ok  exports (Markdown, PDF)"

scan=$(curl -sf -X POST "$BASE/scans" -H 'content-type: application/json' -d '{"universe":"top","top_n":10}' | json "d['id']") || fail "scan request"
for _ in $(seq 1 60); do
  [[ "$(curl -sf "$BASE/scans/$scan" | json "d['status']")" != "running" ]] && break
  sleep 2
done
scan_json=$(curl -sf "$BASE/scans/$scan")
[[ "$(echo "$scan_json" | json "d['status']")" == "completed" ]] || fail "scan did not complete"
pick=$(echo "$scan_json" | json "[r['coingecko_id'] for r in d['results'] if r['shortlisted']][0]") || fail "empty shortlist"
echo "ok  scanner ranked $(echo "$scan_json" | json "len(d['results'])") coins, shortlist leader: $pick"

plan_run=$(curl -sf -X POST "$BASE/trade-plans" -H 'content-type: application/json' -d "{\"coingecko_id\":\"$pick\",\"force\":true}" | json "d['run']['id']") || fail "trade plan request"
curl -sN --max-time 180 "$BASE/runs/$plan_run/events" >/dev/null || true
plan=$(curl -sf "$BASE/runs/$plan_run")
[[ "$(echo "$plan" | json "d['status']")" == "awaiting_approval" ]] || fail "trade-plan run ended $(echo "$plan" | json "d['status']")"
plan_report=$(echo "$plan" | json "d['report_id']")
curl -sf "$BASE/reports/$plan_report" | json "d['kind']=='trade_plan' and d['content']['verification']['passed']" | grep -q True || fail "trade plan not verified"
echo "ok  trade-plan card verified for $pick"

curl -sf "$BASE/backtests" | json "any(b['run_id']=='$plan_run' for b in d)" | grep -q True || fail "backtest not saved"
curl -sf -X POST "$BASE/reports/$plan_report/approve" -H 'content-type: application/json' -d '{}' >/dev/null || fail "approve plan"
curl -sf -X POST "$BASE/paper/positions" -H 'content-type: application/json' -d "{\"report_id\":\"$plan_report\"}" >/dev/null || fail "paper position"
curl -sf "$BASE/paper" | json "len(d['positions']) > 0" | grep -q True || fail "paper portfolio empty"
echo "ok  backtest saved, approved plan is paper trading"
echo "SMOKE TEST PASSED"
