"""
🔧 예상매도가 반영 비율 재조정 (2026-10-08, 사용자: "예상매도가도 다시 맞춰줘")
앱의 예상매도가는 같은 단지·같은 평형(±3㎡) 실거래로 계산한다: 최근 3개월 5건+ → 중위값, 아니면 최근 6개월 3건+ → 하위 40% 지점,
여기에 저층·고층 보정을 곱함(index.html computeBidBoardRow/aptOwnTradeStats). 이 스크립트는
 ① 그 계산을 "입찰 30일 전" 기준으로 그대로 재현(own-complex 경로) → ② 낙찰 후 6개월 안에 같은 동·층에서 되팔린 가격(동 확인)과 비교
 → ③ 남는 오차를 단지 거래 수·지역·평형·층 위치·최근 추세 같은 요인별 보정표로 줄임(walk-forward 시험: 2025상·하반기·2026)
 → ④ 분위(0.4·0.5·0.6)·최소 건수 조합도 비교. 결과(보정표 JSON)를 로그에 출력.
"""
import os, re, json, math, importlib.util
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ab", os.path.join(HERE, "analyze-bidcases.py"))
ab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ab)
avm = ab.avm
SITE = ab.SITE_URL


def med(x):
    return float(np.median(x)) if len(x) else None


def qtile(x, q):
    if not len(x): return None
    x = np.sort(np.asarray(x, float)); i = (len(x) - 1) * q; lo, hi = int(math.floor(i)), int(math.ceil(i))
    return float(x[lo] + (x[hi] - x[lo]) * (i - lo))


