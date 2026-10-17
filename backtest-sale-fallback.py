"""
🔬 최근 6개월 같은 평형 거래가 3건 미만일 때의 예상매도가 추론 규칙 비교 (2026-10-17, 사용자: "6개월 이전 거래·단지 내 다른 평형·생활권 거래로 보수적으로 추론, 모든 배지에 적용")
방법: 2025년 이후 각 거래(정답)에 대해 직전 정보만 써서 단계별 추정을 만들고 오차·치우침·하방 분위를 봄. 대상 = 직전 6개월 같은 단지·같은 평형(±3㎡) 중개거래가 3건 미만인 거래.
 단계 T2: 같은 단지·같은 평형, 6~36개월 전 거래를 시군구 시세지수로 지금 시점에 맞춰 보정한 중위값
 단계 T3: 같은 단지·다른 평형, 최근 12개월 ㎡당 가격(시점 보정) × 이 평형(㎡) (평형 탄력성은 데이터로 추정)
 단계 T4: 같은 법정동 다른 단지의 같은 평형 최근 6개월 ㎡당 가격 × 이 단지의 상대 가격 수준(이 단지 36개월 ÷ 동 36개월, 시점 보정)
 단계 T5: 같은 동 전체 최근 12개월 ㎡당 가격(시점 보정) × 평형 × 상대 수준(없으면 1)
결과는 로그로 출력.
"""
import os, re, math, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ab", os.path.join(HERE, "analyze-bidcases.py"))
ab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ab)
avm = ab.avm
rng = np.random.default_rng(11)
MAX_TEST = int(os.environ.get("MAX_TEST", "20000"))


def cls_of(region):
    s = str(region or "").split(" ")[0]
    if s.startswith("서울"): return "서울"
    if s[:2] in ("경기", "인천"): return "경기·인천"
    return "지방"


