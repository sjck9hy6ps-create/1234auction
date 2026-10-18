"""
🔬 시군구 낙찰가율 추세가 아파트 예상매도가의 오차(실제÷예상)를 설명하나 (2026-10-18, 사용자: 낙찰가율 조사도 진행)
낙찰가율 = 매각가 ÷ 감정가(낙찰사례, 아파트). 감정가는 입찰 몇 달 전 시세라서 낙찰가율이 오르면 시세가 오르는 중, 내리면 내리는 중이라는 신호로 볼 수 있음.
 특징(시험 거래 달 직전 달까지의 낙찰사례만 사용):
  f1 = 최근 3개월 중위 낙찰가율 - 그 전 3개월 중위(변화) / f2 = 최근 3개월 중위 - 최근 12개월 중위(수준 차이) (각 구간 6건 이상일 때)
 기준 예상값 V0 = 현재 규칙(6개월 반감 2개월 가중 중위값, 6개월 3건 이상)
 확인: 특징 구간별 (실제÷예상 - 1) 중앙값, 교차검증으로 특징 구간별 보정을 했을 때 오차·치우침 변화
"""
import os, importlib.util
import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ab", os.path.join(HERE, "analyze-bidcases.py"))
ab = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ab)
avm = ab.avm
SITE = ab.SITE_URL
rng = np.random.default_rng(4)
MAX_TEST = int(os.environ.get("MAX_TEST", "40000"))


def cls_of(region):
    s = str(region or "").split(" ")[0]
    if s.startswith("서울"): return "서울"
    if s[:2] in ("경기", "인천"): return "경기·인천"
    return "지방"


def wmed(vals, w):
    o = np.argsort(vals); v = np.asarray(vals)[o]; ww = np.asarray(w)[o]
    c = (np.cumsum(ww) - 0.5 * ww) / ww.sum()
    return float(np.interp(0.5, c, v))


def main():
    cases = pd.DataFrame(requests.get(f"{SITE}/api/auction?kind=bidCases", timeout=240).json())
    cases = cases[cases["propertyType"].astype(str).str.contains("아파트", na=False)].copy()
    cases["final"] = pd.to_numeric(cases["finalBidPrice"], errors="coerce"); cases["appr"] = pd.to_numeric(cases["appraisalPrice"], errors="coerce")
    cases = cases[(cases["final"] > 0) & (cases["appr"] > 0) & cases["saleDate"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)].copy()
    cases["rate"] = cases["final"] / cases["appr"]
    cases = cases[(cases["rate"] > 0.3) & (cases["rate"] < 1.6)]
    cases["rg"] = cases["addrJibun"].map(ab.region_norm); cases = cases.dropna(subset=["rg"])
    d = pd.to_datetime(cases["saleDate"], errors="coerce"); cases["ym"] = (d.dt.year * 12 + d.dt.month).astype("Int64")
    cases = cases.dropna(subset=["ym"]); cases["ym"] = cases["ym"].astype(int)
    print(f"  낙찰사례(아파트·매각가·감정가 있음) {len(cases):,}건, 시군구 {cases['rg'].nunique():,}곳, 기간 {int(cases['ym'].min())}~{int(cases['ym'].max())}(년*12+월)")
    rate_by = {k: g[["ym", "rate"]].values for k, g in cases.groupby("rg")}
    feat_cache = {}

    def feat(rg, ym0):
        k = (rg, ym0)
        if k in feat_cache: return feat_cache[k]
        a = rate_by.get(rg)
        out = (np.nan, np.nan)
        if a is not None:
            y = a[:, 0]; r = a[:, 1]
            n3 = r[(y >= ym0 - 3) & (y <= ym0 - 1)]; p3 = r[(y >= ym0 - 6) & (y <= ym0 - 4)]; y12 = r[(y >= ym0 - 12) & (y <= ym0 - 1)]
            if len(n3) >= 6 and len(p3) >= 6: f1 = float(np.median(n3) - np.median(p3))
            else: f1 = np.nan
            f2 = float(np.median(n3) - np.median(y12)) if len(n3) >= 6 and len(y12) >= 15 else np.nan
            out = (f1, f2)
        feat_cache[k] = out; return out

    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,price,size,deal_date,dealing_type,cdeal_type", extra_filter="&deal_date=gte.20230101")
    if "cdeal_type" in tr.columns: tr = tr[tr["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    for c in ("price", "size", "deal_date"): tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"]); tr = tr[(tr["price"] > 0) & (tr["size"] > 10) & (tr["dealing_type"] != "직거래")]
    tr["dk"] = tr["dong"].map(ab.dong_key); tr["rg"] = tr["region"].map(ab.region_norm); tr["bj"] = tr["bunji"].astype(str).str.strip()
    tr["ts"] = pd.to_datetime(tr["deal_date"].astype(int).astype(str), format="%Y%m%d", errors="coerce"); tr = tr.dropna(subset=["ts", "rg"])
    tr["t"] = (tr["ts"] - pd.Timestamp("2000-01-01")).dt.days.astype(float)
    tr["ym"] = (tr["ts"].dt.year * 12 + tr["ts"].dt.month).astype(int)
    tr["cls"] = tr["region"].map(cls_of)
    print(f"  거래 {len(tr):,}건")
    groups = {k: g.sort_values("t").reset_index(drop=True) for k, g in tr.groupby(["rg", "dk", "bj"])}
    t_start = (pd.Timestamp("2025-01-01") - pd.Timestamp("2000-01-01")).days
    test = []
    for k, g in groups.items():
        if k[0] not in rate_by: continue
        for i in np.where(g["t"].values >= t_start)[0]: test.append((k, i))
    print(f"  낙찰가율 자료가 있는 시군구의 시험 후보 {len(test):,}건")
    sel = rng.choice(len(test), min(len(test), MAX_TEST * 2), replace=False); test = [test[i] for i in sel]
    rows = []
    for k, i in test:
        if len(rows) >= MAX_TEST: break
        g = groups[k]; T = g.iloc[i]; H = g.iloc[:i]; H = H[H["t"] < T["t"]]
        sm = H[(H["size"] - T["size"]).abs() <= 3]
        if not len(sm): continue
        age = (T["t"] - sm["t"].values) / 30.4; m6 = age <= 6
        if m6.sum() < 3: continue
        v0 = wmed(sm["price"].values[m6].astype(float), 0.5 ** (age[m6] / 2.0))
        f1, f2 = feat(k[0], int(T["ym"]))
        rows.append(dict(cls=T["cls"], rg=k[0], ym=int(T["ym"]), actual=float(T["price"]), V0=v0, f1=f1, f2=f2))
    D = pd.DataFrame(rows)
    D.to_json("backtest-sale-auction.json", orient="records", force_ascii=False)
    print(f"  시험 {len(D):,}건 (f1 있음 {D.f1.notna().sum():,}, f2 있음 {D.f2.notna().sum():,})")
    report(D)


