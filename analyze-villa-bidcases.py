"""
🏘️ 수도권 빌라 낙찰가 예측 모델 시험 (2026-10-10, 사용자가 빌라 낙찰사례 약 8,700건 업로드)
각 낙찰사례의 '낙찰 30일 전까지의 실거래'로 예상매도가(백테스트한 빌라 방식)를 구하고, 낙찰가÷예상매도가를 최저가÷예상매도가·유찰·지역·평형·층 등으로 설명하는
가산 모델(아파트와 같은 방식)을 만들어 최근 사례(학습에 안 쓴 구간)로 오차를 확인. 결과 JSON → 앱의 빌라 낙찰 가능성·추천가 근거
"""
import os, json, re, importlib.util
import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py"))
bv = importlib.util.module_from_spec(_s); _s.loader.exec_module(bv)
avm = bv.avm
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
SIDO = {"서울특별시": "서울", "서울": "서울", "인천광역시": "인천", "인천": "인천", "경기도": "경기", "경기": "경기"}


def trade_region(addr):
    t = str(addr or "").split()
    if len(t) < 2: return None
    sd = SIDO.get(t[0])
    if not sd: return None
    city = t[1]
    if len(t) >= 3 and city.endswith("시") and t[2].endswith("구"):
        return f"{sd} {city[:-1]} {t[2]}"
    return f"{sd} {city}"


def fails_from_ratio(minb, appr):
    if not appr or not minb or appr <= 0: return None
    r = minb / appr
    for k, lim in enumerate((0.9, 0.72, 0.58, 0.47, 0.38, 0.31, 0.25)):
        if r >= lim: return k
    return 6


def fit_additive(X, y, factors, iters=6):
    base = float(np.median(y)); eff = {f: {} for f, _ in factors}; pred = np.full(len(y), base)
    for _ in range(iters):
        for f, k in factors:
            cur = X[f].map(eff[f]).fillna(0).values; r = y - (pred - cur)
            g = pd.DataFrame({"k": X[f].values, "r": r}).groupby("k")["r"].agg(["median", "count"])
            new = (g["median"] * g["count"] / (g["count"] + k)).to_dict(); eff[f] = new
            pred = pred - cur + X[f].map(new).fillna(0).values
    return base, eff


def predict(m, X, factors):
    base, eff = m; p = np.full(len(X), base)
    for f, _ in factors: p = p + X[f].map(eff[f]).fillna(0).values
    return p


