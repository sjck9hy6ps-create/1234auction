"""
🏘️ 빌라 '같은 동 비교' 질 개선 시험 (2026-11-07, 사용자: 수도권 빌라 정확도)
기존: 같은 동 12개월·면적 ±8㎡·준공 ±5년 하드 필터 → 중앙값. 개선 후보: 하드 필터 대신 거리 가중(면적·준공연도·시점) + 승강기 같음/층 구간 같음 가중 + 기간 길이.
시험: 건물 3건 이상이 아닌 거래(동·시군구 단계로 가는 거래) 전체에서, 같은 거래를 기존 방식과 후보로 예측해 오차 비교(30일 전까지 자료만).
결과는 서버 signal|__villa_bt_compare__ (mode=villaBt&name=compare)에 저장.
"""
import os, json, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, fn):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, fn)); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
bv = load("bv", "backtest-villa.py"); vf = load("vf", "analyze-villa-factors.py")
avm = bv.avm
N_TEST = int(os.environ.get("N_TEST", "15000"))
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"


def wmed(v, w):
    o = np.argsort(v); v = v[o]; w = w[o]; c = np.cumsum(w) / w.sum()
    return float(v[min(np.searchsorted(c, 0.5), len(v) - 1)])


def fcls(f):
    f = np.where(np.isnan(f), 3, f)
    return np.where(f <= 0, 0, np.where(f <= 2, 1, np.where(f <= 4, 2, 3)))


