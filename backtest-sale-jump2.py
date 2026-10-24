"""
🔬 최근 실거래가가 '시세 반영'인지 '튀는 가격'인지 가려서 예상매도가에 반영하기 (2026-10-24, 사용자: 최근 실거래가가 시세의 반영인지, 튀는 가격인지 확인이 중요)
기준값 V0 = 앱의 현재 규칙(6개월 같은 평형 3건+: 서울 최근3건 중위 / 경기·인천 반감1개월 / 지방 반감2개월 가중 중위, 그 밖: 12개월 반감3개월 가중 중위).
최근 거래 L(가장 최근 중개거래)이 V0보다 높을 때, 정답이 V0~L 사이 어디에 있었나 w* = (실제 − V0) ÷ (L − V0)를 구하고,
 '다른 근거가 같이 오르는지'로 w(최근 거래를 믿는 비중)를 예측:
  mom    같은 단지 전체 평형 ㎡당 가격의 최근 3개월 ÷ 그 전 3~9개월 (단지 안 다른 평형도 올랐나)
  conf   L과 ±5% 안에 드는 다른 같은 평형 거래가 12개월 안에 더 있나(1/0)
  flhi   L의 층이 같은 평형 다른 거래들의 중앙 층보다 5층 이상 높은가(높은 층 프리미엄 의심)
  mkt    시군구 ㎡당 가격 3개월 변화
  agem   L이 몇 개월 전인가
방식 비교(오차·치우침): V0 / 고정 50% / 학습한 w(2025년 학습 → 2026년 평가)
"""
import os, json, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ab", os.path.join(HERE, "analyze-bidcases.py"))
ab = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ab)
avm = ab.avm
rng = np.random.default_rng(8)
MAX_TEST = int(os.environ.get("MAX_TEST", "80000"))


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
    tr["t"] = (tr["ts"] - pd.Timestamp("2000-01-01")).dt.days.astype(float); tr["ym"] = (tr["ts"].dt.year * 12 + tr["ts"].dt.month).astype(int)
    tr["ppm"] = tr["price"] / tr["size"]; tr["cls"] = tr["region"].map(cls_of)
    print(f"  거래 {len(tr):,}건")
    by = {}
    for (r, ym), g in tr.groupby(["rg", "ym"]): by[(r, ym)] = g["ppm"].values
    ic = {}

    def idx(rg, ym):
        k = (rg, ym)
        if k in ic: return ic[k]
        vals = [by[(rg, m)] for m in (ym - 2, ym - 1, ym) if (rg, m) in by]
        out = float(np.median(np.concatenate(vals))) if vals and sum(len(v) for v in vals) >= 8 else None
        ic[k] = out; return out

    groups = {k: g.sort_values("t").reset_index(drop=True) for k, g in tr.groupby(["rg", "dk", "dj"])}
    t_start = (pd.Timestamp("2025-01-01") - pd.Timestamp("2000-01-01")).days
    test = []
    for k, g in groups.items():
        for i in np.where(g["t"].values >= t_start)[0]: test.append((k, i))
    sel = rng.choice(len(test), min(len(test), MAX_TEST * 2), replace=False); test = [test[i] for i in sel]
    rows = []
    for k, i in test:
        if len(rows) >= MAX_TEST: break
        g = groups[k]; T = g.iloc[i]; H = g.iloc[:i]; H = H[H["t"] < T["t"]]; cls = T["cls"]
        sz = float(T["size"]); same = H[(H["size"] - sz).abs() <= 3]
        age = (T["t"] - same["t"].values) / 30.4; m6 = age <= 6; n6 = int(m6.sum())
        if n6 < 1: continue
        p = same["price"].values.astype(float); fl = same["floor"].values.astype(float); m12 = age <= 12
        if n6 >= 3:
            p6, a6 = p[m6], age[m6]
            V0 = float(np.median(p6[np.argsort(a6)[:3]])) if cls == "서울" else wmed(p6, 0.5 ** (a6 / (1.0 if cls == "경기·인천" else 2.0)))
        else:
            V0 = wmed(p[m12], 0.5 ** (age[m12] / 3.0))
        o = np.argsort(age); L = float(p[o[0]]); agem = float(age[o[0]]); Lfl = fl[o[0]]
        if agem > 6: continue
        rec = dict(cls=cls, n6=n6, actual=float(T["price"]), V0=V0, L=L, jump=L / V0 - 1, agem=agem)
        ym0 = int(T["ym"]); i0, i3 = idx(k[0], ym0 - 1), idx(k[0], ym0 - 4)
        rec["mkt"] = float(np.clip(np.log(i0 / i3), -0.15, 0.15)) if i0 and i3 else 0.0
        a_all = (T["t"] - H["t"].values) / 30.4
        pr, pv = H["ppm"].values[a_all <= 3], H["ppm"].values[(a_all > 3) & (a_all <= 9)]
        rec["mom"] = float(np.clip(np.log(np.median(pr) / np.median(pv)), -0.2, 0.2)) if len(pr) >= 2 and len(pv) >= 2 else np.nan
        mk = m12.copy(); mk[o[0]] = False
        others, fo = p[mk], fl[mk]
        rec["conf"] = float((np.abs(others / L - 1) <= 0.05).sum() >= 1) if len(others) else 0.0
        rec["flhi"] = float(bool(np.isfinite(Lfl) and len(fo) >= 1 and np.isfinite(fo).any() and (Lfl - np.nanmedian(fo)) >= 5))
        rec["ts"] = T["ts"]
        rows.append(rec)
    D = pd.DataFrame(rows); D.to_json("backtest-sale-jump2.json", orient="records", force_ascii=False, date_format="iso")
    print(f"  시험 {len(D):,}건 (최근 6개월 거래 있음)")
    report(D)