def main():
    flt = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.{bv.START}{flt}")
    df = bv.prep(raw)
    print(f"빌라 거래 {len(df):,}건")
    cases = pd.DataFrame(requests.get(f"{SITE}/api/auction?kind=bidCases", timeout=300).json())
    c = cases[cases["propertyType"].astype(str).str.contains("다세대|연립|도시형", na=False)].copy()
    c["actual"] = pd.to_numeric(c["finalBidPrice"], errors="coerce") / 10000.0
    c["minbid"] = pd.to_numeric(c["minBidPrice"], errors="coerce") / 10000.0
    c["appr"] = pd.to_numeric(c["appraisalPrice"], errors="coerce") / 10000.0
    c["area"] = pd.to_numeric(c["areaM2"], errors="coerce")
    c["fl"] = pd.to_numeric(c["floor"], errors="coerce")
    c["bidders"] = pd.to_numeric(c.get("bidders"), errors="coerce")
    c = c[(c["actual"] > 0) & (c["minbid"] > 0) & c["area"].between(15, 150) & c["saleDate"].astype(str).str.match(r"^\d{4}-\d\d-\d\d$", na=False)]
    c["region"] = c["addrJibun"].map(trade_region)
    c = c.dropna(subset=["region", "dong", "bunji"])
    c["dong"] = c["dong"].astype(str).str.strip().str.split().str[-1]
    c["bunji"] = c["bunji"].astype(str).str.strip()
    c["sale"] = c["saleDate"].str.replace("-", "").astype(int)
    c = c[c["sale"] >= 20220101]
    print(f"낙찰사례(수도권 빌라, 2022~) {len(c):,}건")
    regs = set(df["region"].unique()); c = c[c["region"].isin(regs)]
    print(f"거래 지역과 연결된 사례 {len(c):,}건")
    # 건물(번지) 단위 가장 흔한 준공연도
    byb = df.dropna(subset=["build_year"]).groupby(["region", "dong", "bunji"])["build_year"].agg(lambda s: s.mode().iloc[0]).to_dict()
    T = pd.DataFrame({"region": c["region"].values, "dong": c["dong"].values, "bunji": c["bunji"].values, "size": c["area"].values, "floor": c["fl"].values,
                      "price": c["actual"].values, "day": (pd.to_datetime(c["sale"].astype(str), format="%Y%m%d") - pd.Timestamp("2020-01-01")).dt.days.values})
    T["build_year"] = [byb.get((r, d, b), np.nan) for r, d, b in zip(T["region"], T["dong"], T["bunji"])]
    T["bld"] = T["region"] + "|" + T["dong"] + "|" + T["bunji"]; T["dk"] = T["region"] + "|" + T["dong"]
    T.index = c.index
    E = bv.estimate(df, T)
    E = E[(E["tadj"] == 0) & (E["q"] == 0.5)].set_index("i")
    D = c.join(E[["est", "lvl"]], how="inner")
    D["est"] = D["est"] / 1.0
    D = D[(D["est"] > 0)].copy()
    D["by"] = T["build_year"].reindex(D.index)
    D["ratio"] = D["actual"] / D["est"]
    D = D[D["ratio"].between(0.25, 1.8)]
    print(f"예상매도가 계산된 사례 {len(D):,}건  낙찰가÷예상매도가 중앙 {D['ratio'].median():.3f} (25% {D['ratio'].quantile(.25):.3f} ~ 75% {D['ratio'].quantile(.75):.3f})")
    D["fails"] = [fails_from_ratio(m, a) for m, a in zip(D["minbid"], D["appr"])]
    X = pd.DataFrame(index=D.index)
    X["lb"] = np.clip(np.floor(np.log(D["minbid"] / D["est"]) / 0.05), -24, 9).astype(int).astype(str)
    X["fails"] = D["fails"].map(lambda v: "?" if v is None or pd.isna(v) else str(min(int(v), 4)))
    X["region"] = D["region"].values
    X["dong"] = (D["region"] + "|" + D["dong"]).values
    X["size"] = D["area"].map(lambda a: "40↓" if a < 40 else ("40~60" if a < 60 else ("60~85" if a < 85 else "85↑"))).values
    X["floor"] = D["fl"].map(lambda f: "지하" if f <= 0 else ("1층" if f == 1 else ("2~3층" if f <= 3 else "4층+"))).values
    X["age"] = D["by"].map(lambda b: "?" if pd.isna(b) else ("~10년" if 2026 - b <= 10 else ("11~20" if 2026 - b <= 20 else ("21~30" if 2026 - b <= 30 else "31+")))).values
    X["lvl"] = D["lvl"].values
    X["season"] = D["sale"].map(lambda d: "겨울" if (d // 100) % 100 in (12, 1, 2) else ("봄" if (d // 100) % 100 <= 5 else ("여름" if (d // 100) % 100 <= 8 else "가을"))).values
    FAC = [("lb", 10), ("fails", 120), ("region", 120), ("size", 30), ("floor", 30), ("age", 60), ("lvl", 60), ("season", 300), ("dong", 40)]
    y = np.log(D["ratio"].values)
    cut = 20260601
    tr = (D["sale"] < cut).values; te = ~tr
    print(f"학습 {tr.sum():,} / 시험(2026-06~) {te.sum():,}")
    res = {}
    for name, fac in (("기본(최저가만)", [("lb", 10)]), ("+유찰·지역·평형·층", [("lb", 10), ("fails", 120), ("region", 120), ("size", 30), ("floor", 30)]), ("전체", FAC), ("전체−동", [f for f in FAC if f[0] != "dong"])):
        m = fit_additive(X[tr], y[tr], fac); p = predict(m, X[te], fac)
        pr = np.exp(p) * D["est"].values[te]; act = D["actual"].values[te]
        e = pr / act - 1
        res[name] = {"n": int(te.sum()), "medAbsErrPct": round(float(np.median(np.abs(e))) * 100, 2), "within10Pct": round(float((np.abs(e) <= .10).mean()) * 100, 1), "biasPct": round(float(np.median(e)) * 100, 2)}
        print(name, res[name])
    # 상수 비율 기준선
    base = np.exp(np.median(y[tr])) * D["est"].values[te]; e0 = base / D["actual"].values[te] - 1
    res["상수 비율(기준선)"] = {"medAbsErrPct": round(float(np.median(np.abs(e0))) * 100, 2), "within10Pct": round(float((np.abs(e0) <= .10).mean()) * 100, 1)}
    print("기준선:", res["상수 비율(기준선)"])
    # 단계별(예상매도가 근거)별 오차 - 전체 모델
    m = fit_additive(X[tr], y[tr], FAC); p = predict(m, X[te], FAC)
    pr = np.exp(p) * D["est"].values[te]; e = pr / D["actual"].values[te] - 1
    T2 = pd.DataFrame({"lvl": D["lvl"].values[te], "e": e, "age": X["age"].values[te], "fl": X["floor"].values[te]})
    bylvl = {k: {"n": int(len(G)), "medAbsErrPct": round(float(G["e"].abs().median()) * 100, 1), "within10Pct": round(float((G["e"].abs() <= .1).mean()) * 100, 1)} for k, G in T2.groupby("lvl") if len(G) >= 50}
    byage = {k: {"n": int(len(G)), "medAbsErrPct": round(float(G["e"].abs().median()) * 100, 1)} for k, G in T2.groupby("age") if len(G) >= 50}
    byfl = {k: {"n": int(len(G)), "medAbsErrPct": round(float(G["e"].abs().median()) * 100, 1)} for k, G in T2.groupby("fl") if len(G) >= 50}
    print("단계별:", json.dumps(bylvl, ensure_ascii=False)); print("연식별:", json.dumps(byage, ensure_ascii=False)); print("층별:", json.dumps(byfl, ensure_ascii=False))
    # 층별 낙찰가÷예상매도가 중앙값(원자료) - 층 효과가 낙찰가에서도 보이나
    flr = {k: {"n": int(len(G)), "ratioMed": round(float(G["ratio"].median()), 3)} for k, G in D.assign(fl2=X["floor"]).groupby("fl2") if len(G) >= 80}
    print("층별 낙찰가÷예상매도가:", json.dumps(flr, ensure_ascii=False))
    FIN = [f for f in FAC if f[0] != "dong"]   # 동 요인은 시험에서 개선이 없어 뺌
    mfin = fit_additive(X[tr], y[tr], FIN); pfin = predict(mfin, X[te], FIN)
    resid_q = [round(float(np.quantile(y[te] - pfin, q / 100)), 4) for q in range(1, 100)]
    full = fit_additive(X, y, FIN)
    FAC = FIN
    out = {"n": int(len(D)), "oos": res, "byLevel": bylvl, "byAge": byage, "byFloor": byfl, "floorRatio": flr, "ratioMed": round(float(D["ratio"].median()), 3), "resQ": resid_q,
           "factors": [f for f, _ in FIN], "base": full[0], "eff": {f: {str(k): round(float(v), 4) for k, v in d.items()} for f, d in full[1].items()}}
    json.dump(out, open("villa-winbid.json", "w"), ensure_ascii=False)
    print("저장 villa-winbid.json")


if __name__ == "__main__":
    main()