def main():
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.{bv.START}{FLT}")
    df = bv.prep(raw)
    cc = avm.fetch_all_rows("complex_coords", cols="cache_key,sigungu_cd,bjdong_cd", order_col="id", extra_filter="&or=(sigungu_cd.like.11*,sigungu_cd.like.28*,sigungu_cd.like.41*)")
    cmap = {r.cache_key: (r.sigungu_cd, r.bjdong_cd) for r in cc.itertuples()}
    mnum = pd.to_numeric(df["main_num"], errors="coerce"); snum = pd.to_numeric(df["sub_num"], errors="coerce")
    base = df["dong"].fillna("").astype(str) + "|" + df["danji"].fillna("").astype(str) + "|" + df["bunji"].fillna("").astype(str) + "|" + df["road_name"].fillna("").astype(str) + "|"
    k_new = (base + mnum.fillna(0).astype(int).astype(str) + "|" + snum.fillna(0).astype(int).astype(str).where(snum.fillna(0) > 0, "")).str.lower()
    k_leg = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "" if pd.isna(v) else str(int(v)))).str.lower()
    k_leg0 = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "0" if pd.isna(v) else str(int(v)))).str.lower()
    c2 = k_new.map(cmap)
    for alt in (k_leg, k_leg0): c2 = c2.where(~c2.isna(), alt.map(cmap))
    df["sg"] = c2.map(lambda x: x[0] if isinstance(x, tuple) else None); df["bj"] = c2.map(lambda x: x[1] if isinstance(x, tuple) else None)
    bb = df["bunji"].map(vf.bunji_to_bunji); df["bun"] = bb.map(lambda x: x[0] if x else None); df["ji"] = bb.map(lambda x: x[1] if x else None)
    B = vf.fetch_buildings()
    if len(B):
        for c in ("elv", "emg", "apr"): B[c] = pd.to_numeric(B.get(c), errors="coerce") if c != "apr" else pd.to_numeric(B["apr"].astype(str).str[:4], errors="coerce")
        B["elvAny"] = ((B["elv"].fillna(0) + B["emg"].fillna(0)) > 0).astype(float)
        Bg = B.groupby(["sigungu_cd", "bjdong_cd", "bun", "ji"]).agg(elv=("elvAny", "max"), apr=("apr", "min")).reset_index()
        df = df.merge(Bg, how="left", left_on=["sg", "bj", "bun", "ji"], right_on=["sigungu_cd", "bjdong_cd", "bun", "ji"], suffixes=("", "_b"))
    else:
        df["elv"] = np.nan; df["apr"] = np.nan
    df = df.reset_index(drop=True)
    # 준공연도: 거래 신고값 우선, 없으면 대장 사용승인연
    df["by2"] = df["build_year"].where(df["build_year"].between(1960, 2026), df["apr"].where(df["apr"].between(1960, 2026)))
    print(f"거래 {len(df):,}건, 대장 승강기 정보 {df['elv'].notna().mean() * 100:.1f}%")
    T = df[df["deal_date"] >= bv.TEST_FROM]
    if len(T) > N_TEST: T = T.sample(N_TEST, random_state=7)
    E = bv.estimate(df, T); E = E[(E["tadj"] == 0) & (E["q"] == 0.5)].set_index("i")
    T = T[T.index.isin(E.index)]
    T = T[E.loc[T.index, "lvl"].values != "건물3+"]
    print(f"시험(건물3+ 제외) {len(T):,}건")

    G = {}
    for k, g in df.groupby("dk"):
        G[k] = (g["day"].values, g["size"].values, g["ppm"].values, g["by2"].values.astype(float), g["elv"].values.astype(float), fcls(g["floor"].values.astype(float)))
    GR = {}
    for k, g in df.groupby("region"):
        GR[k] = (g["day"].values, g["size"].values, g["ppm"].values, g["by2"].values.astype(float), g["elv"].values.astype(float), fcls(g["floor"].values.astype(float)))

    def est(t, r, days, yb, tau, elvw, flw, stol=15):
        if t is None: return None
        d, sz, pp, yy, ee, ff = t
        dc = r.day - 30
        hi = np.searchsorted(d, dc, side="right"); lo = np.searchsorted(d, dc - days, side="left")
        if hi <= lo: return None
        s = sz[lo:hi]; m = np.abs(s - r.size) <= stol
        if m.sum() < 3: return None
        w = np.exp(-(dc - d[lo:hi][m]) / tau) * np.exp(-np.abs(s[m] - r.size) / 10.0)
        y = yy[lo:hi][m]; by = r.by2
        if yb and np.isfinite(by): w = w * np.where(np.isnan(y), 0.5, np.exp(-np.abs(y - by) / yb))
        if elvw < 1 and np.isfinite(r.elv): e = ee[lo:hi][m]; w = w * np.where(np.isnan(e), (1 + elvw) / 2, np.where(e == r.elv, 1.0, elvw))
        if flw < 1:
            f = ff[lo:hi][m]; tf = fcls(np.array([r.floor], dtype=float))[0]; w = w * np.where(f == tf, 1.0, flw)
        return wmed(pp[lo:hi][m], w) * r.size

    V = {
        "동 가중(준공5년·기간12개월)": dict(days=365, yb=5, tau=365, elvw=1, flw=1),
        "동 가중(준공3년)": dict(days=365, yb=3, tau=365, elvw=1, flw=1),
        "동 가중(준공8년)": dict(days=365, yb=8, tau=365, elvw=1, flw=1),
        "동 가중(준공5년)+승강기 같은 것 우대": dict(days=365, yb=5, tau=365, elvw=0.3, flw=1),
        "동 가중(준공5년)+층 구간 같은 것 우대": dict(days=365, yb=5, tau=365, elvw=1, flw=0.5),
        "동 가중(준공5년)+승강기+층 구간": dict(days=365, yb=5, tau=365, elvw=0.3, flw=0.5),
        "동 가중(준공5년+승강기+층)·기간 6개월": dict(days=183, yb=5, tau=180, elvw=0.3, flw=0.5),
        "동 가중(준공5년+승강기+층)·기간 18개월": dict(days=548, yb=5, tau=365, elvw=0.3, flw=0.5),
        "동 가중(준공5년+승강기+층)·기간 24개월": dict(days=730, yb=5, tau=540, elvw=0.3, flw=0.5),
    }
    rows = []
    for r in T.itertuples():
        row = {"i": r.Index, "lvl": E.loc[r.Index, "lvl"], "base": E.loc[r.Index, "est"], "actual": r.price}
        for nm, p in V.items():
            row[nm] = est(G.get(r.dk), r, **p)
        rows.append(row)
    R = pd.DataFrame(rows)

    def stat(S, col):
        S = S[S[col].notna()]
        if len(S) < 30: return None
        e = S[col] / S["actual"] - 1; a = e.abs()
        return {"n": int(len(S)), "medAbsErrPct": round(float(a.median()) * 100, 2), "within10Pct": round(float((a <= .1).mean()) * 100, 1), "within20Pct": round(float((a <= .2).mean()) * 100, 1), "biasPct": round(float(e.median()) * 100, 1)}
    out = {"시험 n": int(len(R)), "대장 승강기 정보 비율%": round(float(df["elv"].notna().mean()) * 100, 1)}
    # 공정 비교: 후보 값이 있는 거래만 기존과 같은 표본에서
    for nm in V:
        S = R[R[nm].notna()]
        out[nm] = {"적용 비율%": round(len(S) / len(R) * 100, 1), "기존(같은 표본)": stat(S, "base"), "후보": stat(S, nm)}
        for l, g in S.groupby("lvl"):
            if len(g) >= 100: out[nm]["단계 " + l] = {"기존": stat(g, "base"), "후보": stat(g, nm)}
    txt = json.dumps(out, ensure_ascii=False, indent=1); print(txt)
    json.dump(out, open("backtest-villa-compare.json", "w"), ensure_ascii=False, indent=1)
    try:
        from datetime import datetime, timezone
        cyc = load("cyc", "analyze-cycle.py"); now = datetime.now(timezone.utc).isoformat()
        cyc.upsert_rows([{"id": "signal|__villa_bt_compare__", "payload": cyc.clean_json(dict(out, generatedAt=now)), "fetched_at": now}]); print("서버 저장: compare")
    except Exception as e:
        print("서버 저장 실패:", e)


if __name__ == "__main__":
    main()
