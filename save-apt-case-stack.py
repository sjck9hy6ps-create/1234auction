"""아파트 낙찰사례 되돌려 계산한 값(apt-case-data 결과)을 signal|__apt_case_stack__에 저장 → 매주 낙찰가 모델이 종합 평가 시세로 학습(2026-11-07)"""
import os, sys, json, glob, importlib.util
from datetime import datetime, timezone
HERE = os.path.dirname(os.path.abspath(__file__))
s = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py")); cyc = importlib.util.module_from_spec(s); s.loader.exec_module(cyc)
D = sys.argv[1] if len(sys.argv) > 1 else "aptcases"
rows = {}
for f in glob.glob(os.path.join(D, "**", "rows.json"), recursive=True):
    for r in json.load(open(f)):
        if r.get("err") or not r.get("sale"): continue
        rows[str(r["id"])] = [int(r.get("stk") or r["sale"]), int(r["sale"])]
now = datetime.now(timezone.utc).isoformat()
print("이번 계산 건수", len(rows))
# 2026-11-17(사용자: 2020년~ 전체 사례 학습 적용): 2025-02-15 이전 사례 값은 한 번 계산하면 바뀌지 않으므로, 이미 저장된 값을 남기고 이번에 계산한 값으로 덮어쓰기(병합)
try:
    import requests
    old = requests.get(f"{cyc.SUPABASE_URL}/rest/v1/leader_follower_cache", headers=cyc.HEADERS, params={"select": "payload", "id": "eq.signal|__apt_case_stack__"}, timeout=120).json()
    old_rows = (old[0]["payload"] or {}).get("rows", {}) if old else {}
except Exception as e:
    sys.exit(f"기존 저장값을 읽지 못해 병합 불가 - 저장하지 않음: {e}")
print("기존 저장 건수", len(old_rows))
if os.environ.get("STACK_REPLACE") != "1":
    merged = dict(old_rows); merged.update(rows); rows = merged
print("저장 건수(병합 후)", len(rows))
if len(rows) < 3000: sys.exit("건수가 너무 적어 저장하지 않음")
cyc.upsert_rows([{"id": "signal|__apt_case_stack__", "payload": {"generatedAt": now, "rows": rows}, "fetched_at": now}])
print("저장 완료")
