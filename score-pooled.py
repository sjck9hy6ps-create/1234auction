"""📊 과거 전체 + 실전 병합 실현 검증 (2026-11-15, 사용자: 과거 전체와 현재 순이익을 병합해 계산식의 평균을 알고 싶다 - 아파트·빌라 모두)
한 줄 = 낙찰 사건 1건:  앱이 낙찰 전에 낸 예상매도가(pred) ↔ 낙찰 후 되판 가격(resale) ↔ 추천가·예상 순이익(net_pred).
 · 과거(hist): 사건마다 낙찰일 35일 전 정보로 앱 계산을 다시 돌린 값(as-of) + 낙찰 후 180일 안 같은 단지·건물 실거래(대리 되판가)
 · 실전(live): 앱이 입찰 전에 실제 저장한 예측 + analyze-bidcases가 찾은 실제 되판 거래
 같은 사건이 양쪽에 있으면 실전을 씀. 실현 순이익 ≈ 예상 순이익 − (예상매도가 − 되판가)  (세금·보유기간 변화 제외, 1:1 가정 - 기존 점검과 같은 방식)
 평균 비교 대상은 '추천가로 낙찰될 사례(추천가 > 실제 낙찰가)'. 결과는 정확도 원장 'pooled_apt'·'pooled_villa'에 매월 한 줄(분기별 추이 q 포함).
 ⚠️ 되팔린(또는 이후 거래가 확인된) 사건만 보이므로 못 팔린 사건이 빠져 실현 평균이 낙관 쪽으로 기울 수 있음 - coverage(대리값이 잡힌 비율)를 같이 기록.
 입력: data/asof-apt-rows.json·data/asof-villa-rows.json(과거 재계산 보관본) + 이번 달 새 재계산 산출물(aptrows-*/rows.json, villa-new/villa-score-rows.json) + apt-realized-rows.json(analyze-apt-realized 결과)
환경변수(SUPABASE_*)가 없으면(로컬) 아파트만 apt-realized-rows.json 으로 계산해 출력한다.  사용: python score-pooled.py
"""
import os, re, json, glob, sys, importlib.util
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
SITE_URL = (os.environ.get("SITE_URL") or "https://1234auction.vercel.app").rstrip("/")
HAVE_DB = bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))


def load(name, fn):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, fn)); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def norm_case(s): return re.sub(r"\s", "", str(s or "").replace("타경", "-"))
def region_of(addr):
    m = re.search(r"(\S+[시도])\s*(\S+[시군구])(?:\s*(\S+구))?", str(addr or ""))
    return (m.group(2) + (m.group(3) or "")) if m else ""
def qtr(d):
    d = re.sub(r"\D", "", str(d or ""))
    return f"{d[:4]}-Q{(int(d[4:6]) - 1) // 3 + 1}" if len(d) >= 6 else None
def jload(p, default):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return default


def merge_rows(old, new):
    m = {r["id"]: r for r in old if isinstance(r, dict) and r.get("id")}
    for r in new:
        if isinstance(r, dict) and r.get("id") and not r.get("err"): m[r["id"]] = r
    return list(m.values())