def main():
    cases = pd.DataFrame(requests.get(f"{SITE}/api/auction?kind=bidCases", timeout=180).json())
    df = cases[cases["propertyType"].astype(str).str.contains("아파트", na=False)].copy()
    df["actual"] = pd.to_numeric(df["finalBidPrice"], errors="coerce") / 10000.0
    df["area"] = pd.to_numeric(df["areaM2"], errors="coerce")
    df["fl"] = pd.to_numeric(df["floor"], errors="coerce")
    df = df[(df["actual"] > 0) & df["area"].notna() & df["fl"].notna() & df["saleDate"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)]
    df["sale_int"] = df["saleDate"].str.replace("-", "").astype(int)
    cut_old = int((datetime.now() - timedelta(days=200)).strftime("%Y%m%d"))
    df = df[(df["sale_int"] >= 20230101) & (df["sale_int"] <= cut_old)].copy()
    df["region"] = df["addrJibun"].map(ab.region_norm); df["dk"] = df["dong"].map(ab.dong_key)

    def full_bunji(row):
        d = str(row.get("dong") or "")
        m = re.search(re.escape(d) + r"\s+(산?\d+(?:-\d+)?)", str(row.get("addrJibun") or "")) if d else None
        return m.group(1).replace("산", "").strip() if m else str(row.get("bunji") or "").strip()
    df["bunji_s"] = df.apply(full_bunji, axis=1)

    def case_adong(row):
        ad = row.get("aptDong")
        if isinstance(ad, str) and ad.strip().isdigit(): return str(int(ad.strip()))
        txt = str(row.get("addrJibun") or ""); b = str(row.get("bunji") or "")
        tail = txt.split(b, 1)[1] if b and b in txt else txt
        for t in (tail, str(row.get("unitNo") or "")):
            m = re.search(r"(\d{1,4})\s*동(?![가-힣])", t)
            if m: return str(int(m.group(1)))
        return ""
    df["adong"] = df.apply(case_adong, axis=1)
    df = df[df["adong"] != ""].dropna(subset=["region", "dk"]).reset_index(drop=True)
    names = set()
    for r in df["region"].unique():
        sd, gu = r.split(" ", 1)
        for alias in ({"전남광주": ["전남광주", "광주", "전남"]}.get(sd, [sd])): names.add(f"{alias} {gu}")
    flt = "&or=(" + ",".join('region.like."' + n + '*"' for n in sorted(names)) + ")"
    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,apt_dong,cdeal_type", extra_filter=f"&deal_date=gte.20190101{flt}")
    if "cdeal_type" in tr.columns: tr = tr[tr["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    for c in ("price", "size", "floor", "deal_date"): tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"])
    tr = tr[(tr["price"] > 0) & (tr["size"] > 10)]
    tr["dk"] = tr["dong"].map(ab.dong_key); tr["region_n"] = tr["region"].map(ab.region_norm); tr["bunji_s"] = tr["bunji"].astype(str).str.strip()
    tr["adong"] = tr["apt_dong"].map(lambda v: str(int(re.search(r"(\d{1,4})", str(v)).group(1))) if re.search(r"(\d{1,4})", str(v or "")) else "")
    tr["is_direct"] = (tr["dealing_type"] == "직거래")
    tr["ts"] = pd.to_datetime(tr["deal_date"].astype(int).astype(str), format="%Y%m%d", errors="coerce")
    tr = tr.dropna(subset=["ts"])
    tr["tday"] = (tr["ts"] - pd.Timestamp("2000-01-01")).dt.days.astype(float)
    groups = {k: g.sort_values("tday").reset_index(drop=True) for k, g in tr.groupby(["region_n", "dk", "bunji_s"])}
    print(f"  대상 사례 {len(df):,}건(동 번호 있음), 실거래 {len(tr):,}건, 단지 {len(groups):,}곳")

    rows = []
    for c in df.itertuples():
        g = groups.get((c.region, c.dk, c.bunji_s))
        if g is None: continue
        sd = pd.Timestamp(ab.int_to_date(int(c.sale_int)))
        asof = (sd - pd.Timedelta(days=30) - pd.Timestamp("2000-01-01")).days
        # 정답: 낙찰 후 14일~6개월, 같은 동·층·면적(±2㎡), 낙찰가의 70%+ 첫 거래(동 번호 있는 거래만)
        lo = (sd + pd.Timedelta(days=14) - pd.Timestamp("2000-01-01")).days; hi = (sd + pd.Timedelta(days=183) - pd.Timestamp("2000-01-01")).days
        R = g[(g["tday"] >= lo) & (g["tday"] <= hi) & (g["adong"] == c.adong) & (g["floor"] == c.fl) & ((g["size"] - c.area).abs() <= 2) & (g["price"] >= c.actual * 0.7)]
        if not len(R): continue
        resale = float(R.iloc[0]["price"]); resale_m = (R.iloc[0]["tday"] - asof - 30) / 30.4
        H = g[g["tday"] < asof]
        if not len(H): continue
        maxF = int(H["floor"].max()) if H["floor"].notna().any() else 0
        S = H[(~H["is_direct"]) & ((H["size"] - c.area).abs() <= 3)]
        age_m = (asof - S["tday"].values) / 30.4
        p3 = S["price"].values[age_m <= 3]; p6 = S["price"].values[age_m <= 6]; p12 = S["price"].values[age_m <= 12]
        if not ((len(p3) >= 5) or (len(p6) >= 3)): continue
        tf = int(c.fl)
        # 저층·고층 보정(앱과 같은 규칙, 승강기 정보가 없던 시점이라 층수 단지 구분만)
        allp = H[(~H["is_direct"]) & (H["floor"] > 0)]
        allp = allp[(asof - allp["tday"]) / 30.4 <= 60]
        factor = 1.0
        lim = max(3, int(maxF * 0.2))
        if maxF > 0 and tf <= lim:
            inb = (allp["floor"] <= 1) if tf <= 1 else ((allp["floor"] >= 2) & (allp["floor"] <= lim))
            A = allp[inb]; B = allp[~inb]
            rs = []
            if len(A) and len(B):
                bt = B["tday"].values; bp = (B["price"] / B["size"]).values
                for t, p, s in zip(A["tday"].values, A["price"].values, A["size"].values):
                    ref = bp[np.abs(bt - t) <= 180]
                    if len(ref) >= 3: rs.append((p / s) / np.median(ref))
            cls = "noE" if maxF <= 5 else ("mid" if maxF <= 10 else "tall")
            dft = {"noE": (0.99, 0.97), "mid": (0.98, 0.98), "tall": (0.915, 0.94)}[cls][0 if tf <= 1 else 1]
            nR = len(rs); ownR = min(1.05, float(np.median(rs))) if nR else None
            factor = (nR * ownR + 10 * dft) / (nR + 10) if nR else dft
        else:
            hiLim = max(4, math.ceil(maxF * 0.8))
            if maxF > 0 and tf >= hiLim and tf < maxF:
                S36 = S[(asof - S["tday"]) / 30.4 <= 36]
                gh = S36[(S36["floor"] >= hiLim) & (S36["floor"] < maxF)]["price"].values
                allH = S36["price"].values
                rh = max(1.0, min(1.08, np.median(gh) / np.median(allH))) if (len(gh) >= 3 and len(allH) >= 6) else None
                factor = rh or 1.015
        base3, base6 = qtile(p3, 0.5), qtile(p6, 0.4)
        rows.append(dict(region=c.region, sale=int(c.sale_int), area=float(c.area), fl=tf, maxF=maxF, n3=len(p3), n6=len(p6), n12=len(p12),
                         p3q=[qtile(p3, q) if len(p3) else None for q in (0.3, 0.4, 0.5, 0.6, 0.7)], p6q=[qtile(p6, q) if len(p6) else None for q in (0.3, 0.4, 0.5, 0.6, 0.7)],
                         m12=med(p12), factor=float(factor), resale=resale, resale_m=float(resale_m), actual=float(c.actual), dk=c.dk, nm=str(getattr(c, "buildingName", "") or "")))
    D = pd.DataFrame(rows)
    print(f"  앱 방식 재현 가능 사례 {len(D):,}건 (동 확인 6개월 내 되팔기 있음)")
    if os.environ.get("KEEP_PKL"):
        D.to_json("tune-sale-est.json", orient="records", force_ascii=False)
    run_tuning(D)


