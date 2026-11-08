"""낙찰 가능성(%) 양방향 보정(2026-11-08): apt-case-data가 모은 사례(낙찰가 모델이 학습에 안 쓴 2025-10-30 이후)에서 '앱이 계산한 원래 확률'과 '추천가가 실제 낙찰가 이상이었는지'를 맞춤.
지역등급(서울/경기·인천/지방)별 logit 보정 p' = sigmoid(a + b*logit(p)). 이른 절반으로 맞추고 늦은 절반 Brier가 좋아질 때만 use. 결과는 signal|__prob_cal2__에 저장 -> api가 winbid 응답에 probCal2로 붙임."""
import os, sys, json, glob, importlib.util
import numpy as np
from datetime import datetime, timezone
HERE = os.path.dirname(os.path.abspath(__file__))
s = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py")); cyc = importlib.util.module_from_spec(s); s.loader.exec_module(cyc)
D = sys.argv[1] if len(sys.argv) > 1 else "aptcases"
OOS = "2025-10-30"
rows = []
for f in glob.glob(os.path.join(D, "**", "rows.json"), recursive=True):
    for r in json.load(open(f)):
        if r.get("err") or r.get("saleDate", "") < OOS or not r.get("rec") or not r.get("act") or r.get("probRaw") is None: continue
        rows.append(r)
cls = lambda l: "서울" if str(l).startswith("11") else ("경기·인천" if str(l)[:2] in ("41", "28") else "지방")
lg = lambda p: np.log(np.clip(p, 0.003, 0.997) / (1 - np.clip(p, 0.003, 0.997)))
sg = lambda z: 1 / (1 + np.exp(-z))
def fit(x, y, iters=60):  # 2변수 로지스틱(IRLS), 약한 규제
    X = np.c_[np.ones(len(x)), x]; w = np.array([0.0, 1.0])
    for _ in range(iters):
        p = sg(X @ w); W = p * (1 - p) + 1e-9
        H = (X.T * W) @ X + 1e-3 * np.eye(2); g = X.T @ (y - p) - 1e-3 * (w - np.array([0.0, 1.0]))
        w = w + np.linalg.solve(H, g)
    return w
print("사례", len(rows))
if len(rows) < 2000: sys.exit("사례가 적어 건너뜀")
rows.sort(key=lambda r: r["saleDate"]); half = len(rows) // 2
def arr(R): return lg(np.array([r["probRaw"] for r in R], float)), np.array([1.0 if r["rec"] >= r["act"] else 0.0 for r in R])
out, br_raw, br_cal, nn = {}, 0.0, 0.0, 0
for c in ("서울", "경기·인천", "지방"):
    E = [r for r in rows[:half] if cls(r["lawd"]) == c]; L = [r for r in rows[half:] if cls(r["lawd"]) == c]
    if len(E) < 300 or len(L) < 300: continue
    xe, ye = arr(E); w = fit(xe, ye); xl, yl = arr(L)
    b0 = float(np.mean((sg(xl) - yl) ** 2)); b1 = float(np.mean((sg(w[0] + w[1] * xl) - yl) ** 2))
    br_raw += b0 * len(L); br_cal += b1 * len(L); nn += len(L)
    xa, ya = arr([r for r in rows if cls(r["lawd"]) == c]); wf = fit(xa, ya)
    out[c] = {"a": round(float(wf[0]), 4), "b": round(float(wf[1]), 4), "n": int(len(xa)), "lateBrierRaw": round(b0, 4), "lateBrierCal": round(b1, 4)}
    print(" ", c, out[c], "이른 절반 맞춤", np.round(w, 3))
use = bool(nn and (br_cal / nn) < (br_raw / nn) * 0.98)
now = datetime.now(timezone.utc).isoformat()
payload = {"generatedAt": now, "use": use, "cls": out, "check": {"lateBrierRaw": round(br_raw / max(1, nn), 4), "lateBrierCal": round(br_cal / max(1, nn), 4), "n": nn}}
print("검증", payload["check"], "use", use)
cyc.upsert_rows([{"id": "signal|__prob_cal2__", "payload": payload, "fetched_at": now}])
print("저장 완료")
