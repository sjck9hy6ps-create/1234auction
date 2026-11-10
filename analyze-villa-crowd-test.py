"""
🏘️ 빌라 낙찰가 개선 시험 두 가지 (2026-11-10, 사용자: 요인 확대 모델(②-b)과 몰림을 읽는 새 입력 요인을 먼저 시험)
입력: villa-cases-asof.json(2026-06 이후 낙찰 사례 + 그 당시 종합 시세 등), 채점 결과 villa-score-rows.json(현재 낙찰가 모델의 예상 낙찰가 wbPrice)
 ① 요인 확대 모델(②-b): 현재 예상 낙찰가의 잔차 ln(실제÷예상)을 16개 입력으로 직접 학습 - 시간순 확장 창 4구간(앞 40%로 학습→다음 15% 시험 …)으로 일관성 확인
 ② 새 입력 요인 후보(입찰 35일 전 자료만): 법정동 가격·거래량 흐름, 반경 700m·1.5km 거래량 흐름·최근 12개월 거래 수(회전율), 반경 가격 흐름, 도시민박 밀집(법정동 영업 수)
    - 입찰자 수 예측(상관)과 낙찰가 잔차 학습(오차·쏠림)에서 새 요인을 넣었을 때 나아지는가
 임차인 유무는 입찰 전 자료에 없어 이번 시험에서 제외. 측정 전용. 출력 villa-crowd-test.json
"""
import os, json, importlib.util
import numpy as np, pandas as pd, requests
from sklearn.ensemble import HistGradientBoostingRegressor
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, fn):
    s = importlib.util.spec_from_file_location(name, os.path.join(HERE, fn)); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
bv = load("bv", "backtest-villa.py"); avm = bv.avm
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"


