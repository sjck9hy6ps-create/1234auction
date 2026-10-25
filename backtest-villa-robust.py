"""
🏘️ 빌라 예상매도가를 튀는 가격에 견고하게 (2026-10-24, 사용자: 튀는 가격이 반영되면 큰 손실 - 가격 정확도는 견고해야 / 빌라는 반경 시세 변동으로 판단)
현재 방식(같은 건물 24개월 → 같은 동 12개월 → 시군구 12개월 ㎡당 가중 중앙값)을 그대로 두고, '하방 위험'(예상이 실제보다 높아 손해가 나는 쪽)을 중심으로 본다.
 ① 현재 방식의 하방 위험: 예상이 실제보다 10%·15% 넘게 높은 비율, 하위 10% 지점 - 단계별
 ② 견고화 후보: 40% 지점 / 튀는 거래 제외(중앙값의 0.8~1.25배 밖 제외) 후 중앙값
 ③ 불안정 신호별 하방 위험: 비교 거래의 흩어짐(IQR÷중앙값), 같은 건물 최근 거래가 예상과 8% 이상 어긋난 정도
정답 = 시험 거래의 실제 가격(2025년~), 직전 정보(30일 전까지)만 사용.
"""
import os, json, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py"))
bv = importlib.util.module_from_spec(_s); _s.loader.exec_module(bv)
avm = bv.avm
N_TEST = int(os.environ.get("N_TEST", "40000"))


def wq(vals, w, q):
    o = np.argsort(vals); v = vals[o]; ww = w[o]; c = np.cumsum(ww) / ww.sum()
    return float(v[min(np.searchsorted(c, q), len(v) - 1)])


def main():
    flt = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.{bv.START}{flt}")
    df = bv.prep(raw); print(f"  빌라 거래 {len(df):,}건")
    T = df[df["deal_date"] >= bv.TEST_FROM]
    if len(T) > N_TEST: T = T.sample(N_TEST, random_state=7)
    groups = {}
    for key_col in ("bld", "dk", "region"):
        groups[key_col] = {k: (G["day"].values, G["size"].values, G["ppm"].values, G["build_year"].values) for k, G in df.groupby(key_col)}

    def cands(key_col, key, day_c, days, size, tol, by=None, byy=None):
        t = groups[key_col].get(key)
        if t is None: return None
        d, sz, pp, yb = t
        hi = np.searchsorted(d, day_c, side="right"); lo = np.searchsorted(d, day_c - days, side="left")
        if hi <= lo: return None
        m = np.abs(sz[lo:hi] - size) <= tol
        if by is not None and byy is not None and np.isfinite(by): m &= (np.isnan(yb[lo:hi]) | (np.abs(yb[lo:hi] - by) <= byy))
        if not m.any(): return None
        ppm = pp[lo:hi][m]; age = day_c - d[lo:hi][m]
        w = np.exp(-age / 365.0) * np.exp(-np.abs(sz[lo:hi][m] - size) / 10.0)
        return ppm, w, age

    def trim(c):
        ppm, w, _ = c; med = wq(ppm, w, 0.5); k = (ppm >= 0.8 * med) & (ppm <= 1.25 * med)
        return (ppm[k], w[k]) if k.sum() >= 1 else (ppm, w)

    rows = []
    for r in T.itertuples():
        day_c = r.day - 30; by = r.build_year if np.isfinite(r.build_year) else None
        c1 = cands("bld", r.bld, day_c, 730, r.size, 6); c2 = cands("dk", r.dk, day_c, 365, r.size, 8, by, 5); c3 = cands("region", r.region, day_c, 365, r.size, 8)
        n1 = 0 if c1 is None else len(c1[0]); n2 = 0 if c2 is None else len(c2[0])

        def est_with(f):
            v1 = f(c1) if c1 else None; v2 = f(c2) if c2 else None; v3 = f(c3) if c3 else None
            if n1 >= 3: return v1, "건물3+"
            if n1 >= 1 and v2 is not None: return 0.5 * v1 + 0.5 * v2, "건물1~2+동"
            if n1 >= 1: return v1, "건물1~2"
            if n2 >= 5: return v2, "동5+"
            if v2 is not None: return 0.6 * v2 + 0.4 * (v3 if v3 else v2), "동1~4"
            if v3 is not None: return v3, "시군구"
            return None, "없음"
        p50, lvl = est_with(lambda c: wq(c[0], c[1], 0.5))
        if p50 is None: continue
        p40, _ = est_with(lambda c: wq(c[0], c[1], 0.4))
        ptr, _ = est_with(lambda c: (lambda t: wq(t[0], t[1], 0.5))(trim(c)))
        prim = c1 if n1 >= 1 else (c2 if c2 else c3)
        disp = (wq(prim[0], prim[1], 0.75) - wq(prim[0], prim[1], 0.25)) / max(wq(prim[0], prim[1], 0.5), 1e-9) if len(prim[0]) >= 3 else np.nan
        jump = np.nan
        if n1 >= 1:
            lat = c1[0][np.argmin(c1[2])]; jump = lat / wq(c1[0], c1[1], 0.5) - 1
        a = r.price
        rows.append({"lvl": lvl, "actual": a, "e50": p50 * r.size, "e40": p40 * r.size, "etr": ptr * r.size, "disp": disp, "jump": jump, "n": int(len(prim[0])), "reg": str(r.region).split()[0]})
    D = pd.DataFrame(rows); D.to_json("backtest-villa-robust.json", orient="records", force_ascii=False)
    print(f"  시험 {len(D):,}건"); report(D)
    try:  # 2026-10-25 정확도 원장 - 빌라 시세·예상매도가(직전 실거래만으로 다음 거래가 맞히기)
        _s2 = importlib.util.spec_from_file_location("led", os.path.join(HERE, "accuracy_ledger.py")); led = importlib.util.module_from_spec(_s2); _s2.loader.exec_module(led)
        _s3 = importlib.util.spec_from_file_location("ab", os.path.join(HERE, "analyze-bidcases.py")); ab = importlib.util.module_from_spec(_s3); _s3.loader.exec_module(ab)
        r = D["actual"] / D["e50"] - 1
        led.record(ab.cyc, "sale_market_villa", {"n": int(len(r)), "err": round(float(np.median(np.abs(r))) * 100, 2), "bias": round(float(np.median(r)) * 100, 2),
                                                  "hi10": round(float((r < -0.10).mean()) * 100, 1), "hi15": round(float((r < -0.15).mean()) * 100, 1)}, "빌라 시세·예상매도가 vs 시장 거래")
    except Exception as e:
        print("  원장 기록 건너뜀(빌라):", e)


