"""
🔬 거래가 충분한 단지(최근 6개월 같은 평형 3건+)에서 예상매도가 오차를 줄이는 요인 찾기 (2026-10-20, 사용자: 거래가 있는 곳의 정확도를 올리는 게 더 중요)
기준값 V0 = 앱의 지역별 규칙(서울 최근3건 중위 / 경기·인천 반감1개월 / 지방 반감2개월 가중 중위). 정답 = 시험 거래의 실제 가격, 직전 정보만 사용. 2025년~ 중개거래.
 후보 요인(모두 입찰 직전 정보):
  fl   시험 거래의 층 − 기준 거래들의 평균 층 (층이 높으면 비싼 경향) / 저층(1~2층) 표시
  momc 같은 단지 전체 평형 ㎡당 가격의 최근 3개월 ÷ 그 전 3~9개월 (단지 안 가격 흐름)
  moml 시군구 ㎡당 가격 3개월 변화 (주변 시장 흐름)
  lastg 가장 최근 같은 평형 거래가 ÷ V0 (최근 거래를 더 믿어야 하나)
  span 기준 거래 가격의 흩어짐(IQR/중위) - 방향 보정이 아니라 오차 크기 예측용
  pm   같은 평형 6~18개월 전 거래의 중위 ÷ V0 (최근 거래가 평소 대비 튀었나 - 평균 회귀)
 방법: 2025년 시험분으로 지역 × 요인 회귀(능형)를 맞추고 2026년 시험분에서 오차를 비교. 요인별 단독 효과와 전체 효과를 출력.
"""
import os, json, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ab", os.path.join(HERE, "analyze-bidcases.py"))
ab = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ab)
avm = ab.avm
rng = np.random.default_rng(33)
MAX_TEST = int(os.environ.get("MAX_TEST", "30000"))
FEATS = ["fl", "low", "momc", "moml", "lastg", "pm"]


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
    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,floor,deal_date,dealing_type,cdeal_type", extra_filter="&deal_date=gte.20220101")
    if "cdeal_type" in tr.columns: tr = tr[tr["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    for c in ("price", "size", "floor", "deal_date"): tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"]); tr = tr[(tr["price"] > 0) & (tr["size"] > 10) & (tr["dealing_type"] != "직거래")]
    tr["dk"] = tr["dong"].map(ab.dong_key); tr["rg"] = tr["region"].map(ab.region_norm); tr["dj"] = tr["danji"].astype(str).str.strip()
    tr["ts"] = pd.to_datetime(tr["deal_date"].astype(int).astype(str), format="%Y%m%d", errors="coerce"); tr = tr.dropna(subset=["ts", "rg"])
    tr["t"] = (tr["ts"] - pd.Timestamp("2000-01-01")).dt.days.astype(float)
    tr["ym"] = (tr["ts"].dt.year * 12 + tr["ts"].dt.month).astype(int)
    tr["ppm"] = tr["price"] / tr["size"]; tr["cls"] = tr["region"].map(cls_of)
    print(f"  거래 {len(tr):,}건")
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
    t_start = (pd.Timestamp("2025-01-01") - pd.Timestamp("2000-01-01")).days
    rows = []
    for cls in ("서울", "경기·인천", "지방"):
        test = []
        for k, g in groups.items():
            if g["cls"].iloc[0] != cls: continue
            for i in np.where(g["t"].values >= t_start)[0]: test.append((k, i))
        sel = rng.choice(len(test), min(len(test), MAX_TEST * 2), replace=False); test = [test[i] for i in sel]
        got = 0
        for k, i in test:
            if got >= MAX_TEST: break
            g = groups[k]; T = g.iloc[i]; H = g.iloc[:i]; H = H[H["t"] < T["t"]]
            sz = float(T["size"])
            same = H[(H["size"] - sz).abs() <= 3]
            age = (T["t"] - same["t"].values) / 30.4
            m6 = age <= 6
            if m6.sum() < 3: continue
            p6 = same["price"].values[m6].astype(float); a6 = age[m6]
            if cls == "서울": V0 = float(np.median(p6[np.argsort(a6)[:3]]))
            else: V0 = wmed(p6, 0.5 ** (a6 / (1.0 if cls == "경기·인천" else 2.0)))
            rec = dict(cls=cls, actual=float(T["price"]), V0=V0, ts=T["ts"], n6=int(m6.sum()))
            fl6 = same["floor"].values[m6]
            tf = T["floor"]
            if pd.notna(tf) and np.isfinite(fl6).any():
                rec["fl"] = float(np.clip(tf - np.nanmean(fl6), -15, 15)) / 10; rec["low"] = float(tf <= 2)
            ym0 = int(T["ym"])
            ppm_recent = H["ppm"].values[(T["t"] - H["t"].values) / 30.4 <= 3]; ppm_prev = H["ppm"].values[((T["t"] - H["t"].values) / 30.4 > 3) & ((T["t"] - H["t"].values) / 30.4 <= 9)]
            if len(ppm_recent) >= 3 and len(ppm_prev) >= 3: rec["momc"] = float(np.clip(np.log(np.median(ppm_recent) / np.median(ppm_prev)), -0.15, 0.15))
            i0, i3 = idx(k[0], ym0 - 1), idx(k[0], ym0 - 4)
            if i0 and i3: rec["moml"] = float(np.clip(np.log(i0 / i3), -0.15, 0.15))
            la = np.argmin(a6); rec["lastg"] = float(np.clip(np.log(p6[la] / V0), -0.3, 0.3))
            old = same["price"].values[(age > 6) & (age <= 18)]
            if len(old) >= 2: rec["pm"] = float(np.clip(np.log(np.median(old) / V0), -0.3, 0.3))
            rec["span"] = float((np.quantile(p6, .75) - np.quantile(p6, .25)) / np.median(p6)) if len(p6) >= 4 else np.nan
            rows.append(rec); got += 1
        print(f"  {cls}: 시험 {got:,}건")
    D = pd.DataFrame(rows)
    D.to_json("backtest-sale-rich.json", orient="records", force_ascii=False, date_format="iso")
    report(D)