def main():
    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,cdeal_type", extra_filter="&deal_date=gte.20220101")
    if "cdeal_type" in tr.columns: tr = tr[tr["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    for c in ("price", "size", "deal_date"): tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"]); tr = tr[(tr["price"] > 0) & (tr["size"] > 10) & (tr["dealing_type"] != "직거래")]
    tr["dk"] = tr["dong"].map(ab.dong_key); tr["rg"] = tr["region"].map(ab.region_norm); tr["bj"] = tr["bunji"].astype(str).str.strip()
    tr["ts"] = pd.to_datetime(tr["deal_date"].astype(int).astype(str), format="%Y%m%d", errors="coerce"); tr = tr.dropna(subset=["ts", "rg"])
    tr["t"] = (tr["ts"] - pd.Timestamp("2000-01-01")).dt.days.astype(float)
    tr["ym"] = (tr["ts"].dt.year * 12 + tr["ts"].dt.month).astype(int)
    tr["ppm"] = tr["price"] / tr["size"]
    tr["cls"] = tr["region"].map(cls_of)
    print(f"  거래 {len(tr):,}건")

    # 시군구 월별 ㎡당 가격 중위값 → 후행 3개월 지수
    mon = tr.groupby(["rg", "ym"])["ppm"].agg(["median", "count"]).reset_index()
    mon_d = {r: g.set_index("ym") for r, g in mon.groupby("rg")}
    tr_by_rg_ym = {}
    for (r, ym), g in tr.groupby(["rg", "ym"]): tr_by_rg_ym[(r, ym)] = g["ppm"].values

    idx_cache = {}
    def idx(rg, ym):
        k = (rg, ym)
        if k in idx_cache: return idx_cache[k]
        vals = []
        for m in (ym - 2, ym - 1, ym):
            v = tr_by_rg_ym.get((rg, m))
            if v is not None: vals.append(v)
        out = float(np.median(np.concatenate(vals))) if vals and sum(len(v) for v in vals) >= 8 else None
        idx_cache[k] = out; return out

    groups = {k: g.sort_values("t").reset_index(drop=True) for k, g in tr.groupby(["rg", "dk", "bj"])}
    dong_groups = {k: g.sort_values("t").reset_index(drop=True) for k, g in tr.groupby(["rg", "dk"])}
    t_start = (pd.Timestamp("2025-01-01") - pd.Timestamp("2000-01-01")).days
    rows = []
    for cls in ("서울", "경기·인천", "지방"):
        keys = [k for k, g in groups.items() if g["cls"].iloc[0] == cls]
        test = []
        for k in keys:
            g = groups[k]
            for i in np.where(g["t"].values >= t_start)[0]: test.append((k, i))
        sel = rng.choice(len(test), min(len(test), MAX_TEST * 3), replace=False); test = [test[i] for i in sel]
        got = 0
        for k, i in test:
            if got >= MAX_TEST: break
            g = groups[k]; T = g.iloc[i]; H = g.iloc[:i]; H = H[H["t"] < T["t"]]
            same = H[(H["size"] - T["size"]).abs() <= 3]
            age = (T["t"] - same["t"].values) / 30.4
            if (age <= 6).sum() >= 3: continue   # 규칙 1(최근 거래 충분)이 처리하는 경우는 제외
            rg, ym0 = k[0], int(T["ym"]); i0 = idx(rg, ym0 - 1)
            if not i0: continue
            got += 1
            def adj(frame):  # 거래들을 지금 시점으로 시점 보정한 ㎡당 가격 배열
                out = []
                for ppm, ym in zip(frame["ppm"].values, frame["ym"].values):
                    ii = idx(rg, int(ym))
                    out.append(ppm * i0 / ii if ii else np.nan)
                return np.array(out)
            rec = dict(cls=cls, actual=float(T["price"]), n6=int((age <= 6).sum()), nsame=len(same))
            # T2
            s2 = same[(age > 6) & (age <= 36)]
            if len(s2) >= 1:
                a2 = adj(s2); a2 = a2[~np.isnan(a2)] * float(T["size"])
                if len(a2): rec["T2"] = float(np.median(a2[-5:] if False else a2)); rec["T2n"] = len(a2)
            # T2 최근가중 (반감 6개월)
            if len(s2) >= 1:
                a2 = adj(s2) * float(T["size"]); w = 0.5 ** ((T["t"] - s2["t"].values) / 30.4 / 6.0); ok = ~np.isnan(a2)
                if ok.any(): rec["T2w"] = float(np.average(a2[ok], weights=w[ok]))
            # T3
            other = H[(H["size"] - T["size"]).abs() > 3]
            o12 = other[(T["t"] - other["t"].values) / 30.4 <= 12]
            if len(o12) >= 2:
                a3 = adj(o12); ok = ~np.isnan(a3)
                if ok.sum() >= 2:
                    rec["T3raw"] = float(np.median(a3[ok])) * float(T["size"]); rec["T3n"] = int(ok.sum())
                    rec["T3dsz"] = float(np.log(T["size"] / np.median(o12["size"].values[ok])))
            # T4 / T5
            D = dong_groups.get((rg, k[1]))
            if D is not None:
                Dh = D[(D["t"] < T["t"])]
                d6 = Dh[((T["t"] - Dh["t"].values) / 30.4 <= 6) & ((Dh["size"] - T["size"]).abs() <= 3) & (Dh["bj"] != k[2])]
                d36 = Dh[((T["t"] - Dh["t"].values) / 30.4 <= 36)]
                o36 = d36[d36["bj"] == k[2]]
                cf = None
                if len(o36) >= 3 and len(d36) >= 30:
                    ao = adj(o36); ad = adj(d36[d36["bj"] != k[2]])
                    ao = ao[~np.isnan(ao)]; ad = ad[~np.isnan(ad)]
                    if len(ao) >= 3 and len(ad) >= 20: cf = float(np.median(ao) / np.median(ad))
                if len(d6) >= 3:
                    a4 = adj(d6); a4 = a4[~np.isnan(a4)]
                    if len(a4) >= 3:
                        rec["T4"] = float(np.median(a4)) * float(T["size"]) * (cf if cf else 1.0); rec["T4n"] = len(a4); rec["T4cf"] = cf is not None
                d12 = Dh[((T["t"] - Dh["t"].values) / 30.4 <= 12) & (Dh["bj"] != k[2])]
                if len(d12) >= 10:
                    a5 = adj(d12); a5 = a5[~np.isnan(a5)]
                    if len(a5) >= 10: rec["T5"] = float(np.median(a5)) * float(T["size"]) * (cf if cf else 1.0); rec["T5cf"] = cf is not None
            rows.append(rec)
        print(f"  {cls}: 6개월 거래 3건 미만 시험 {got:,}건")
    D = pd.DataFrame(rows)
    D.to_json("backtest-sale-fallback.json", orient="records", force_ascii=False)
    report(D)