def to_days(d):
    d = np.asarray(d, dtype=np.int64)
    return (d // 10000 - 2000) * 372 + ((d // 100) % 100 - 1) * 31 + (d % 100 - 1)


def main():
    cases = json.load(open(os.environ.get("CASES", "input/villa-cases-asof.json")))
    sc = {r["id"]: r for r in json.load(open(os.environ.get("SCORE_ROWS", "input/villa-score-rows.json"))) if not r.get("err")}
    R = [x for x in cases if x["id"] in sc and sc[x["id"]].get("wbPrice") and x.get("actual")]
    R.sort(key=lambda x: x["sale"]); print(f"사례 {len(R)}건, 입찰자 수 있는 건 {sum(1 for x in R if x.get('bidders'))}")
    # ── 거래·좌표(입찰 35일 전 자료 계산용): 읽기는 한 번 ──
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.20250101{FLT}")
    df = bv.prep(raw)
    cc = avm.fetch_all_rows("complex_coords", cols="cache_key,lat,lon", order_col="id", extra_filter="&or=(sigungu_cd.like.11*,sigungu_cd.like.28*,sigungu_cd.like.41*)")
    cmap = {r.cache_key: (r.lat, r.lon) for r in cc.itertuples() if r.lat and r.lon}
    mnum = pd.to_numeric(df["main_num"], errors="coerce"); snum = pd.to_numeric(df["sub_num"], errors="coerce")
    base = df["dong"].fillna("").astype(str) + "|" + df["danji"].fillna("").astype(str) + "|" + df["bunji"].fillna("").astype(str) + "|" + df["road_name"].fillna("").astype(str) + "|"
    k_new = (base + mnum.fillna(0).astype(int).astype(str) + "|" + snum.fillna(0).astype(int).astype(str).where(snum.fillna(0) > 0, "")).str.lower()
    k_leg = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "" if pd.isna(v) else str(int(v)))).str.lower()
    k_leg0 = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "0" if pd.isna(v) else str(int(v)))).str.lower()
    co = k_new.map(cmap)
    for alt in (k_leg, k_leg0): co = co.where(~co.isna(), alt.map(cmap))
    df["lat"] = co.map(lambda x: x[0] if isinstance(x, tuple) else np.nan); df["lon"] = co.map(lambda x: x[1] if isinstance(x, tuple) else np.nan)
    df["d"] = to_days(df["deal_date"].astype(int).values); df["dk"] = df["region"].astype(str) + "|" + df["dong"].astype(str).str.split().str[-1]
    G = df[df["lat"].notna()]; KM = 111.0 * np.cos(np.radians(37.5))
    X = np.c_[G["lat"].values * 111.0, G["lon"].values * KM]; tree = cKDTree(X); g_d, g_p = G["d"].values, G["ppm"].values
    dong_idx = {k: (g["d"].values, g["ppm"].values) for k, g in df.groupby("dk")}
    # 도시민박 밀집(법정동): 사이트에서 한 번 받음(재시도·실패하면 비워 두고 계속)
    hs = {}
    for k in range(4):
        try:
            r = requests.get(SITE + "/api/data-coverage?mode=homestay", timeout=60).json(); hs = (r or {}).get("byDong") or {}; break
        except Exception as e:
            print("도시민박 받기 재시도", k + 1, str(e)[:60])
    print(f"도시민박 집계 {len(hs)}곳")
    def flow(d, p, cut, w=90):
        a = p[(d <= cut) & (d > cut - w)]; b = p[(d <= cut - w) & (d > cut - 2 * w)]
        price = float(np.log(np.median(a) / np.median(b))) if len(a) >= 5 and len(b) >= 5 else np.nan
        vol = float(np.log((len(a) + 1) / (len(b) + 1)))
        return price, vol, len(a), len(b)
    new = []
    for x in R:
        cut = int(to_days([int(x["sale"])])[0]) - 35
        d_, p_ = dong_idx.get(f"{x['region']}|{str(x['dong']).split()[-1]}", (np.array([]), np.array([])))
        dp, dv, dn1, dn0 = flow(d_, p_, cut) if len(d_) else (np.nan, np.nan, 0, 0)
        r7p = r7v = r15v = np.nan; n7 = n15 = 0
        if x.get("lat") is not None and x.get("lon") is not None:
            p0 = np.array([x["lat"] * 111.0, x["lon"] * KM])
            for rad, nm in ((0.7, "7"), (1.5, "15")):
                ix = np.array(tree.query_ball_point(p0, rad), dtype=int)
                if len(ix):
                    pr, vo, n1, n0 = flow(g_d[ix], g_p[ix], cut)
                    n12 = int(((g_d[ix] <= cut) & (g_d[ix] > cut - 365)).sum())
                    if nm == "7": r7p, r7v, n7 = pr, vo, n12
                    else: r15v, n15 = vo, n12
        h = hs.get(f"{x['region']}|{str(x['dong']).split()[-1]}") or hs.get(f"{x['region']} |{str(x['dong']).split()[-1]}") or {}
        new.append([dp, dv, r7p, r7v, n7, r15v, n15, float(h.get("open") or 0), float(h.get("new1y") or 0)])
    New = np.array(new, float); print("새 요인 채움 비율:", [round(float(np.isfinite(New[:, k]).mean()) * 100) for k in range(New.shape[1])])
    def fails(m, a):
        if not a or not m: return -1
        r = m / a
        for k, l in enumerate([.9, .72, .58, .47, .38, .31, .25]):
            if r >= l: return min(k, 4)
        return 4
    def feat(x):
        return [np.log(x["minbid"] / x["est"]), fails(x["minbid"], x["appr"]), x["sido"], x["area"], x["floor"] if x["floor"] is not None else 3, (2026 - x["by"]) if x["by"] else -1,
                {"건물3+": 0, "건물1~2+동": 1, "건물1~2": 2, "동5+": 3, "동1~4": 4, "시군구": 5}.get(x["lvl"], 3), x["nRad"] if x["nRad"] is not None else -1, x["nBld"], x["nDong"], x["disp"] if x["disp"] is not None else -1,
                np.log(x["est"]), int(str(x["sale"])[4:6]), 1 if x["elv"] else (0 if x["elv"] is not None else -1), x["grnd"] or -1, x["hh"] or -1]
    X0 = np.array([feat(x) for x in R], float); X1 = np.c_[X0, New]
    wp = np.array([sc[x["id"]]["wbPrice"] for x in R], float); act = np.array([x["actual"] for x in R], float); y = np.log(act / wp)
    bid = np.array([x.get("bidders") or np.nan for x in R], float); n = len(R)
    # 시간순 확장 창 4구간: 앞 40%로 학습→다음 15% 시험, 앞 55%→다음 15%, 앞 70%→다음 15%, 앞 85%→나머지
    folds = [(0.40, 0.55), (0.55, 0.70), (0.70, 0.85), (0.85, 1.0)]
    P = dict(max_iter=120, learning_rate=0.05, max_depth=3, min_samples_leaf=40, random_state=1)
    def fit_pred(Xm, tr, te):
        m = HistGradientBoostingRegressor(loss="absolute_error", **P).fit(Xm[tr], y[tr]); return m.predict(Xm[te])
    res = {"사례": n, "folds": []}; agg = {k: [] for k in ("기준", "②-b", "②-b+새요인")}; aggb = {k: [] for k in agg}; corr = {"기존입력": [], "기존+새요인": []}
    for a, b in folds:
        tr = np.arange(0, int(n * a)); te = np.arange(int(n * a), int(n * b))
        out = {"학습": len(tr), "시험": len(te)}
        for nm, pr in (("기준", np.zeros(len(te))), ("②-b", fit_pred(X0, tr, te)), ("②-b+새요인", fit_pred(X1, tr, te))):
            e = wp[te] * np.exp(pr) / act[te] - 1; agg[nm].append(e); aggb[nm].append(bid[te])
            out[nm] = {"중앙오차%": round(float(np.median(np.abs(e))) * 100, 2), "±10%": round(float(np.mean(np.abs(e) <= .1)) * 100, 1), "쏠림%": round(float(np.median(e)) * 100, 1)}
        # 입찰자 수 예측(상관)
        mk_tr = tr[np.isfinite(bid[tr])]; mk_te = te[np.isfinite(bid[te])]
        for nm, Xm in (("기존입력", X0), ("기존+새요인", X1)):
            if len(mk_tr) >= 200 and len(mk_te) >= 100:
                m = HistGradientBoostingRegressor(loss="absolute_error", **P).fit(Xm[mk_tr], np.log(bid[mk_tr])); pb = m.predict(Xm[mk_te])
                c = float(np.corrcoef(np.log(bid[mk_te]), pb)[0, 1]); out["입찰자수상관_" + nm] = round(c, 3); corr[nm].append(c)
        res["folds"].append(out); print(json.dumps(out, ensure_ascii=False))
    summ = {}
    for nm in agg:
        e = np.concatenate(agg[nm]); b = np.concatenate(aggb[nm])
        s = {"n": int(len(e)), "중앙오차%": round(float(np.median(np.abs(e))) * 100, 2), "±10%": round(float(np.mean(np.abs(e) <= .1)) * 100, 1), "쏠림%": round(float(np.median(e)) * 100, 1)}
        for lo, hi, lab in ((1, 1, "단독"), (2, 3, "2~3명"), (4, 7, "4~7명"), (8, 999, "8명+")):
            mk = np.isfinite(b) & (b >= lo) & (b <= hi)
            if mk.sum() >= 30: s["쏠림_" + lab] = round(float(np.median(e[mk])) * 100, 1)
        summ[nm] = s
    res["합계(시험 구간 합산)"] = summ
    res["입찰자수 예측 상관(구간 평균)"] = {k: round(float(np.mean(v)), 3) for k, v in corr.items() if v}
    # 새 요인 단독 효과: 입찰자 수·잔차와의 순위 상관
    res["새요인 상관"] = {}
    for k, nm in enumerate(["동 가격흐름", "동 거래량흐름", "반경700 가격흐름", "반경700 거래량흐름", "반경700 12개월 거래수", "반경1.5km 거래량흐름", "반경1.5km 12개월 거래수", "도시민박 영업", "도시민박 신규1년"]):
        v = New[:, k]; ok = np.isfinite(v) & np.isfinite(bid)
        if ok.sum() > 200 and np.nanstd(v[ok]) > 0:
            rk = lambda z: pd.Series(z).rank().values
            res["새요인 상관"][nm] = {"입찰자수": round(float(np.corrcoef(rk(v[ok]), rk(bid[ok]))[0, 1]), 3), "낙찰가 잔차": round(float(np.corrcoef(rk(v[np.isfinite(v)]), rk(y[np.isfinite(v)]))[0, 1]), 3), "n": int(ok.sum())}
    print(json.dumps(res, ensure_ascii=False, indent=1)); json.dump(res, open("villa-crowd-test.json", "w"), ensure_ascii=False)


if __name__ == "__main__":
    main()
