"""
🔬 예상매도가 '종합 판단' 검증 (2026-10-19, 사용자: "같은 단지·같은 평형이 가장 우선이지만 다른 방식도 모두 통합 반영해야 예상매도가에 가까워진다")
지금 앱은 거래 건수에 따라 방식을 갈라 쓴다(6개월 3건+ → 최근거래 규칙 / 부족 → 이전거래·다른 평형 추론 ...). 이걸 하나로 합치면 더 정확한가를 본다.
 기준값(anchor) = 가장 우선인 근거: 같은 단지·같은 평형 최근 6개월(반감 가중 중위) → 없으면 6~36개월(지수 보정) → 없으면 다른 평형 → 없으면 같은 동 다른 단지
 보조 신호(모두 같은 값에 겹쳐 반영): S2 같은 평형 6~36개월 시점보정 / S3 같은 단지 다른 평형 ㎡당 × 평형 / S4 같은 동 다른 단지 같은 평형 × 이 단지 상대수준 / SJ 전세 보증금 × 과거 매매÷전세 / 추세(시군구 ㎡당 가격 3개월 변화)
 종합값 = anchor × exp(Σ w_k · log(S_k / anchor) + 추세 계수 · 추세), 가중치 w는 지역 × 최근 6개월 같은 평형 거래 수 구간별로 학습(2025년 시험분) → 2026년 시험분으로 평가(학습에 안 쓴 구간)
 비교: 'anchor만'(우선순위 단일 방식) vs '종합'. 오차 = |실제÷예상 − 1| 중앙값, 치우침, 하방 분위
"""
import os, re, json, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ab", os.path.join(HERE, "analyze-bidcases.py"))
ab = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ab)
avm = ab.avm
rng = np.random.default_rng(21)
MAX_TEST = int(os.environ.get("MAX_TEST", "20000"))
SIG = ["S2", "S3", "S4", "SJ"]


def cls_of(region):
    s = str(region or "").split(" ")[0]
    if s.startswith("서울"): return "서울"
    if s[:2] in ("경기", "인천"): return "경기·인천"
    return "지방"


def wmed(vals, w):
    o = np.argsort(vals); v = np.asarray(vals)[o]; ww = np.asarray(w)[o]
    c = (np.cumsum(ww) - 0.5 * ww) / ww.sum()
    return float(np.interp(0.5, c, v))


def bucket(n6):
    return "0" if n6 == 0 else ("1-2" if n6 < 3 else ("3-5" if n6 < 6 else "6+"))


