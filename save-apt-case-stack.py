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
print("저장 건수", len(rows))
if len(rows) < 3000: sys.exit("건수가 너무 적어 저장하지 않음")
cyc.upsert_rows([{"id": "signal|__apt_case_stack__", "payload": {"generatedAt": now, "rows": rows}, "fetched_at": now}])
print("저장 완료")