def run_tuning(D):
    D = D.copy()
    D["est0"] = np.where(D["n3"] >= 5, D["p3q"].map(lambda v: v[2]), D["p6q"].map(lambda v: v[1])) * D["factor"]
    D = D[D["est0"].notna() & (D["est0"] > 0)].copy()
    D["y"] = np.log(D["resale"] / D["est0"])
    D = D[D["y"].between(np.log(0.5), np.log(1.6))].sort_values("sale").reset_index(drop=True)
    FOLDS = [(20250101, 20250701), (20250701, 20260101), (20260101, 20261231)]
    def sc(te, p):
        e = np.exp(p) * te["est0"] / te["resale"] - 1
        return dict(mae=float(np.median(np.abs(e))) * 100, w10=float((np.abs(e) <= .1).mean()) * 100, bias=float(np.median(e)) * 100, under20=float((e < -0.2).mean()) * 100)
    def cv(name, fn, verbose=True):
        res = []
        for a, b in FOLDS:
            trn = D[D["sale"] < a]; te = D[(D["sale"] >= a) & (D["sale"] < b)]
            if len(te) < 200: continue
            res.append((len(te), sc(te, fn(trn, te))))
        tot = sum(n for n, _ in res); avg = lambda k: sum(n * s[k] for n, s in res) / tot
        if verbose: print(f"{name:46s} 오차 {avg('mae'):.2f}% ±10% {avg('w10'):.1f}% 쏠림 {avg('bias'):+.2f}% 20%+ 낮게 맞힘 {avg('under20'):.1f}% | " + " ".join(f"{s['mae']:.2f}" for _, s in res))
        return avg('mae')
    print("\n=== 1) 지금 앱 방식 그대로 ===")
    cv("앱 방식(3개월 5건+ 중위값, 6개월 3건+ 40%)", lambda trn, te: np.zeros(len(te)))
    print("\n=== 2) 분위·최소 건수 조합 (보정 없이) ===")
    qi = {0.3: 0, 0.4: 1, 0.5: 2, 0.6: 3, 0.7: 4}
    best = None
    for q3 in (0.4, 0.5, 0.6):
        for q6 in (0.3, 0.4, 0.5, 0.6):
            for n3 in (3, 5, 8):
                for n6 in (2, 3, 5):
                    def f(trn, te, q3=q3, q6=q6, n3=n3, n6=n6):
                        e = np.where(te["n3"] >= n3, te["p3q"].map(lambda v: v[qi[q3]]), np.where(te["n6"] >= n6, te["p6q"].map(lambda v: v[qi[q6]]), np.nan)) * te["factor"]
                        e = np.where(np.isnan(e.astype(float)), te["est0"], e)
                        return np.log(e / te["est0"].values)
                    m = cv("", f, verbose=False)
                    if best is None or m < best[0]: best = (m, q3, q6, n3, n6)
    print(f"  최적 조합: 3개월 {best[3]}건+ {best[1]}분위 / 6개월 {best[4]}건+ {best[2]}분위 → 오차 {best[0]:.2f}%")
    q3, q6, n3m, n6m = best[1], best[2], best[3], best[4]
    D["est1"] = np.where(D["n3"] >= n3m, D["p3q"].map(lambda v: v[qi[q3]]), np.where(D["n6"] >= n6m, D["p6q"].map(lambda v: v[qi[q6]]), D["est0"] / D["factor"])) * D["factor"]
    cv("최적 분위 조합 적용", lambda trn, te: np.log(te["est1"].values / te["est0"].values))
    print("\n=== 3) 요인별 보정표(백피팅, 축소 k) ===")
    m = D["sale"] // 100 % 100
    D["season"] = m.map(lambda v: "겨울" if v in (12, 1, 2) else ("봄" if v <= 5 else ("여름" if v <= 8 else "가을")))
    D["fpos"] = [("1층" if f <= 1 else ("저층" if f <= max(3, int(mf * 0.2)) else ("꼭대기" if (mf and f >= mf) else ("고층" if (mf and f >= max(4, math.ceil(mf * 0.8))) else "중간")))) for f, mf in zip(D["fl"], D["maxF"])]
    D["mxc"] = D["maxF"].map(lambda v: "5층↓" if v <= 5 else ("6~10층" if v <= 10 else ("11~20층" if v <= 20 else "21층+")))
    D["size"] = D["area"].map(lambda a: "소형" if a < 60 else ("중형" if a <= 85 else "대형"))
    D["ownb"] = [("3개월10건+" if a >= 10 else ("3개월5~9건" if a >= 5 else ("6개월6건+" if b >= 6 else "6개월3~5건"))) for a, b in zip(D["n3"], D["n6"])]
    tr_ = D["m12"] / D["est0"] * D["factor"]
    D["trend"] = pd.cut((D["est0"] / D["factor"]) / D["m12"], [0, 0.97, 0.995, 1.005, 1.03, 9]).astype(str)
    D["region2"] = D["region"]
    FACT = ["ownb", "region2", "size", "fpos", "mxc", "season", "trend"]
    def fit(trn, K, factors):
        y = trn["y"].values; base = float(np.median(y)); eff = {f: {} for f in factors}; pred = np.full(len(y), base)
        for _ in range(6):
            for f in factors:
                cur = trn[f].map(eff[f]).fillna(0).values; r = y - (pred - cur); new = {}
                for k, idx in trn.groupby(f).indices.items():
                    n = len(idx); new[k] = float(np.median(r[idx])) * n / (n + K[f])
                eff[f] = new; pred = pred - cur + trn[f].map(new).fillna(0).values
        return base, eff
    def pred(model, te, factors):
        base, eff = model; p = np.full(len(te), base)
        for f in factors: p = p + te[f].map(eff[f]).fillna(0).values
        return p
    K0 = dict(ownb=40, region2=60, size=60, fpos=40, mxc=60, season=120, trend=60)
    cv("보정 전체 요인(k 기본)", lambda trn, te: pred(fit(trn, K0, FACT), te, FACT))
    for drop in FACT:
        F = [f for f in FACT if f != drop]
        cv(f"  − {drop} 뺀 것", lambda trn, te, F=F: pred(fit(trn, K0, F), te, F))
    bestK = dict(K0)
    for f in FACT:
        cand = []
        for k in (10, 30, 60, 120, 300):
            K = dict(bestK); K[f] = k
            cand.append((cv("", lambda trn, te, K=K: pred(fit(trn, K, FACT), te, FACT), verbose=False), k))
        cand.sort(); bestK[f] = cand[0][1]
    print("  조정한 k:", bestK)
    final = lambda trn, te: pred(fit(trn, bestK, FACT), te, FACT)
    cv("보정표(k 조정)", final)
    # 최종 보정표(전체 데이터로 학습)
    model = fit(D, bestK, FACT)
    out = {"base": round(model[0], 4), "eff": {f: {k: round(v, 4) for k, v in d.items()} for f, d in model[1].items()}, "n": int(len(D)), "K": bestK,
           "quant": {"q3": q3, "q6": q6, "n3": n3m, "n6": n6m}, "generatedAt": datetime.now().isoformat()}
    print("\n=== 최종 보정표 JSON ===")
    print(json.dumps(out, ensure_ascii=False))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("## 예상매도가 보정표\n\n```\n" + json.dumps(out, ensure_ascii=False, indent=1) + "\n```\n")


if __name__ == "__main__":
    main()