def stat(a, e):
    r = a / e - 1
    return f"n{len(r):6,} 오차 {np.median(np.abs(r)) * 100:5.2f}% 치우침 {np.median(r) * 100:+6.2f}% 10%초과 {(np.abs(r) > .1).mean() * 100:4.1f}%"


def design(d):
    return np.column_stack([d["mom"].fillna(0).values * 5, d["conf"].values, d["flhi"].values, d["mkt"].values * 5, np.minimum(d["agem"].values, 6) / 6, np.ones(len(d))])


def report(D):
    D = D.copy(); D["ts"] = pd.to_datetime(D["ts"])
    tr_ = D[D.ts < "2026-01-01"]; te = D[D.ts >= "2026-01-01"]
    print(f"\n학습(2025) {len(tr_):,} → 평가(2026) {len(te):,}")
    out = {}
    for lab, thr in (("최근이 8%↑", 0.08), ("최근이 15%↑", 0.15)):
        for grp, mk in (("6개월 1~2건", lambda d: d.n6 <= 2), ("6개월 3건+", lambda d: d.n6 >= 3)):
            a = tr_[(tr_.jump >= thr)]; a = a[mk(a)]; c = te[(te.jump >= thr)]; c = c[mk(c)]
            if len(a) < 150 or len(c) < 80:
                print(f"\n[{lab} · {grp}] 표본 부족 학습 {len(a)} 평가 {len(c)}"); continue
            ws = np.clip((a.actual - a.V0) / (a.L - a.V0), -0.5, 1.5)
            X = design(a); R = 1.0 * len(X) / 50 * np.eye(X.shape[1]); R[-1, -1] = 0
            beta = np.linalg.solve(X.T @ X + R, X.T @ ws.values)
            wp = np.clip(design(c) @ beta, 0.0, 1.0)
            print(f"\n[{lab} · {grp}] 학습 {len(a):,} 평가 {len(c):,} | 정답 위치 w* 중앙 {ws.median():.2f} | 계수(mom,conf,flhi,mkt,agem,상수) {[round(float(x),2) for x in beta]}")
            print("   현재(V0)        ", stat(c.actual.values, c.V0.values))
            print("   최근 거래 그대로  ", stat(c.actual.values, c.L.values))
            for w0 in (0.3, 0.5, 0.7):
                print(f"   고정 {int(w0*100)}%        ", stat(c.actual.values, (c.V0 + w0 * (c.L - c.V0)).values))
            print("   학습한 비중      ", stat(c.actual.values, (c.V0 + wp * (c.L - c.V0)).values), f"(비중 평균 {wp.mean():.2f})")
            # 확인된 경우(conf=1 또는 mom>0.03)와 아닌 경우의 정답 위치
            for nm, m in (("다른 근거로 확인됨(conf 또는 단지 상승)", (c.conf == 1) | (c.mom > 0.03)), ("확인 안 됨", ~((c.conf == 1) | (c.mom > 0.03)))):
                cc = c[m]
                if len(cc) >= 30:
                    wst = np.clip((cc.actual - cc.V0) / (cc.L - cc.V0), -0.5, 1.5)
                    print(f"   · {nm} n{len(cc)}: 정답 위치 w* 중앙 {wst.median():.2f} | 현재 {stat(cc.actual.values, cc.V0.values)} | 50% {stat(cc.actual.values, (cc.V0 + 0.5 * (cc.L - cc.V0)).values)}")
            out[f"{lab}|{grp}"] = {"beta": [round(float(x), 3) for x in beta], "n": int(len(a)), "wMed": round(float(ws.median()), 2)}
    json.dump(out, open("backtest-sale-jump2-weights.json", "w"), ensure_ascii=False)


if __name__ == "__main__":
    main()