def tail(a, e):
    r = a / e - 1
    return f"n{len(r):6,} 오차 {np.median(np.abs(r)) * 100:5.2f}% 치우침 {np.median(r) * 100:+6.2f}% | 예상이 10%+ 높음 {(r < -0.10).mean() * 100:4.1f}% · 15%+ 높음 {(r < -0.15).mean() * 100:4.1f}% · 25%+ 높음 {(r < -0.25).mean() * 100:4.1f}% · 하위10% {np.quantile(r, .10) * 100:+6.1f}%"


def report(D):
    print("\n==== ① 현재 방식(중앙값) vs 견고화 후보 ====")
    for nm, c in (("현재(중앙값)", "e50"), ("40% 지점", "e40"), ("튀는 거래 제외 후 중앙값", "etr")):
        print(f"  {nm:22}", tail(D["actual"].values, D[c].values))
    print("\n==== 단계별 하방 위험(현재 방식) ====")
    for lv, G in D.groupby("lvl"):
        if len(G) >= 200:
            print(f"  {lv:10}", tail(G["actual"].values, G["e50"].values), "| 40%지점:", tail(G["actual"].values, G["e40"].values).split("|")[1].strip())
    print("\n==== ③ 불안정 신호별 하방 위험(현재 방식) ====")
    d = D[D.disp.notna()]
    for lo, hi, lab in ((0, 0.15, "흩어짐 낮음(IQR 15%↓)"), (0.15, 0.30, "중간(15~30%)"), (0.30, 0.50, "높음(30~50%)"), (0.50, 9, "매우 높음(50%↑)")):
        G = d[(d.disp >= lo) & (d.disp < hi)]
        if len(G) >= 200: print(f"  {lab:22}", tail(G["actual"].values, G["e50"].values))
    d = D[D.jump.notna()]
    for lo, hi, lab in ((-9, -0.08, "같은 건물 최근 거래가 8%↓"), (-0.08, 0.08, "비슷(±8%)"), (0.08, 9, "최근 거래가 8%↑")):
        G = d[(d.jump > lo) & (d.jump <= hi)]
        if len(G) >= 200: print(f"  {lab:22}", tail(G["actual"].values, G["e50"].values))
    print("\n==== 흩어짐 높음일 때 견고화 후보 ====")
    G = D[D.disp >= 0.30]
    for nm, c in (("현재", "e50"), ("40% 지점", "e40"), ("튀는 거래 제외", "etr")):
        print(f"  {nm:12}", tail(G["actual"].values, G[c].values))
    print("\n==== 지역별 하방(현재) ====")
    for rg, G in D.groupby("reg"):
        if len(G) >= 500: print(f"  {rg}", tail(G["actual"].values, G["e50"].values))


if __name__ == "__main__":
    main()
