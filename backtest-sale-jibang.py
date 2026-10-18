"""
🔬 지방 아파트 예상매도가 개선 방법 비교 (2026-10-18, 사용자: "지방의 경우 실거래와 더 가까이 갈 수 있는 방법 / 지방 시장 상황을 고려")
정답 = 시험 거래의 실제 가격, 직전 정보(같은 단지·같은 평형 ±3㎡ 중개거래)만 사용. 대상: 2025년~ 지방 거래 중 직전 6개월 같은 평형 3건 이상(현재 규칙 적용 구간) / 3건 미만(추론 구간) 따로.
 V0 현재: 6개월, 반감 2개월 가중 중위값(시세 보정 없음)
 V1: 12개월 거래를 시군구 ㎡당 시세 지수로 지금 시점에 맞춘 뒤 반감 3개월 가중 중위값
 V2: 6개월 거래를 지수로 보정한 뒤 반감 2개월 가중 중위값
 V3: V0에서 중위값 대비 ±12%를 벗어난 거래를 빼고 다시 계산
 V4: V1 + 비슷한 층(±3층) 거래 비중 1.5배
 V5: V2 + 시군구 추세 반영(최근 3개월 지수 변화율의 절반을 더함, 상한 ±3%)
결과: 지역 시세 추세(하락·보합·상승) 구간별 오차·치우침도 같이 출력.
"""
import os, re, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ab", os.path.join(HERE, "analyze-bidcases.py"))
ab = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ab)
avm = ab.avm
rng = np.random.default_rng(5)
MAX_TEST = int(os.environ.get("MAX_TEST", "40000"))


def is_local(region):
    s = str(region or "").split(" ")[0]
    return not (s.startswith("서울") or s[:2] in ("경기", "인천"))


def wmed(vals, w):
    o = np.argsort(vals); v = np.asarray(vals)[o]; ww = np.asarray(w)[o]
    c = (np.cumsum(ww) - 0.5 * ww) / ww.sum()
    return float(np.interp(0.5, c, v))