def main():
    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,deal_date,dealing_type,cdeal_type", extra_filter="&deal_date=gte.20220101")
    if "cdeal_type" in tr.columns: tr = tr[tr["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    for c in ("price", "size", "deal_date"): tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"]); tr = tr[(tr["price"] > 0) & (tr["size"] > 10) & (tr["dealing_type"] != "직거래")]
    rt = avm.fetch_all_rows("house_rent", cols="region,dong,danji,deposit,monthly_rent,size,deal_date", extra_filter="&deal_date=gte.20211001")
    for c in ("deposit", "monthly_rent", "size", "deal_date"): rt[c] = pd.to_numeric(rt[c], errors="coerce")
    rt = rt.dropna(subset=["deposit", "size", "deal_date"]); rt = rt[(rt["monthly_rent"].fillna(0) == 0) & (rt["deposit"] > 0) & (rt["size"] > 10)]

    def prep(df):
        df["dk"] = df["dong"].map(ab.dong_key); df["rg"] = df["region"].map(ab.region_norm); df["dj"] = df["danji"].astype(str).str.strip()
        df["ts"] = pd.to_datetime(df["deal_date"].astype(int).astype(str), format="%Y%m%d", errors="coerce"); df = df.dropna(subset=["ts", "rg"])
        df["t"] = (df["ts"] - pd.Timestamp("2000-01-01")).dt.days.astype(float)
        df["ym"] = (df["ts"].dt.year * 12 + df["ts"].dt.month).astype(int)
        return df
    tr = prep(tr); rt = prep(rt)
    tr["ppm"] = tr["price"] / tr["size"]; tr["cls"] = tr["region"].map(cls_of)
    print(f"  매매 {len(tr):,}건 / 순수 전세 {len(rt):,}건")

    by = {}
    for (r, ym), g in tr.groupby(["rg", "ym"]): by[(r, ym)] = g["ppm"].values
    icache = {}

    def idx(rg, ym):
        k = (rg, ym)
        if k in icache: return icache[k]
        vals = [by[(rg, m)] for m in (ym - 2, ym - 1, ym) if (rg, m) in by]
        out = float(np.median(np.concatenate(vals))) if vals and sum(len(v) for v in vals) >= 8 else None
        icache[k] = out; return out

    groups = {k: g.sort_values("t").reset_index(drop=True) for k, g in tr.groupby(["rg", "dk", "dj"])}
    dong_g = {k: g.sort_values("t").reset_index(drop=True) for k, g in tr.groupby(["rg", "dk"])}
    rent_g = {k: (g["t"].values, g["size"].values, g["deposit"].values.astype(float)) for k, g in rt.sort_values("t").groupby(["rg", "dk", "dj"])}
    t_start = (pd.Timestamp("2025-01-01") - pd.Timestamp("2000-01-01")).days
    rows = []
    for cls in ("서울", "경기·인천", "지방"):
        test = []
        for k, g in groups.items():
            if g["cls"].iloc[0] != cls: continue
            for i in np.where(g["t"].values >= t_start)[0]: test.append((k, i))
        sel = rng.choice(len(test), min(len(test), MAX_TEST), replace=False); test = [test[i] for i in sel]
        print(f"  {cls}: 시험 후보 {len(test):,}건")
        for k, i in test:
            g = groups[k]; T = g.iloc[i]; H = g.iloc[:i]; H = H[H["t"] < T["t"]]
            rg, ym0 = k[0], int(T["ym"]); i0 = idx(rg, ym0 - 1)
            if not i0: continue
            sz = float(T["size"])
            adj = lambda fr: np.array([p * i0 / idx(rg, int(m)) if idx(rg, int(m)) else np.nan for p, m in zip(fr["ppm"].values, fr["ym"].values)])
            same = H[(H["size"] - sz).abs() <= 3]
            age = (T["t"] - same["t"].values) / 30.4
            m6 = age <= 6; n6 = int(m6.sum())
            rec = dict(cls=cls, n6=n6, actual=float(T["price"]), ts=T["ts"], ym=ym0)
            # 기준값
            if n6 >= 1:
                p = same["price"].values[m6].astype(float); a = age[m6]
                hl = 1.0 if cls == "경기·인천" else 2.0
                rec["A"] = float(np.median(p[np.argsort(a)[:3]])) if (cls == "서울" and n6 >= 3) else wmed(p, 0.5 ** (a / hl)); rec["Atype"] = "6m"
            # 보조 신호 S2: 같은 평형 6~36개월 시점 보정
            s2 = same[(age > 6) & (age <= 36)]
            if len(s2):
                v = adj(s2) * sz; w = 0.5 ** ((T["t"] - s2["t"].values) / 30.4 / 6.0); ok = ~np.isnan(v)
                if ok.any(): rec["S2"] = float(np.average(v[ok], weights=w[ok]))
            other = H[(H["size"] - sz).abs() > 3]
            o12 = other[(T["t"] - other["t"].values) / 30.4 <= 12]
            if len(o12) >= 2:
                v = adj(o12); ok = ~np.isnan(v)
                if ok.sum() >= 2: rec["S3"] = float(np.median(v[ok])) * sz
            D = dong_g.get((rg, k[1]))
            if D is not None:
                Dh = D[D["t"] < T["t"]]; Dh = Dh[Dh["dj"] != k[2]]
                d6 = Dh[((T["t"] - Dh["t"].values) / 30.4 <= 6) & ((Dh["size"] - sz).abs() <= 3)]
                if len(d6) >= 3:
                    v = adj(d6); v = v[~np.isnan(v)]
                    if len(v) >= 3:
                        cf = 1.0
                        h36 = H[(T["t"] - H["t"].values) / 30.4 <= 36]; d36 = Dh[(T["t"] - Dh["t"].values) / 30.4 <= 36]
                        if len(h36) >= 3 and len(d36) >= 20:
                            ao = adj(h36); ad = adj(d36); ao = ao[~np.isnan(ao)]; ad = ad[~np.isnan(ad)]
                            if len(ao) >= 3 and len(ad) >= 20: cf = float(np.median(ao) / np.median(ad))
                        rec["S4"] = float(np.median(v)) * sz * cf
            rg_ = rent_g.get(k)
            if rg_ is not None:
                rt_t, rt_s, rt_d = rg_
                keep = (np.abs(rt_s - sz) <= 3) & (rt_t < T["t"]); rag = (T["t"] - rt_t[keep]) / 30.4; rd = rt_d[keep]
                j6 = rd[rag <= 6]
                if len(j6) >= 2 and len(same):
                    ratios = []
                    for lo in (0, 6, 12, 18, 24):
                        ps = same["price"].values[(age > lo) & (age <= lo + 6)]; js = rd[(rag > lo + 0.0) & (rag <= lo + 6)] if lo else None
                        if lo == 0: continue
                        if len(ps) >= 1 and js is not None and len(js) >= 1: ratios.append(np.median(ps) / np.median(js))
                    if ratios: rec["SJ"] = float(np.median(j6)) * float(np.median(ratios))
            # 추세: 시군구 ㎡당 가격 3개월 변화
            i3 = idx(rg, ym0 - 4)
            rec["trend"] = float(np.log(i0 / i3)) if i3 else 0.0
            # 기준값이 없으면 우선순위로 채움
            if "A" not in rec:
                for kk in ("S2", "S3", "S4", "SJ"):
                    if kk in rec: rec["A"] = rec[kk]; rec["Atype"] = kk; break
            if "A" in rec: rows.append(rec)
    D = pd.DataFrame(rows)
    D["b"] = D["n6"].map(bucket)
    print(f"  시험 {len(D):,}건 (기준값 종류: {D['Atype'].value_counts().to_dict()})")
    report(D)