def design(d, feats):
    X = np.column_stack([d[f].fillna(0.0).values for f in feats] + [np.ones(len(d))]) if feats else np.ones((len(d), 1))
    return X


def fit(d, feats, lam=1.0):
    X = design(d, feats); y = np.log(d["actual"] / d["V0"]).values
    R = lam * len(X) / 50 * np.eye(X.shape[1]); R[-1, -1] = 0
    return np.linalg.solve(X.T @ X + R, X.T @ y)


def stat(r):
    return f"오차 {np.median(np.abs(r)) * 100:5.2f}% 치우침 {np.median(r) * 100:+5.2f}% 10%초과 {(np.abs(r) > .1).mean() * 100:4.1f}% p90 {np.quantile(np.abs(r), .9) * 100:5.1f}%"


def report(D):
    tr_ = D[D["ts"] < pd.Timestamp("2026-01-01")]; te = D[D["ts"] >= pd.Timestamp("2026-01-01")]
    print(f"\n학습(2025) {len(tr_):,}건 → 평가(2026) {len(te):,}건 (6개월 같은 평형 3건+)")
    sets = [("상수만", []), ("층", ["fl", "low"]), ("단지 흐름", ["momc"]), ("시군구 흐름", ["moml"]), ("최근 거래", ["lastg"]), ("평균 회귀", ["pm"]), ("전부", FEATS)]
    summary = {}
    for cls in ("서울", "경기·인천", "지방", None):
        a = tr_ if cls is None else tr_[tr_.cls == cls]; c = te if cls is None else te[te.cls == cls]
        if len(a) < 500 or len(c) < 300: continue
        print(f"\n[{cls or '전체'}] 학습 {len(a):,} 평가 {len(c):,}")
        print("   기존 규칙(보정 없음)   ", stat(c["actual"].values / c["V0"].values - 1))
        for nm, fs in sets:
            w = fit(a, fs); p = c["V0"].values * np.exp(design(c, fs) @ w)
            print(f"   {nm:10} ", stat(c["actual"].values / p - 1), "계수", [round(float(x), 3) for x in w[:-1]])
            summary[f"{cls or '전체'}|{nm}"] = round(float(np.median(np.abs(c["actual"].values / p - 1))) * 100, 2)
    # 거래 수 구간별 (전체 모델)
    for lo, hi, lab in ((3, 5, "3~5건"), (6, 11, "6~11건"), (12, 999, "12건+")):
        a = tr_; c = te[(te.n6 >= lo) & (te.n6 <= hi)]
        if len(c) < 300: continue
        w = fit(a, FEATS); p = c["V0"].values * np.exp(design(c, FEATS) @ w)
        print(f"\n[6개월 {lab}] 평가 {len(c):,}\n   기존 ", stat(c["actual"].values / c["V0"].values - 1), "\n   전부 ", stat(c["actual"].values / p - 1))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("### 거래 충분 구간 요인 시험\n```json\n" + json.dumps(summary, ensure_ascii=False, indent=1) + "\n```\n")


if __name__ == "__main__":
    main()