def stats(rows, coverage=None):
    """rows: [{src,type,date,pred,resale,act,rec,net_pred,go}]"""
    df = pd.DataFrame(rows)
    if not len(df): return None
    df["gap"] = df["pred"] - df["resale"]; df["err"] = df["gap"] / df["resale"]
    out = {"n": int(len(df)), "nHist": int((df["src"] == "hist").sum()), "nLive": int((df["src"] == "live").sum()),
           "err": round(float(df["err"].abs().median()) * 100, 2), "bias": round(float(df["err"].median()) * 100, 2),
           "hi10": round(float((df["err"] > 0.10).mean()) * 100, 1), "gapMean": round(float(df["gap"].mean()), 1)}
    if coverage is not None: out["coverage"] = coverage

    def net_block(X):
        W = X[X["rec"].notna() & X["act"].notna() & (X["rec"] > X["act"]) & X["net_pred"].notna()].copy()
        if len(W) < 5: return None
        W["real"] = W["net_pred"] - W["gap"]
        rng = np.random.default_rng(0); v = W["real"].values
        bs = [float(rng.choice(v, len(v)).mean()) for _ in range(600)]
        return {"nNet": int(len(W)), "nNetLive": int((W["src"] == "live").sum()), "netPred": round(float(W["net_pred"].mean())), "netPredMed": round(float(W["net_pred"].median())),
                "netReal": round(float(W["real"].mean())), "netRealMed": round(float(W["real"].median())), "lossPct": round(float((W["real"] < 0).mean()) * 100, 1),
                "ratio": round(float(W["real"].mean() / W["net_pred"].mean()), 2) if W["net_pred"].mean() else None,
                "ciLo": round(float(np.percentile(bs, 2.5))), "ciHi": round(float(np.percentile(bs, 97.5)))}, W
    nb = net_block(df)
    if nb:
        out.update(nb[0]); W = nb[1]
        W["q"] = W["date"].map(qtr)
        out["q"] = [[q, int(len(g)), round(float(g["net_pred"].mean())), round(float(g["real"].mean())), round(float((g["real"] < 0).mean()) * 100, 1)]
                    for q, g in sorted(W.groupby("q"), key=lambda x: str(x[0])) if q and len(g) >= 8][-8:]
    gb = net_block(df[df["go"] == True]) if "go" in df else None
    if gb:
        g0 = gb[0]; out["go"] = {k: g0[k] for k in ("nNet", "netPred", "netReal", "lossPct", "ratio")}
    return out


