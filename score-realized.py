"""📈 실현 검증 원장 (2026-11-15, 사용자: 대리값이 아니라 실제 낙찰·되팔기 결과로 앱 예측을 다시 검증)
앱이 입찰 전에 물건 기록에 저장해 둔 예측(predSnap/predHist: 예상매도가·추천가·후보 여부)을,
그 사건의 실제 낙찰가(낙찰사례)와 낙찰 후 같은 단지·동·층에서 확인된 되판 거래(analyze-bidcases가 낙찰사례에 써 둔 resaleMatch)와 비교한다.
 - 예상매도가 오차 = (입찰 전 앱 예상매도가 − 실제 되판가) ÷ 되판가   (+ 면 앱이 높게 예측 = 손해 쪽)
 - 실현 순이익(비용 단순 가정) = 되판가 − 낙찰가×1.05 − 400만  (analyze-bidcases와 같은 가정, 세금 제외)
되판 거래는 호수를 몰라 옆집 거래일 수 있으므로(resale-detection-limits 참고) '동까지 확인된 것'을 우선 쓰고 표본이 적으면 전체로 보되 basis에 적는다.
결과는 정확도 원장(accuracy_ledger)에 'realized'(전체)·'realized_go'(임장 후보였던 것)로 매주 한 줄씩 쌓인다. 계산 규칙은 바꾸지 않는다.
환경변수가 없으면(로컬) 계산만 하고 결과를 출력한다.  사용: python score-realized.py
"""
import os, re, json, sys
from datetime import datetime, timezone, timedelta
import numpy as np
import requests

SITE_URL = (os.environ.get("SITE_URL") or "https://1234auction.vercel.app").rstrip("/")
COST_RATIO, FIXED_COST = 1.05, 400.0


def norm_case(s): return re.sub(r"\s", "", str(s or "").replace("타경", "-"))
def region_of(addr):
    m = re.search(r"(\S+[시도])\s*(\S+[시군구])(?:\s*(\S+구))?", str(addr or ""))
    return (m.group(2) + (m.group(3) or "")) if m else ""
def to_date(s):
    s = re.sub(r"\D", "", str(s or ""))
    return datetime.strptime(s[:8], "%Y%m%d") if len(s) >= 8 else None


def pick_snap(a, sale_d):
    hist = [h for h in (a.get("predHist") or []) if isinstance(h, dict) and h.get("at")]
    if not hist and a.get("predSnap"): hist = [a["predSnap"]]
    ok = [h for h in hist if h.get("at") and datetime.strptime(h["at"][:10], "%Y-%m-%d") <= sale_d]
    return max(ok, key=lambda h: h["at"]) if ok else None


def stats(rows):
    err = np.array([r["err"] for r in rows]); net = np.array([r["net"] for r in rows])
    return {"n": int(len(rows)), "err": round(float(np.median(np.abs(err))) * 100, 2), "bias": round(float(np.median(err)) * 100, 2),
            "hi10": round(float((err > 0.10).mean()) * 100, 1), "netMed": round(float(np.median(net))), "lossPct": round(float((net < 0).mean()) * 100, 1),
            "recWonPct": round(float(np.mean([r["recWon"] for r in rows if r["recWon"] is not None])) * 100, 1) if any(r["recWon"] is not None for r in rows) else None}


def collect_live():
    """입찰 전 저장 예측 ↔ 실제 낙찰 ↔ 되판 거래가 이어진 사례(실전). 병합 스크립트(score-pooled.py)도 이 함수를 씀"""
    au = requests.get(f"{SITE_URL}/api/auction", timeout=180).json()
    bc = requests.get(f"{SITE_URL}/api/auction?kind=bidCases", timeout=300).json()
    amap = {}
    for a in au:
        if isinstance(a, dict) and a.get("caseNo") and not a.get("isBacktest") and (a.get("predSnap") or a.get("predHist")):
            amap.setdefault(norm_case(a["caseNo"]), []).append(a)
    rows = []; seen = set()
    for c in bc:
        if not isinstance(c, dict): continue
        L = amap.get(norm_case(c.get("caseNo")))
        rm = c.get("resaleMatch") or {}
        if not L or not rm.get("amount") or not (c.get("finalBidPrice") or 0) > 0: continue
        a = next((x for x in L if x.get("dong") and x.get("dong") == c.get("dong")), None) or next((x for x in L if region_of(x.get("addr")) and region_of(x.get("addr")) == region_of(c.get("addrJibun"))), None)
        if not a: continue
        sale_d, rs_d = to_date(c.get("saleDate")), to_date(rm.get("date"))
        if not sale_d or not rs_d or (rs_d - sale_d).days < 14: continue
        sn = pick_snap(a, sale_d)
        if not sn or not sn.get("sale"): continue
        actual = float(c["finalBidPrice"]) / 10000.0; resale = float(rm["amount"])
        try:   # 저장 당시 최저가와 낙찰사례 최저가가 2% 넘게 다르면 다른 회차의 예측일 수 있어 제외
            sm, am = float(sn.get("minBid") or 0), float(c.get("minBidPrice") or 0) / 10000.0
            if sm > 0 and am > 0 and abs(sm / am - 1) > 0.02: continue
        except (TypeError, ValueError): pass
        key = (norm_case(c.get("caseNo")), region_of(c.get("addrJibun")))
        if key in seen: continue
        seen.add(key)
        rec = sn.get("recBid")
        rows.append({"case": c.get("caseNo"), "sale": str(c.get("saleDate")), "actual": actual, "resale": resale, "m": round((rs_d - sale_d).days / 30.4, 1),
                     "snapSale": float(sn["sale"]), "rec": rec, "go": bool(sn.get("go")), "conf": rm.get("conf") or ("approx" if rm.get("approx") else "floor"),
                     "err": (float(sn["sale"]) - resale) / resale, "net": resale - actual * COST_RATIO - FIXED_COST,
                     "recWon": (actual <= rec) if rec else None, "type": sn.get("type") or "apt", "net_pred": sn.get("net"), "key": key[0] + "|" + key[1]})
    print(f"예측 저장 {len(amap):,}건 · 낙찰 + 되판 거래까지 이어진 사례 {len(rows):,}건")
    return rows, len(amap)


def main():
    rows, n_snap = collect_live()
    out = {}
    if rows:
        dong = [r for r in rows if r["conf"] == "dong"]
        base = dong if len(dong) >= 10 else rows
        basis = "dong" if base is dong else "all"
        out["realized"] = dict(stats(base), basis=basis)
        go = [r for r in base if r["go"]]
        if go: out["realized_go"] = dict(stats(go), basis=basis)
        for k, v in out.items(): print(f"  {k}: {json.dumps(v, ensure_ascii=False)}")
    else:
        print("  아직 이어진 사례가 없어요(되팔린 거래가 확인되면 쌓여요)")
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        spec = importlib.util.spec_from_file_location("cyc", os.path.join(here, "analyze-cycle.py")); cyc = importlib.util.module_from_spec(spec); spec.loader.exec_module(cyc)
        import accuracy_ledger as led
        labels = {"realized": "앱 예측 vs 실제 되판 가격(전체)", "realized_go": "앱 예측 vs 실제 되판 가격(임장 후보였던 것)"}
        for k, v in out.items(): led.record(cyc, k, v, labels[k])
        if not out: led.record(cyc, "realized", {"n": 0, "err": None, "bias": None, "hi10": None, "basis": "none"}, labels["realized"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