def stat(d, c):
    x = d[d[c].notna()]
    if len(x) < 50: return None
    r = x["actual"] / x[c]
    return f"n{len(x):6,} 오차{np.median(np.abs(r - 1)) * 100:5.1f}% 치우침{(np.median(r) - 1) * 100:+6.1f}% 하방p10 {(r.quantile(.10) - 1) * 100:+6.1f}% p25 {(r.quantile(.25) - 1) * 100:+6.1f}%"


def report(D):
    # 평형 탄력성(T3): log(실제/T3raw) ~ a·log(평형/기준평형)
    X = D[D["T3raw"].notna()] if "T3raw" in D.columns else D.iloc[0:0]
    if len(X) > 200:
        y = np.log(X["actual"] / X["T3raw"]); xv = X["T3dsz"]
        e = float(np.polyfit(xv, y, 1)[0]); print(f"\nT3 평형 탄력성(㎡당 가격이 평형이 클수록 변하는 정도) 추정 기울기 {e:+.3f}")
        D["T3"] = X["T3raw"] * np.exp(e * X["T3dsz"])
    for cls in ("서울", "경기·인천", "지방", None):
        d = D if cls is None else D[D.cls == cls]
        print(f"\n[{cls or '전체'}] 6개월 3건 미만 시험 {len(d):,}건 (같은 평형 6개월 밖 거래 있음 {(d.get('T2n', pd.Series(dtype=float)).notna().mean() * 100):.0f}%)")
        for c in ("T2", "T2w", "T3", "T4", "T5"):
            if c in d.columns:
                s = stat(d, c)
                if s: print(f"   {c:4} {s}")
    # 우선순위 조합: T2(≥2건) → T3 → T4(상대수준 있음) → T5
    def pick(r):
        if r.get("T2n", 0) >= 2 and pd.notna(r.get("T2w")): return r["T2w"], "T2"
        if pd.notna(r.get("T3")): return r["T3"], "T3"
        if pd.notna(r.get("T4")): return r["T4"], "T4"
        if pd.notna(r.get("T5")): return r["T5"], "T5"
        if pd.notna(r.get("T2w")): return r["T2w"], "T2(1건)"
        return np.nan, None
    pk = D.apply(lambda r: pd.Series(pick(r), index=["est", "tier"]), axis=1)
    D["est"] = pk["est"]; D["tier"] = pk["tier"]
    print("\n==== 우선순위 조합 (T2≥2건 → T3 → T4 → T5 → T2 1건) ====")
    for cls in ("서울", "경기·인천", "지방", None):
        d = D if cls is None else D[D.cls == cls]
        print(f"\n[{cls or '전체'}] 추정 가능 {d.est.notna().mean() * 100:.0f}%")
        s = stat(d, "est")
        if s: print("   조합   ", s)
        for t in ("T2", "T3", "T4", "T5", "T2(1건)"):
            dd = d[d.tier == t]
            if len(dd) >= 50:
                r = dd["actual"] / dd["est"]
                print(f"   └ {t:6} n{len(dd):6,} 오차{np.median(np.abs(r - 1)) * 100:5.1f}% 치우침{(np.median(r) - 1) * 100:+6.1f}% 하방p10 {(r.quantile(.10) - 1) * 100:+6.1f}% p25 {(r.quantile(.25) - 1) * 100:+6.1f}% p75 {(r.quantile(.75) - 1) * 100:+6.1f}%")


if __name__ == "__main__":
    main()
