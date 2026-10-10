"""
🏘️ 빌라 예상매도가에 '전세가'를 쓰면 정확해지나 (2026-10-10, 사용자: "빌라 매매의 핵심은 전세가 - 그 건물 전세가로 매매가를 대략 추측, 전세가율이 사실상 매도가 한계")
방법: 거래마다 '그 거래 30일 전까지 자료만'으로 예측해 실제가와 비교.
  기존: 건물→동→시군구 매매 거래 ㎡당 가격
  전세: (같은 건물 → 같은 동 → 시군구) 최근 12개월 순수 전세 ㎡당 보증금 중앙값(면적 ±8㎡) × 그 동의 최근 24개월 '매매÷전세' 비율(없으면 시군구)
  혼합: 기존과 전세 추정을 가중 평균(전세 비중 0.3/0.5), 전세가 있을 때만
결과: 방식별 적용 비율·보통 오차·±10%·±20%·상하위 10%, 기존 단계별 구분
"""
import os, json, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py"))
bv = importlib.util.module_from_spec(_s); _s.loader.exec_module(bv)
avm = bv.avm
N_TEST = int(os.environ.get("N_TEST", "15000"))
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"


def wmed(v, w):
    o = np.argsort(v); v = v[o]; w = w[o]; c = np.cumsum(w) / w.sum()
    return float(v[min(np.searchsorted(c, 0.5), len(v) - 1)])