def report(D):
    D["r"] = D["actual"] / D["V0"] - 1
    for feat_name, bins, lab in (("f1", [-9, -0.03, 0.03, 9], ["낙찰가율 하락(-3%p↓)", "보합", "상승(+3%p↑)"]), ("f2", [-9, -0.03, 0.03, 9], ["최근이 연평균보다 낮음", "비슷", "높음"])):
        X = D[D[feat_name].notna()].copy()
        if len(X) < 500: continue
        X["g"] = pd.cut(X[feat_name], bins, labels=lab)
        for cls in ("지방", "서울", "경기·인천", None):
            d0 = X if cls is None else X[X.cls == cls]
            if len(d0) < 400: continue
            print(f"\n[{feat_name} · {cls or '전국'}] n{len(d0):,}")
            for g in lab:
                d = d0[d0.g == g]
                if len(d) < 100: continue
                r = d["r"]
                print(f"   {g:14} n{len(d):6,} 실제÷예상-1 중앙 {np.median(r) * 100:+6.2f}% | 오차 {np.median(np.abs(r)) * 100:5.2f}% | 하방p10 {r.quantile(.1) * 100:+6.1f}%")
            # 교차검증 보정
            d0 = d0.copy(); d0["fold"] = rng.integers(0, 2, len(d0)); outs = []
            for f in (0, 1):
                trn = d0[d0.fold != f]; te = d0[d0.fold == f].copy()
                b = trn.groupby("g", observed=True)["r"].median().rename("b"); te = te.join(b, on="g"); te["b"] = te["b"].fillna(0); outs.append(te)
            T = pd.concat(outs)
            print(f"   교차검증 보정 후: 오차 {np.median(np.abs(T.r)) * 100:.2f}% → {np.median(np.abs(T.r - T.b)) * 100:.2f}% | 치우침 {np.median(T.r) * 100:+.2f}% → {np.median(T.r - T.b) * 100:+.2f}%")
    # 상관(스피어만)
    for f in ("f1", "f2"):
        for cls in ("지방", "서울", "경기·인천"):
            d = D[(D.cls == cls) & D[f].notna()]
            if len(d) > 500: print(f"  순위상관 {f} · {cls}: {d[f].corr(d['r'], method='spearman'):+.3f} (n{len(d):,})")


if __name__ == "__main__":
    main()