def main():
    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,cdeal_type", extra_filter="&deal_date=gte.20220101")
    if "cdeal_type" in tr.columns: tr = tr[tr["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    for c in ("price", "size", "floor", "deal_date"): tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"]); tr = tr[(tr["price"] > 0) & (tr["size"] > 10) & (tr["dealing_type"] != "직거래")]
    tr = tr[tr["region"].map(is_local)].copy()
    tr["dk"] = tr["dong"].map(ab.dong_key); tr["rg"] = tr["region"].map(ab.region_norm); tr["bj"] = tr["bunji"].astype(str).str.strip()
    tr["ts"] = pd.to_datetime(tr["deal_date"].astype(int).astype(str), format="%Y%m%d", errors="coerce"); tr = tr.dropna(subset=["ts", "rg"])
    tr["t"] = (tr["ts"] - pd.Timestamp("2000-01-01")).dt.days.astype(float)
    tr["ym"] = (tr["ts"].dt.year * 12 + tr["ts"].dt.month).astype(int)
    tr["ppm"] = tr["price"] / tr["size"]
    print(f"  지방 거래 {len(tr):,}건")

    by = {}
    for (r, ym), g in tr.groupby(["rg", "ym"]): by[(r, ym)] = g["ppm"].values
    cache = {}
    def idx(rg, ym):
        k = (rg, ym)
        if k in cache: return cache[k]
        v = [by[(rg, m)] for m in (ym - 2, ym - 1, ym) if (rg, m) in by]
        out = float(np.median(np.concatenate(v))) if v and sum(len(x) for x in v) >= 8 else None
        cache[k] = out; return out

    groups = {k: g.sort_values("t").reset_index(drop=True) for k, g in tr.groupby(["rg", "dk", "bj"])}
    t_start = (pd.Timestamp("2025-01-01") - pd.Timestamp("2000-01-01")).days
    test = []
    for k, g in groups.items():
        for i in np.where(g["t"].values >= t_start)[0]: test.append((k, i))
    sel = rng.choice(len(test), min(len(test), MAX_TEST * 2), replace=False); test = [test[i] for i in sel]
    print(f"  시험 후보 {len(test):,}건")
    rows = []
    for k, i in test:
        if len(rows) >= MAX_TEST: break
        g = groups[k]; T = g.iloc[i]; H = g.iloc[:i]; H = H[H["t"] < T["t"]]
        same = H[(H["size"] - T["size"]).abs() <= 3]
        if not len(same): continue
        rg, ym0 = k[0], int(T["ym"]); i0 = idx(rg, ym0 - 1)
        if not i0: continue
        age = (T["t"] - same["t"].values) / 30.4
        m6 = age <= 6; m12 = age <= 12
        n6 = int(m6.sum())
        if m12.sum() < 1: continue
        price = same["price"].values.astype(float); fl = same["floor"].values; ymv = same["ym"].values
        adj = np.array([i0 / idx(rg, int(y)) if idx(rg, int(y)) else np.nan for y in ymv])
        rec = dict(n6=n6, n12=int(m12.sum()), actual=float(T["price"]))
        # 추세: 시군구 지수 최근 3개월 변화
        i3 = idx(rg, ym0 - 4)
        rec["trend"] = (i0 / i3 - 1) if i3 else np.nan
        if n6 >= 1:
            rec["V0"] = wmed(price[m6], 0.5 ** (age[m6] / 2.0))
            p = price[m6]; med = np.median(p); keep = np.abs(p / med - 1) <= 0.12
            if keep.sum() >= 1: rec["V3"] = wmed(p[keep], 0.5 ** (age[m6][keep] / 2.0))
            ok = ~np.isnan(adj[m6])
            if ok.any():
                rec["V2"] = wmed(price[m6][ok] * adj[m6][ok], 0.5 ** (age[m6][ok] / 2.0))
                tf = np.clip(rec["trend"] * 0.5, -0.03, 0.03) if not np.isnan(rec["trend"]) else 0.0
                rec["V5"] = rec["V2"] * (1 + tf)
        ok12 = m12 & ~np.isnan(adj)
        if ok12.any():
            val = price[ok12] * adj[ok12]
            rec["V1"] = wmed(val, 0.5 ** (age[ok12] / 3.0))
            w = 0.5 ** (age[ok12] / 3.0)
            tfl = T["floor"]
            if not np.isnan(tfl):
                w = w * np.where(np.abs(fl[ok12] - tfl) <= 3, 1.5, 1.0)
            rec["V4"] = wmed(val, w)
        rows.append(rec)
    D = pd.DataFrame(rows)
    D.to_json("backtest-sale-jibang.json", orient="records", force_ascii=False)
    print(f"  시험 {len(D):,}건")
    report(D)


def line(d, c):
    x = d[d[c].notna()]
    if len(x) < 100: return None
    r = x["actual"] / x[c]
    return f"n{len(x):6,} 오차{np.median(np.abs(r - 1)) * 100:5.2f}% 치우침{(np.median(r) - 1) * 100:+6.2f}% 하방p10 {(r.quantile(.10) - 1) * 100:+6.1f}% p25 {(r.quantile(.25) - 1) * 100:+6.1f}%"


def report(D):
    V = ["V0", "V1", "V2", "V3", "V4", "V5"]
    D["tr"] = pd.cut(D["trend"], [-9, -0.03, 0.03, 9], labels=["하락(-3%↓)", "보합", "상승(+3%↑)"])
    for nm, m in (("직전 6개월 3건 이상(현재 규칙 구간)", D.n6 >= 3), ("6개월 1~2건", (D.n6 >= 1) & (D.n6 < 3))):
        d = D[m]
        print(f"\n===== {nm} n{len(d):,} =====")
        for c in V:
            s = line(d, c)
            if s: print(f"  {c} {s}")
        for t in ["하락(-3%↓)", "보합", "상승(+3%↑)"]:
            dd = d[d["tr"] == t]
            if len(dd) < 300: continue
            print(f"  -- 시세 추세 {t} n{len(dd):,}")
            for c in V:
                s = line(dd, c)
                if s: print(f"     {c} {s}")


if __name__ == "__main__":
    main()
