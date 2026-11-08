"""예상매도가 최근 쏠림 자동 보정(2026-11-08): 앱이 낙찰 35일 전 자료로 계산한 종합 예상매도가(보정 전 값)와 낙찰 뒤 6개월 같은 단지·평형 시장 중위값을 비교.
지역등급별 보정 pct = 최근 '정답이 나온'(낙찰일+183일 <= 오늘) 구간 중 낙찰일이 오늘-270일~오늘-183일인 사례의 (시장/예상 - 1) 중앙값.
walk-forward 검증: 각 사례를 그 사례 낙찰일 기준 같은 창(낙찰일-270일~-183일)의 중앙값으로 보정했을 때 오차가 줄어드는지(늦은 절반). 줄 때만 use. 결과는 signal|__sale_corr__ -> api가 winbid 응답에 saleCorr로 붙임."""
import os, sys, json, glob, importlib.util
import numpy as np
from datetime import datetime, timezone, timedelta
HERE = os.path.dirname(os.path.abspath(__file__))
s = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py")); cyc = importlib.util.module_from_spec(s); s.loader.exec_module(cyc)
D = sys.argv[1] if len(sys.argv) > 1 else "aptcases"
cls = lambda l: "서울" if str(l).startswith("11") else ("경기·인천" if str(l)[:2] in ("41", "28") else "지방")
rows = []
for f in glob.glob(os.path.join(D, "**", "rows.json"), recursive=True):
    for r in json.load(open(f)):
        base = r.get("stkRaw") or r.get("saleFinal")
        if r.get("err") or not r.get("mkt") or not base or not r.get("saleDate"): continue
        rows.append({"d": datetime.strptime(r["saleDate"], "%Y-%m-%d"), "cls": cls(r["lawd"]), "e": r["mkt"] / base - 1})
print("사례", len(rows))
if len(rows) < 1500: sys.exit("사례가 적어 건너뜀")
now = datetime.now(timezone.utc).replace(tzinfo=None)
def window_med(c_rows, ref):   # ref 시점에 이미 정답이 나온 사례: 낙찰일 in [ref-270, ref-183]
    v = [x["e"] for x in c_rows if ref - timedelta(days=270) <= x["d"] <= ref - timedelta(days=183)]
    return (float(np.median(v)), len(v)) if len(v) >= 40 else (None, len(v))
out, ba, bb, nn = {}, 0.0, 0.0, 0
for c in ("서울", "경기·인천", "지방"):
    C = sorted([x for x in rows if x["cls"] == c], key=lambda x: x["d"])
    if len(C) < 300: continue
    L = C[len(C) // 2:]; ea = []; eb = []
    for x in L:
        m, n = window_med(C, x["d"])
        if m is None: continue
        ea.append(abs(x["e"])); eb.append(abs(x["e"] - m))
    cur, n_cur = window_med(C, now)
    chk = {"n": len(ea), "오차보정없음": round(float(np.median(ea)), 4) if ea else None, "오차보정": round(float(np.median(eb)), 4) if eb else None, "평균오차없음": round(float(np.mean(ea)), 4) if ea else None, "평균오차보정": round(float(np.mean(eb)), 4) if eb else None}
    out[c] = {"pct": None if cur is None else round(cur, 4), "n": n_cur, "check": chk}
    print(" ", c, out[c])
    if ea: ba += float(np.mean(ea)) * len(ea); bb += float(np.mean(eb)) * len(eb); nn += len(ea)
use_c = {}
for c, v in out.items():
    ch = v["check"]; use_c[c] = bool(v["pct"] is not None and ch["n"] >= 100 and ch["평균오차보정"] is not None and ch["평균오차보정"] < ch["평균오차없음"])   # 2026-11-08 사용자 방침: 결과가 비슷해도 시장 흐름을 따르는 근거식이 더 정확하면 적용 - 늦은 구간 평균 오차가 줄기만 하면 use
payload = {"generatedAt": now.isoformat(), "use": any(use_c.values()), "cls": {c: {"pct": v["pct"], "n": v["n"], "on": use_c[c], "check": v["check"]} for c, v in out.items()}}
# 앱은 cls[c].pct만 보므로 검증 통과한 등급만 pct를 남김
for c in list(payload["cls"].keys()):
    if not payload["cls"][c]["on"]: payload["cls"][c]["pct"] = None
print("use", use_c)
cyc.upsert_rows([{"id": "signal|__sale_corr__", "payload": payload, "fetched_at": payload["generatedAt"]}])
print("저장 완료")