def design(d):
    X = []
    for kk in SIG:
        v = np.log(d[kk] / d["A"]) if kk in d else pd.Series(np.nan, index=d.index)
        v = v.where(~((d.get("Atype", "") == kk)), 0.0)  # 기준값이 이 신호 자체면 0
        X.append(v.fillna(0.0).clip(-0.5, 0.5).values)
    X.append(d["trend"].clip(-0.15, 0.15).values)
    return np.column_stack(X)


def fit(d, lam=0.5):
    X = design(d); y = np.log(d["actual"] / d["A"]).values
    X1 = np.column_stack([X, np.ones(len(X))])
    R = lam * len(X) / 100 * np.eye(X1.shape[1]); R[-1, -1] = 0
    return np.linalg.solve(X1.T @ X1 + R, X1.T @ y)


def pred(d, w):
    return d["A"].values * np.exp(np.column_stack([design(d), np.ones(len(d))]) @ w)


def stat(actual, est):
    r = actual / est - 1
    return f"n{len(r):6,} 오차{np.median(np.abs(r)) * 100:5.2f}% 치우침{np.median(r) * 100:+6.2f}% 하방p10 {np.quantile(r, .10) * 100:+6.1f}% 10%초과 {(np.abs(r) > .10).mean() * 100:4.1f}%"


def report(D):
    D.to_json("backtest-sale-blend.json", orient="records", force_ascii=False, date_format="iso")
    tr_ = D[D["ts"] < pd.Timestamp("2026-01-01")]; te = D[D["ts"] >= pd.Timestamp("2026-01-01")]
    print(f"\n학습(2025년) {len(tr_):,}건 → 평가(2026년) {len(te):,}건")
    weights = {}
    allp = []
    for cls in ("서울", "경기·인천", "지방"):
        for b in ("0", "1-2", "3-5", "6+"):
            a = tr_[(tr_.cls == cls) & (tr_.b == b)]; c = te[(te.cls == cls) & (te.b == b)]
            if len(a) < 200 or len(c) < 100: continue
            w = fit(a); weights[f"{cls}|{b}"] = [round(float(x), 4) for x in w]
            c = c.copy(); c["P"] = pred(c, w); allp.append(c)
            print(f"\n[{cls} · 6개월 같은 평형 {b}건] 계수 S2 {w[0]:+.2f} S3 {w[1]:+.2f} S4 {w[2]:+.2f} SJ {w[3]:+.2f} 추세 {w[4]:+.2f} 상수 {w[5]:+.3f}")
            print("   기준값만 ", stat(c["actual"].values, c["A"].values))
            print("   종합     ", stat(c["actual"].values, c["P"].values))
    if allp:
        P = pd.concat(allp)
        print("\n==== 전체(평가 2026) ====")
        print("   기준값만 ", stat(P["actual"].values, P["A"].values)); print("   종합     ", stat(P["actual"].values, P["P"].values))
        for cls in ("서울", "경기·인천", "지방"):
            q = P[P.cls == cls]
            if len(q): print(f"   {cls} 기준값만", stat(q["actual"].values, q["A"].values), "\n   {0} 종합   ".format(cls), stat(q["actual"].values, q["P"].values))
    json.dump(weights, open("backtest-sale-blend-weights.json", "w"), ensure_ascii=False)


if __name__ == "__main__":
    main()
