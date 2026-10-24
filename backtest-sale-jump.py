"""
🔬 최근 거래가 이전 거래보다 크게 높을 때(예: 목포 20.7평 - 최근 2.2억, 이전 1.8억대) 예상매도가를 어떻게 잡아야 정확한가 (2026-10-24, 사용자: 이 사건 실거래가는 최근 2.2억인데 예상매도가가 1.8억)
대상: 최근 6개월 같은 평형(±3㎡) 중개거래가 1~2건(앱이 '12개월 가중 중위값'을 쓰는 구간) + 비교로 3건+ 구간. 2025년~ 거래를 정답으로, 직전 정보만 사용.
 V0  현재: 12개월 원값, 반감 3개월 가중 중위값
 L   가장 최근 거래가 그대로
 B50 V0와 최근 거래의 평균(최근 거래가 V0보다 높을 때만 - 점프 규칙)
 NF  비슷한 층(±3층) 거래에 비중 3배를 준 가중 중위값
 H15 반감 1.5개월 가중 중위값(최근 쪽을 더 믿음)
 NFL 비슷한 층 거래 중 가장 최근 거래
최근 거래 ÷ V0(점프 비율) 구간별로 각 방식의 오차·치우침을 봄.
"""
import os, json, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ab", os.path.join(HERE, "analyze-bidcases.py"))
ab = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ab)
avm = ab.avm
rng = np.random.default_rng(5)
MAX_TEST = int(os.environ.get("MAX_TEST", "60000"))


def cls_of(region):
    s = str(region or "").split(" ")[0]
    if s.startswith("서울"): return "서울"
    if s[:2] in ("경기", "인천"): return "경기·인천"
    return "지방"


def wmed(v, w):
    o = np.argsort(v); v = np.asarray(v, dtype=float)[o]; w = np.asarray(w, dtype=float)[o]
    c = (np.cumsum(w) - 0.5 * w) / w.sum()
    return float(np.interp(0.5, c, v))


def main():
    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,floor,deal_date,dealing_type,cdeal_type", extra_filter="&deal_date=gte.20230101")
    if "cdeal_type" in tr.columns: tr = tr[tr["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    for c in ("price", "size", "floor", "deal_date"): tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"]); tr = tr[(tr["price"] > 0) & (tr["size"] > 10) & (tr["dealing_type"] != "직거래")]
    tr["dk"] = tr["dong"].map(ab.dong_key); tr["rg"] = tr["region"].map(ab.region_norm); tr["dj"] = tr["danji"].astype(str).str.strip()
    tr["ts"] = pd.to_datetime(tr["deal_date"].astype(int).astype(str), format="%Y%m%d", errors="coerce"); tr = tr.dropna(subset=["ts", "rg"])
    tr["t"] = (tr["ts"] - pd.Timestamp("2000-01-01")).dt.days.astype(float); tr["cls"] = tr["region"].map(cls_of)
    print(f"  거래 {len(tr):,}건")
    groups = {k: g.sort_values("t").reset_index(drop=True) for k, g in tr.groupby(["rg", "dk", "dj"])}
    t_start = (pd.Timestamp("2025-01-01") - pd.Timestamp("2000-01-01")).days
    test = []
    for k, g in groups.items():
        for i in np.where(g["t"].values >= t_start)[0]: test.append((k, i))
    sel = rng.choice(len(test), min(len(test), MAX_TEST * 2), replace=False); test = [test[i] for i in sel]
    rows = []
    for k, i in test:
        if len(rows) >= MAX_TEST: break
        g = groups[k]; T = g.iloc[i]; H = g.iloc[:i]; H = H[H["t"] < T["t"]]
        sz = float(T["size"]); same = H[(H["size"] - sz).abs() <= 3]
        age = (T["t"] - same["t"].values) / 30.4; m6 = age <= 6; n6 = int(m6.sum())
        if n6 < 1: continue
        m12 = age <= 12
        p = same["price"].values.astype(float); fl = same["floor"].values.astype(float)
        V0 = wmed(p[m12], 0.5 ** (age[m12] / 3.0))
        o = np.argsort(age); lat = float(p[o[0]]); lat_fl = fl[o[0]]
        rec = dict(cls=T["cls"], n6=n6, actual=float(T["price"]), V0=V0, L=lat, jump=lat / V0 - 1)
        rec["B50"] = (V0 + lat) / 2 if lat > V0 else V0
        tf = T["floor"]
        if pd.notna(tf):
            w = 0.5 ** (age[m12] / 3.0) * np.where(np.abs(fl[m12] - tf) <= 3, 3.0, 1.0); rec["NF"] = wmed(p[m12], w)
            near = np.abs(fl - tf) <= 3
            if near.any(): rec["NFL"] = float(p[np.where(near)[0][np.argsort(age[near])[0]]])
        rec["H15"] = wmed(p[m12], 0.5 ** (age[m12] / 1.5))
        rows.append(rec)
    D = pd.DataFrame(rows); D.to_json("backtest-sale-jump.json", orient="records", force_ascii=False)
    print(f"  시험 {len(D):,}건")
    report(D)


def line(d, c):
    x = d[d[c].notna()]
    if len(x) < 50: return None
    r = x["actual"] / x[c] - 1
    return f"n{len(x):6,} 오차 {np.median(np.abs(r)) * 100:5.2f}% 치우침 {np.median(r) * 100:+6.2f}% 10%초과 {(np.abs(r) > .1).mean() * 100:4.1f}%"


def report(D):
    V = ["V0", "L", "B50", "NF", "H15", "NFL"]
    NM = {"V0": "현재(12개월 가중 중위값)", "L": "최근 거래 그대로", "B50": "점프 규칙(최근>V0이면 평균)", "NF": "비슷한 층 3배 가중", "H15": "반감 1.5개월", "NFL": "비슷한 층 최근 거래"}
    for cls in ("전체", "지방", "경기·인천", "서울"):
        d0 = D if cls == "전체" else D[D.cls == cls]
        for nm, m in (("6개월 1~2건", d0.n6 <= 2), ("6개월 3건+", d0.n6 >= 3)):
            d = d0[m]
            if len(d) < 300: continue
            print(f"\n===== {cls} · {nm} · n{len(d):,} =====")
            for c in V:
                s = line(d, c)
                if s: print(f"  {NM[c]:26} {s}")
            print("  -- 최근 거래 ÷ 현재 예상 - 1 (점프) 구간별")
            for lo, hi, lab in ((-9, -0.10, "최근이 10%↓"), (-0.10, 0.10, "비슷(±10%)"), (0.10, 0.20, "최근이 10~20%↑"), (0.20, 9, "최근이 20%↑")):
                dd = d[(d.jump > lo) & (d.jump <= hi)]
                if len(dd) < 80: continue
                print(f"   [{lab}] n{len(dd):,}")
                for c in ("V0", "L", "B50", "NF", "NFL"):
                    s = line(dd, c)
                    if s: print(f"      {NM[c]:26} {s}")


if __name__ == "__main__":
    main()