def main():
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.{bv.START}{FLT}")
    df = bv.prep(raw)
    rr = avm.fetch_all_rows("villa_rent", cols="region,dong,bunji,size,deposit,monthly_rent,floor,deal_date,build_year", extra_filter=f"&deal_date=gte.{bv.START}{FLT}")
    print(f"매매 {len(df):,}건 / 전월세 {len(rr):,}건")
    for c in ("size", "deposit", "monthly_rent", "deal_date", "build_year"):
        rr[c] = pd.to_numeric(rr[c], errors="coerce")
    rr = rr[(rr["monthly_rent"].fillna(0) == 0) & (rr["deposit"] > 0) & (rr["size"] >= 15) & (rr["size"] <= 150)].dropna(subset=["deal_date"])
    rr["dt"] = pd.to_datetime(rr["deal_date"].astype(int).astype(str), format="%Y%m%d", errors="coerce"); rr = rr.dropna(subset=["dt"])
    rr["day"] = (rr["dt"] - pd.Timestamp("2020-01-01")).dt.days.astype(int)
    rr["ppm"] = rr["deposit"] / rr["size"]
    rr["bld"] = rr["region"].astype(str) + "|" + rr["dong"].astype(str) + "|" + rr["bunji"].astype(str)
    rr["dk"] = rr["region"].astype(str) + "|" + rr["dong"].astype(str)
    rr = rr.sort_values("day")
    print(f"순수 전세 {len(rr):,}건 ({rr['deal_date'].min()}~{rr['deal_date'].max()})")
    gJ = {kc: {k: (G["day"].values, G["size"].values, G["ppm"].values, G["build_year"].values) for k, G in rr.groupby(kc)} for kc in ("bld", "dk", "region")}
    gS = {kc: {k: (G["day"].values, G["size"].values, G["ppm"].values) for k, G in df.groupby(kc)} for kc in ("dk", "region")}

    def jq(kc, key, dc, days, size, tol, by=None, byy=None):
        t = gJ[kc].get(key)
        if t is None: return None, 0
        d, sz, pp, yb = t
        hi = np.searchsorted(d, dc, side="right"); lo = np.searchsorted(d, dc - days, side="left")
        if hi <= lo: return None, 0
        m = np.abs(sz[lo:hi] - size) <= tol
        if byy is not None and by is not None and np.isfinite(by): m &= (np.isnan(yb[lo:hi]) | (np.abs(yb[lo:hi] - by) <= byy))
        if not m.any(): return None, 0
        w = np.exp(-(dc - d[lo:hi][m]) / 365.0) * np.exp(-np.abs(sz[lo:hi][m] - size) / 10.0)
        return wmed(pp[lo:hi][m], w), int(m.sum())

    def ratio(kc, key, dc, size):  # 같은 곳 최근 24개월 매매÷전세 ㎡당 비율
        a = gS[kc].get(key); b = gJ[kc].get(key)
        if a is None or b is None: return None
        out = []
        for d, sz, pp in ((a[0], a[1], a[2]), (b[0], b[1], b[2])):
            hi = np.searchsorted(d, dc, side="right"); lo = np.searchsorted(d, dc - 730, side="left")
            m = np.abs(sz[lo:hi] - size) <= 15
            if m.sum() < 3: return None
            out.append(float(np.median(pp[lo:hi][m])))
        return out[0] / out[1] if out[1] > 0 else None

    T = df[df["deal_date"] >= bv.TEST_FROM]
    if len(T) > N_TEST: T = T.sample(N_TEST, random_state=7)
    E = bv.estimate(df, T); E = E[(E["tadj"] == 0) & (E["q"] == 0.5)].set_index("i")
    rows = []
    for r in T.itertuples():
        i = r.Index
        if i not in E.index: continue
        dc = r.day - 30; by = r.build_year if np.isfinite(r.build_year) else None
        j, n = jq("bld", r.bld, dc, 365, r.size, 8); src = "건물"
        if j is None or n < 1: j, n = jq("dk", r.dk, dc, 365, r.size, 8, by, 5); src = "동"
        if j is None or n < 3: j2, n2 = jq("region", r.region, dc, 365, r.size, 8); (j, n, src) = (j2, n2, "시군구") if j2 is not None else (j, n, src)
        rt = ratio("dk", r.dk, dc, r.size) or ratio("region", r.region, dc, r.size)
        ej = j * rt * r.size if (j is not None and rt) else None
        rows.append({"i": i, "lvl": E.loc[i, "lvl"], "base": E.loc[i, "est"], "j": ej, "jsrc": src if ej else None, "actual": r.price})
    R = pd.DataFrame(rows)
    R["b3"] = R["base"]
    R["mix30"] = np.where(R["j"].notna(), np.exp(0.7 * np.log(R["base"]) + 0.3 * np.log(R["j"].fillna(1))), np.nan)
    R["mix50"] = np.where(R["j"].notna(), np.exp(0.5 * np.log(R["base"]) + 0.5 * np.log(R["j"].fillna(1))), np.nan)

    def stat(G, col):
        G = G[G[col].notna()]
        if len(G) < 30: return None
        e = G[col] / G["actual"] - 1; a = e.abs()
        return {"n": int(len(G)), "medAbsErrPct": round(float(a.median()) * 100, 1), "within10Pct": round(float((a <= .1).mean()) * 100, 1), "within20Pct": round(float((a <= .2).mean()) * 100, 1),
                "p10": round(float(e.quantile(.1)) * 100, 1), "p90": round(float(e.quantile(.9)) * 100, 1), "biasPct": round(float(e.median()) * 100, 1)}
    out = {"전세 추정 적용비율%": round(float(R["j"].notna().mean()) * 100, 1)}
    names = {"base": "기존", "j": "전세만", "mix30": "혼합(전세30%)", "mix50": "혼합(전세50%)"}
    # 같은 표본(전세 추정이 있는 거래)에서 공정 비교
    S = R[R["j"].notna()]
    for col, nm in names.items():
        out[nm + " (전세 있는 표본)"] = stat(S, col)
        weak = S[S["lvl"] != "건물3+"]; out[nm + " (전세 있고 건물3+ 아님)"] = stat(weak, col)
        for l, G in S.groupby("lvl"):
            s = stat(G, col)
            if s: out.setdefault("단계별 " + l, {})[nm] = s
    out["전세 출처 비율%"] = {k: round(v * 100, 1) for k, v in S["jsrc"].value_counts(normalize=True).items()}
    txt = json.dumps(out, ensure_ascii=False, indent=1); print(txt)
    json.dump(out, open("backtest-villa-jeonse.json", "w"), ensure_ascii=False, indent=1)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("```json\n" + txt + "\n```\n")


if __name__ == "__main__":
    main()