def main():
    cyc = None
    if HAVE_DB:
        cyc = load("cyc", "analyze-cycle.py")
    live_mod = load("sr", "score-realized.py")
    # ── 실전
    try: live_rows, _ = live_mod.collect_live()
    except Exception as e:
        print("실전 사례 수집 실패(건너뜀):", e); live_rows = []
    live_keys = {r["key"] for r in live_rows if r.get("key")}
    # ── 낙찰사례(사건번호·주소 매핑, 대리 되판가 계산용)
    BC = {}
    try:
        bc = requests.get(f"{SITE_URL}/api/auction?kind=bidCases", timeout=300).json()
        BC = {c["id"]: c for c in bc if isinstance(c, dict) and c.get("id")}
    except Exception as e:
        print("낙찰사례 불러오기 실패:", e)
    keyof = lambda cid: (norm_case(BC[cid].get("caseNo")) + "|" + region_of(BC[cid].get("addrJibun"))) if cid in BC else None

    # ── 아파트 과거(대리 되판가는 analyze-apt-realized.py가 만든 apt-realized-rows.json)
    hist_apt = jload(os.path.join(HERE, "data", "asof-apt-rows.json"), [])
    new_apt = []
    for f in glob.glob("aptrows-*/rows.json"):
        if "aptrows-hist" in f: continue
        new_apt += jload(f, [])
    all_apt = merge_rows(hist_apt, new_apt)
    gomap = {r["id"]: bool(r.get("go")) for r in all_apt}
    O = jload("apt-realized-rows.json", []) or jload(os.path.join(HERE, "apt-realized-rows.json"), [])
    apt_rows = []
    for r in O:
        k = keyof(r.get("id"))
        if k and k in live_keys: continue
        if r.get("ref") and r.get("sale"):
            apt_rows.append({"src": "hist", "type": "apt", "date": r.get("saleDate"), "pred": float(r["sale"]), "resale": float(r["ref"]), "act": r.get("act"), "rec": r.get("rec"),
                             "net_pred": r.get("margin"), "go": gomap.get(r.get("id"), False)})
    apt_rows += [{"src": "live", "type": "apt", "date": r["sale"], "pred": r["snapSale"], "resale": r["resale"], "act": r["actual"], "rec": r.get("rec"), "net_pred": r.get("net_pred"), "go": r["go"]}
                 for r in live_rows if r.get("type") != "villa"]
    cov_apt = round(len([r for r in O if r.get("ref")]) / max(len(all_apt), 1) * 100, 1) if all_apt else None

    # ── 빌라 과거(재계산 + 대리 되판가)
    hist_v = jload(os.path.join(HERE, "data", "asof-villa-rows.json"), [])
    new_v = jload("villa-new/villa-score-rows.json", [])
    all_v = merge_rows(hist_v, new_v)
    v_rows = []; cov_v = None
    if HAVE_DB and all_v:
        try:
            bv = load("bv", "backtest-villa.py"); avm = bv.avm
            raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,build_year", extra_filter="&deal_date=gte.20250101")
            T = bv.prep(raw); T["dt"] = pd.to_datetime(T["deal_date"].astype(str), format="%Y%m%d", errors="coerce")
            G = {k: g for k, g in T.groupby(["dong", "bunji"])}
            SIDO = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원", "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북", "전라남도": "전남", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주"}
            hit = 0
            for r in all_v:
                c = BC.get(r["id"])
                if not c or not r.get("est") or not r.get("actual"): continue
                k = keyof(r["id"])
                if k and k in live_keys: continue
                sido = SIDO.get((c.get("addrJibun") or "").split(" ")[0], "")
                g = G.get((c.get("dong"), str(c.get("bunji"))))
                if g is None: continue
                sd = pd.to_datetime(c.get("saleDate")); area = c.get("areaM2") or 0
                if sido: g = g[g["region"].astype(str).str.startswith(sido)]
                m = g[(g["dt"] > sd) & (g["dt"] <= sd + pd.Timedelta(days=180)) & ((g["size"] - area).abs() <= 6)]
                if len(m) < 1: continue
                hit += 1
                v_rows.append({"src": "hist", "type": "villa", "date": str(r.get("sale")), "pred": float(r["est"]), "resale": float(np.median(m["ppm"].values)) * area, "act": r.get("actual"), "rec": r.get("rec"), "net_pred": r.get("net"), "go": bool(r.get("go"))})
            cov_v = round(hit / max(len(all_v), 1) * 100, 1)
        except Exception as e:
            print("빌라 대리 되판가 계산 실패(건너뜀):", e)
    v_rows += [{"src": "live", "type": "villa", "date": r["sale"], "pred": r["snapSale"], "resale": r["resale"], "act": r["actual"], "rec": r.get("rec"), "net_pred": r.get("net_pred"), "go": r["go"]}
               for r in live_rows if r.get("type") == "villa"]

    out = {}
    for name, rows, cov in (("pooled_apt", apt_rows, cov_apt), ("pooled_villa", v_rows, cov_v)):
        st = stats(rows, cov)
        if st: out[name] = st; print(f"{name}: {json.dumps(st, ensure_ascii=False)}")
        else: print(f"{name}: 사례 없음")
    if cyc and out:
        import accuracy_ledger as led
        labels = {"pooled_apt": "과거+실전 병합 실현 검증(아파트)", "pooled_villa": "과거+실전 병합 실현 검증(빌라)"}
        for k, v in out.items(): led.record(cyc, k, v, labels[k])
    # 재계산 보관본 갱신(새 사건만 더해 다음 달에 다시 계산하지 않게)
    if HAVE_DB:
        os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
        keep = ["id", "saleDate", "act", "rec", "margin", "verdict", "saleFinal", "lawd", "probRec", "nd", "ndLoaded", "ndLat", "ndSale", "ndMin", "mkt", "go", "err", "sale", "fails", "minB"]
        json.dump([{k: r.get(k) for k in keep if r.get(k) is not None} for r in all_apt], open(os.path.join(HERE, "data", "asof-apt-rows.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        json.dump(all_v, open(os.path.join(HERE, "data", "asof-villa-rows.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
