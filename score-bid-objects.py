"""
════════════════════════════════════════════════════════════
🎯 입찰 경쟁·등수·환금성 점수 (2026-10-14, 사용자: 모든 입찰건 상세에 ① 생활반경 기준 잘 팔리는 평형인지 추천/비추천 ② 생활반경 기준 최근 입찰 인원으로 예상 입찰자 수 → 구간별 낙찰가
③ 입찰자 수 구간별 낙찰가(시세 대비)·1등 확률·격차 표. 지역통계가 아니라 물건 위치 기준 반경으로)
════════════════════════════════════════════════════════════
입력: 낙찰사례(/api/auction?kind=bidCases: 좌표·입찰자수·2등가·낙찰가·되팔기 매칭), 등록 경매물건(/api/auction), 입찰후보 계산 결과(board|cache 아파트 시세·추천가, board|villa 빌라 시세·추천가).
방법(모두 '그 사례 낙찰일 이전 자료'만 사용 - 시간 순서 분리 검증):
 - 반경 특징: 같은 종류(아파트/빌라) 낙찰사례 중 반경 1.5km·4km 안, 최근 365일의 사례 수·입찰자 수 중앙값·1명 단독 비율·낙찰가/기준가 중앙값
 - 입찰자 수 구간(1명/2~3/4~6/7~10/11명+) 확률: 반경 특징 + 최저가÷시세·유찰·면적·층·시기로 분류 모델(HistGradientBoosting)
 - 구간별 낙찰가: 같은 구간·비슷한 유찰 사례의 (낙찰가÷기준가) 분포 → 이 물건의 시세(아파트)·최저가(빌라) 기준 금액, 추천가에서의 1등·2등·3등 이하 확률과 졌을 때 격차
 - 잘 팔리는 평형: 물건 위치 반경 4km의 같은 평형대 낙찰사례(낙찰 후 1년 이상 지난 것)의 되팔림 비율·손해 비율·보유 기간 → 지역·종류 기준선 대비 추천/보통/비추천(시험 기간으로 적중 확인)
결과: leader_follower_cache 'bidscore|N'(물건별) + 'bidscore|meta' + 'signal|__bidval__'(전체 표·검증·지난주 예측 적중)
사용: python score-bid-objects.py [--dry]   (--dry면 저장 안 하고 bidscore-out.json만)
"""
import os, sys, json, math, re, time
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import requests
from sklearn.neighbors import BallTree
from sklearn.ensemble import HistGradientBoostingClassifier

SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
DRY = "--dry" in sys.argv
SB = (os.environ.get("SUPABASE_URL") or "").rstrip("/"); SK = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
HDR = {"apikey": SK, "Authorization": "Bearer " + SK}
BINS = [(1, 1, "1명"), (2, 3, "2~3명"), (4, 6, "4~6명"), (7, 10, "7~10명"), (11, 999, "11명+")]
COST_RATIO, FIXED_COST = 1.05, 400
NOW = datetime.now(timezone.utc); TODAY = pd.Timestamp(NOW.date())


def binof(n):
    for i, (lo, hi, _) in enumerate(BINS):
        if lo <= n <= hi: return i
    return 4


def get_json(url, **kw):
    for a in range(3):
        try:
            r = requests.get(url, timeout=300, **kw)
            if r.status_code == 200: return r.json()
        except Exception as e:
            time.sleep(3)
    raise RuntimeError("불러오기 실패: " + url[:80])


def sb_get(rid):
    if not SB: return None
    r = requests.get(f"{SB}/rest/v1/leader_follower_cache", headers=HDR, params={"select": "payload", "id": f"eq.{rid}"}, timeout=60).json()
    return r[0]["payload"] if r else None


def sb_put(rows):
    if DRY or not SB: return
    for i in range(0, len(rows), 10):
        r = requests.post(f"{SB}/rest/v1/leader_follower_cache?on_conflict=id", headers={**HDR, "Prefer": "resolution=merge-duplicates"}, data=json.dumps(rows[i:i + 10], ensure_ascii=False, allow_nan=False), timeout=120)
        r.raise_for_status()


def clean(o):
    if isinstance(o, (np.floating, float)): return None if (math.isnan(o) or math.isinf(o)) else round(float(o), 4)
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    return o


def load_cases():
    raw = get_json(f"{SITE}/api/auction?kind=bidCases")
    D = pd.DataFrame(raw)
    D["type"] = np.where(D.propertyType.astype(str).str.contains("아파트", na=False), "apt", np.where(D.propertyType.astype(str).str.contains("다세대|연립|도시형", na=False), "villa", ""))
    D = D[D.type != ""].copy()
    D["actual"] = pd.to_numeric(D.finalBidPrice, errors="coerce") / 1e4; D["minbid"] = pd.to_numeric(D.minBidPrice, errors="coerce") / 1e4; D["appr"] = pd.to_numeric(D.appraisalPrice, errors="coerce") / 1e4
    D["second"] = pd.to_numeric(D.secondBidPrice, errors="coerce") / 1e4; D["bidders"] = pd.to_numeric(D.bidders, errors="coerce"); D["area"] = pd.to_numeric(D.areaM2, errors="coerce"); D["fl"] = pd.to_numeric(D.floor, errors="coerce")
    D["dt"] = pd.to_datetime(D.saleDate, errors="coerce"); D["lat"] = pd.to_numeric(D.lat, errors="coerce"); D["lon"] = pd.to_numeric(D.lon, errors="coerce")
    D = D[(D.actual > 0) & (D.minbid > 0) & D.dt.notna() & D.lat.notna() & D.area.between(10, 400) & (D.dt >= "2022-06-01")].copy()
    D["fails"] = np.round(np.log(D.minbid / D.appr) / np.log(0.8)).clip(0, 7) if False else (np.log((D.minbid / D.appr).clip(0.05, 1.5)) / math.log(0.8)).round().clip(0, 7)
    rm = D.resaleMatch.apply(lambda m: m if isinstance(m, dict) else {})
    D["conf"] = rm.map(lambda m: m.get("conf")); D["rs_amt"] = pd.to_numeric(rm.map(lambda m: m.get("amount")), errors="coerce"); D["rs_date"] = pd.to_datetime(rm.map(lambda m: str(m.get("date")) if m.get("date") else None), format="%Y%m%d", errors="coerce")
    D["rs_m"] = (D.rs_date - D.dt).dt.days / 30.4
    D["sold12"] = ((D.conf == np.where(D.type == "apt", "dong", "floor")) & (D.rs_m <= 12)).astype(float)
    D["loss"] = np.where(D.sold12 == 1, (D.rs_amt < D.actual * COST_RATIO + FIXED_COST).astype(float), np.nan)
    D["aband"] = pd.cut(D.area, [0, 40, 50, 60, 85, 135, 1e9], labels=["~40㎡", "40~50㎡", "50~60㎡", "60~85㎡", "85~135㎡", "135㎡~"]).astype(str)
    return D.sort_values("dt").reset_index(drop=True)


def attach_est(D):
    """아파트 사례의 입찰 30일 전 예상매도가(est): 주간 분석 산출물(bidcases-R.csv.gz)에서. 없으면 최저가÷(감정가×0.8) 추정으로 대신하지 않고 비움"""
    p = os.environ.get("BIDCASES_R", "bidcases-R.csv.gz")
    D["est"] = np.nan
    if os.path.exists(p):
        R = pd.read_csv(p, usecols=["id", "est"]); D["est"] = D.id.map(R.drop_duplicates("id").set_index("id").est)
        print(f"  아파트 시세(est) 연결 {int(D.est.notna().sum()):,}건")
    return D


def ref_of(D):
    """기준가: 아파트=예상매도가(est), 빌라=최저가. 낙찰가÷기준가 분포를 씀"""
    D["ref"] = np.where(D.type == "apt", D.est, D.minbid)
    return D


def local_feats(Q, C, radii=(1.5, 4.0), win=365, asof_col="dt", same_idx=False):
    """Q(질문 지점들)마다 반경 안·최근 win일·Q 시점 이전 사례 C의 요약. same_idx면 Q=C(자기 자신 제외)"""
    R_E = 6371.0
    tree = BallTree(np.radians(C[["lat", "lon"]].values), metric="haversine")
    out = {}
    cd = C.dt.values.astype("datetime64[D]").astype(np.int64); cb = C.bidders.values; cr = np.log(C.actual.values / C.ref.values) if "ref" in C else None
    cref = C.ref.values; cty = C.type.values; ca = C.actual.values
    qd = Q[asof_col].values.astype("datetime64[D]").astype(np.int64)
    for rad in radii:
        ind = tree.query_radius(np.radians(Q[["lat", "lon"]].values), r=rad / R_E)
        n = np.zeros(len(Q)); med = np.full(len(Q), np.nan); one = np.full(len(Q), np.nan); lr = np.full(len(Q), np.nan)
        for i, idx in enumerate(ind):
            if len(idx) == 0: continue
            m = (cty[idx] == Q.type.values[i]) & (cd[idx] < qd[i]) & (cd[idx] >= qd[i] - win)
            if same_idx: m &= idx != i
            sel = idx[m]
            if len(sel) == 0: continue
            b = cb[sel]; b = b[~np.isnan(b)]; n[i] = len(sel)
            if len(b): med[i] = np.median(b); one[i] = np.mean(b <= 1)
            r = np.log(ca[sel] / cref[sel]); r = r[np.isfinite(r)]
            if len(r): lr[i] = np.median(r)
        t = f"{rad:g}"
        out[f"n{t}"] = n; out[f"med{t}"] = med; out[f"one{t}"] = one; out[f"lr{t}"] = lr
    return pd.DataFrame(out, index=Q.index)


def base_feats(D):
    X = pd.DataFrame(index=D.index)
    X["lb"] = np.log(D.minbid / np.where(D.type == "apt", D.est, D.appr))
    X["la"] = np.log(D.area); X["fl"] = D.fl.clip(-1, 30).fillna(3); X["fails"] = D.fails; X["m"] = D.dt.dt.month
    X["lm"] = np.log(D.minbid); return X


class PriorByFails:
    """유찰 횟수 그룹별 입찰자 수 구간 비율(모델이 무정보보다 못할 때의 대안)"""
    def fit(self, X, y):
        self.g = {}; tot = np.bincount(y, minlength=5) + 1.0; self.tot = tot / tot.sum()
        for f, G in pd.Series(y, index=X.index).groupby(X["fails"].clip(0, 3).values):
            c = np.bincount(G.values, minlength=5) + 2.0 * self.tot * 5; self.g[int(f)] = c / c.sum()
        return self
    def predict_proba(self, X):
        return np.vstack([self.g.get(int(min(max(f, 0), 3)), self.tot) for f in X["fails"].values])


def fit_clf(X, y, shallow=False):
    if shallow:
        return HistGradientBoostingClassifier(max_iter=60, learning_rate=0.05, max_depth=2, min_samples_leaf=200, l2_regularization=5.0, random_state=1).fit(X, y)
    return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.06, max_depth=4, min_samples_leaf=40, l2_regularization=1.0, random_state=1).fit(X, y)


def logloss(P, y):
    return float(-np.mean(np.log(np.clip(P[np.arange(len(y)), y], 1e-6, 1))))


def main():
    t0 = time.time()
    D = ref_of(attach_est(load_cases()))
    print(f"낙찰사례 {len(D):,}건 (아파트 {int((D.type == 'apt').sum()):,} · 빌라 {int((D.type == 'villa').sum()):,}), 입찰자 수 있음 {D.bidders.notna().mean() * 100:.1f}%")
    out_val = {"generatedAt": NOW.isoformat(), "types": {}}
    models, tabs = {}, {}
    for ty in ("apt", "villa"):
        T = D[(D.type == ty) & D.bidders.notna() & D.ref.notna() & D.appr.notna()].copy()
        if len(T) < 800: print(f"  {ty}: 사례 부족"); continue
        T["bin"] = T.bidders.map(binof)
        # 반경 특징(그 사례 낙찰일 이전만) + 기본 특징
        AllT = D[(D.type == ty) & D.bidders.notna() & D.ref.notna()].copy()
        LF = local_feats(T, AllT, same_idx=False)
        X = pd.concat([base_feats(T), LF], axis=1)
        cut = pd.Timestamp("2025-07-01"); tr = T.dt < cut; te = ~tr
        rep = {"n": int(len(T)), "test": int(te.sum())}
        cols_loc = list(X.columns); cols_base = list(base_feats(T).columns); cols_reg = cols_base + ["med4", "n4", "one4"]
        cands = {"유찰별 평균 비율": ("prior", ["fails"]), "기본 특징(얕은 모델)": ("shallow", cols_base), "기본 특징": ("deep", cols_base), "지역 통계(반경 4km만)": ("deep", cols_reg), "생활반경 특징(1.5·4km)": ("deep", cols_loc), "생활반경 특징(얕은 모델)": ("shallow", cols_loc)}
        def build(kind, cols, Xtr, ytr):
            if kind == "prior": return PriorByFails().fit(Xtr[cols], ytr)
            return fit_clf(Xtr[cols], ytr, shallow=(kind == "shallow"))
        best = ("유찰별 평균 비율", 9.0)
        if te.sum() >= 300 and tr.sum() >= 800:
            y = T.bin.values; res = {}
            res["무정보(전체 비율)"] = {"logLoss": round(logloss(np.tile(np.bincount(y[tr], minlength=5) / tr.sum(), (te.sum(), 1)), y[te]), 4)}
            for nm, (kind, cols) in cands.items():
                m = build(kind, cols, X.loc[tr], y[tr]); P = m.predict_proba(X.loc[te, cols]); pred = P.argmax(1); ll = logloss(P, y[te])
                res[nm] = {"logLoss": round(ll, 4), "구간 적중%": round(float((pred == y[te]).mean()) * 100, 1), "±1구간 이내%": round(float((np.abs(pred - y[te]) <= 1).mean()) * 100, 1)}
                if ll < best[1]: best = (nm, ll)
            rep["입찰자수 구간 예측(시험)"] = res; rep["선택한 방법"] = best[0]; print("  ", ty, "선택:", best[0], json.dumps({k: v["logLoss"] for k, v in res.items()}, ensure_ascii=False))
        kind, cols = cands[best[0]]
        mfull = build(kind, cols, X, T.bin.values); models[ty] = (mfull, cols, kind)
        # 구간별 낙찰가(기준가 대비)·2등 분포 - 최근 18개월 사례, 유찰 그룹(0,1,2,3+) 별
        W = T[T.dt >= TODAY - pd.Timedelta(days=548)].copy(); W["rr"] = W.actual / W.ref; W["fg"] = W.fails.clip(0, 3).astype(int); W["sr"] = (W.second / W.ref).where(W.second > 0)
        tabs[ty] = W
        rows = []
        for i, (_, _, nm) in enumerate(BINS):
            G = W[W.bin == i]
            if len(G) < 30: continue
            rows.append({"bin": nm, "n": int(len(G)), "p50": float(G.rr.median()), "p70": float(G.rr.quantile(.7)), "p90": float(G.rr.quantile(.9)), "second/1st": float((G.second / G.actual).median()) if G.second.notna().sum() > 20 else None})
        rep["구간별 낙찰가÷기준가"] = rows; rep["기준가"] = "예상매도가" if ty == "apt" else "최저가"
        # 가격 수준별 등수(시험 기간 사례에 기준가×m를 적었다면)
        Te = T[te & T.ref.notna()]
        lv = []
        for mlt in ((0.80, 0.85, 0.90, 0.95, 1.0) if ty == "apt" else (1.05, 1.15, 1.25, 1.35, 1.5)):
            P_ = Te.ref * mlt; win = P_ >= Te.actual; sec = Te.second.notna() & (Te.second > 0)
            r2 = ((~win) & sec & (P_ >= Te.second)); r3 = ((~win) & sec & (P_ < Te.second)); feas = P_ >= Te.minbid
            lv.append({"배수": mlt, "입찰가능%": round(float(feas.mean()) * 100, 1), "1등%": round(float(win[feas].mean()) * 100, 1) if feas.any() else None, "2등%": round(float(r2[feas & sec].mean()) * 100, 1) if (feas & sec).any() else None,
                       "3등이하%": round(float(r3[feas & sec].mean()) * 100, 1) if (feas & sec).any() else None, "졌을때 격차%": round(float(((Te.actual - P_) / Te.actual)[(~win) & feas].median()) * 100, 1) if ((~win) & feas).any() else None})
        rep["가격수준별 등수"] = lv; rep["배수 기준"] = "예상매도가×배수" if ty == "apt" else "최저가×배수"
        # 입찰자 수 구간별 1등% (기준가×대표 배수)
        out_val["types"][ty] = rep
    # ── 물건별 점수 ──
    auc = get_json(f"{SITE}/api/auction")
    A = pd.DataFrame([a for a in auc if a and not a.get("isBacktest") and a.get("lat") and a.get("lon") and a.get("propType") in ("apt", "villa") and (a.get("bidDate") or "") >= str(TODAY.date())])
    print(f"점수 대상 입찰물건 {len(A):,}건")
    # 입찰후보 계산 결과(시세·추천가) 읽기
    est, recp = {}, {}
    def chunks(kind):
        meta = get_json(f"{SITE}/api/data-coverage", params={"mode": "boardCacheMeta", "kind": kind})
        return [get_json(f"{SITE}/api/data-coverage", params={"mode": "boardCacheChunk", "kind": kind, "i": i}) for i in range(int(meta.get("n") or 0))]
    for ch in chunks(""):
        for k, v in (ch.get("items") or {}).items():
            r = v.get("row") or {}
            if r.get("sale"): est[str(k)] = float(r["sale"])
            pe = (r.get("pick") or {}).get("ev")
            if pe and pe.get("bid"): recp[str(k)] = float(pe["bid"])
    for ch in chunks("villa"):
        for k, v in (ch.get("ev") or {}).items():
            pe = (v.get("pn") or {}).get("ev")
            if (v.get("ve") or {}).get("est"): est[str(k)] = float(v["ve"]["est"])
            if pe and pe.get("bid"): recp[str(k)] = float(pe["bid"])
    A["id"] = A["id"].astype(str)
    A["est"] = A.id.map(est); A["rec"] = A.id.map(recp)
    A["type"] = A.propType; A["minbid"] = pd.to_numeric(A.minBid, errors="coerce"); A["appr"] = pd.to_numeric(A.appraisal, errors="coerce")
    A["area"] = pd.to_numeric(A.pyung, errors="coerce") * 3.305785; A["fl"] = pd.to_numeric(A.floor, errors="coerce")
    A["fails"] = (np.log((A.minbid / A.appr).clip(0.05, 1.5)) / math.log(0.8)).round().clip(0, 7)
    A["lat"] = pd.to_numeric(A.lat); A["lon"] = pd.to_numeric(A.lon); A["dt"] = TODAY
    A["ref"] = np.where(A.type == "apt", A.est, A.minbid)
    A = A[A.minbid.gt(0) & A.appr.gt(0) & A.area.gt(5) & A.ref.gt(0)].copy()
    # 환금성(잘 팔리는 평형) 기준선: 종류·시도별 되팔림/손해
    S = D[(D.dt <= TODAY - pd.Timedelta(days=365)) & (D.dt >= "2023-01-01")].copy(); S["sido"] = S.addrJibun.astype(str).str[:2]
    base_sold = S.groupby("type").sold12.mean().to_dict(); base_loss = S.groupby("type").loss.mean().to_dict()
    # 시험: 같은 규칙을 과거 시점에 적용했을 때 추천/비추천 적중
    out_val["bandCheck"] = band_backtest(D)
    recs = {}
    for ty in ("apt", "villa"):
        if ty not in models: continue
        Q = A[A.type == ty].copy()
        if Q.empty: continue
        AllT = D[(D.type == ty) & D.bidders.notna() & D.ref.notna()].copy()
        Q["lat"] = Q.lat.astype(float)
        LF = local_feats(Q, AllT); XB = base_feats(Q.assign(est=Q.est))
        XB["lb"] = np.log(Q.minbid / np.where(ty == "apt", Q.est, Q.appr))
        XQ = pd.concat([XB, LF], axis=1)[models[ty][1]]; XQ = XQ.assign(fails=Q.fails.values) if "fails" not in XQ else XQ
        P = models[ty][0].predict_proba(XQ); W = tabs[ty]
        # 밴드(생활반경 4km, 같은 평형대) 환금성
        Sv = S[S.type == ty]; tree = BallTree(np.radians(Sv[["lat", "lon"]].values), metric="haversine"); ind = tree.query_radius(np.radians(Q[["lat", "lon"]].values), r=4.0 / 6371.0)
        aband = pd.cut(Q.area, [0, 40, 50, 60, 85, 135, 1e9], labels=["~40㎡", "40~50㎡", "50~60㎡", "60~85㎡", "85~135㎡", "135㎡~"]).astype(str)
        for qi, (idx_q, row) in enumerate(Q.iterrows()):
            p = P[qi]; ref = float(row.ref); fg = int(min(row.fails, 3))
            tab = []
            for bi, (_, _, nm) in enumerate(BINS):
                G = W[(W.bin == bi) & (W.fg == fg)]
                if len(G) < 25: G = W[W.bin == bi]
                if len(G) < 15: tab.append(None); continue
                q50, q70, q90 = [float(G.rr.quantile(x)) * ref for x in (.5, .7, .9)]
                item = {"p": round(float(p[bi]), 3), "q50": round(q50), "q70": round(q70), "q90": round(q90), "n": int(len(G))}
                if row.rec and row.rec > 0:
                    rr = row.rec / ref; win = float((G.rr <= rr).mean())
                    item["win"] = round(win, 3)
                    gs = G[G.rr > rr]; item["gap"] = round(float(((gs.rr - rr) * ref).median())) if len(gs) >= 5 else 0
                    S2 = G[G.sr.notna()]
                    if len(S2) >= 20: item["r2"] = round(float(((S2.sr <= rr) & (S2.rr > rr)).mean()), 3)
                tab.append(item)
            kexp = float(sum(p[i] * v for i, v in enumerate([1, 2.5, 5, 8.5, 14])))
            rec = {"t": "a" if ty == "apt" else "v", "ref": round(ref), "refKind": "est" if ty == "apt" else "min", "kexp": round(kexp, 1), "tab": tab}
            if row.rec and row.rec > 0:
                ws = [t["win"] * t["p"] for t in tab if t and "win" in t]; ps = [t["p"] for t in tab if t and "win" in t]
                if ps: rec["rec"] = round(float(row.rec)); rec["win"] = round(sum(ws) / sum(ps), 3)
            # 반경 정보
            lf = LF.iloc[qi]; rec["loc"] = {"n": int(lf["n1.5"]), "med": None if pd.isna(lf["med1.5"]) else float(lf["med1.5"]), "one": None if pd.isna(lf["one1.5"]) else round(float(lf["one1.5"]), 2), "n4": int(lf["n4"]), "med4": None if pd.isna(lf["med4"]) else float(lf["med4"])}
            # 잘 팔리는 평형
            sel = Sv.iloc[ind[qi]] if len(ind[qi]) else Sv.iloc[0:0]; sel = sel[sel.aband == aband.iloc[qi]]
            n = len(sel); k0 = 20.0; bs, bl = base_sold.get(ty, 0.3), base_loss.get(ty, 0.3)
            sold = float(sel.sold12.mean()) if n else bs; sh = (n * sold + k0 * bs) / (n + k0)
            nl = int(sel.loss.notna().sum()); lossr = float(sel.loss.mean()) if nl else bl; lh = (nl * lossr + k0 * bl) / (nl + k0)
            hold = float(sel[sel.sold12 == 1].rs_m.median()) if (sel.sold12 == 1).sum() >= 5 else None
            verdict = "good" if (sh >= bs + 0.05 and lh <= bl + 0.03) else ("bad" if (sh <= bs - 0.05 or lh >= bl + 0.10) else "mid")
            rec["band"] = {"label": aband.iloc[qi], "n": n, "sold": round(sold, 3), "soldS": round(sh, 3), "loss": round(lossr, 3) if nl else None, "lossS": round(lh, 3), "nl": nl, "hold": None if hold is None else round(hold, 1), "base": round(bs, 3), "baseLoss": round(bl, 3), "v": verdict}
            recs[row.id] = rec
    # 지난주 예측 적중
    out_val["calibration"] = calibration(D, A, recs)
    out_val["scored"] = len(recs)
    print(f"점수 계산 {len(recs):,}건, {time.time() - t0:.0f}초")
    # 저장
    ids = sorted(recs); CH = 400; rows = []
    for i in range(0, len(ids), CH):
        rows.append({"id": f"bidscore|{i // CH}", "payload": clean({"items": {k: recs[k] for k in ids[i:i + CH]}}), "fetched_at": NOW.isoformat()})
    idx = {k: i // CH for i, k in enumerate(ids)}
    rows.append({"id": "bidscore|meta", "payload": clean({"n": len(rows), "count": len(ids), "at": int(NOW.timestamp() * 1000), "idx": idx}), "fetched_at": NOW.isoformat()})
    rows.append({"id": "signal|__bidval__", "payload": clean(out_val), "fetched_at": NOW.isoformat()})
    json.dump(clean({"val": out_val, "sample": {k: recs[k] for k in ids[:5]}}), open("bidscore-out.json", "w"), ensure_ascii=False, indent=1)
    sb_put(rows); print("✅ 저장" if not DRY else "(dry) bidscore-out.json 저장")


def band_backtest(D):
    """잘 팔리는 평형 규칙을 과거 시점에 적용: 2024-07~2025-04 낙찰 사례마다 '그 시점 1년 전까지 확정된 이웃 사례'로 추천/보통/비추천을 정하고, 실제 그 물건의 되팔림·손해를 비교"""
    res = {}
    for ty in ("apt", "villa"):
        T = D[(D.type == ty)].copy()
        Q = T[(T.dt >= "2024-07-01") & (T.dt < "2025-05-01") & T.sold12.notna()]
        K = T[T.dt < "2024-05-01"]
        if len(Q) < 300 or len(K) < 500: continue
        bs, bl = K.sold12.mean(), K.loss.mean()
        tree = BallTree(np.radians(K[["lat", "lon"]].values), metric="haversine"); ind = tree.query_radius(np.radians(Q[["lat", "lon"]].values), r=4.0 / 6371.0)
        vs = []
        for qi, (_, r) in enumerate(Q.iterrows()):
            sel = K.iloc[ind[qi]]; sel = sel[(sel.aband == r['aband']) & (sel.dt <= r['dt'] - pd.Timedelta(days=365))] if len(ind[qi]) else K.iloc[0:0]
            n = len(sel); nl = int(sel.loss.notna().sum()); k0 = 20.0
            sh = (n * (sel.sold12.mean() if n else bs) + k0 * bs) / (n + k0); lh = (nl * (sel.loss.mean() if nl else bl) + k0 * bl) / (nl + k0)
            vs.append("good" if (sh >= bs + 0.05 and lh <= bl + 0.03) else ("bad" if (sh <= bs - 0.05 or lh >= bl + 0.10) else "mid"))
        Q = Q.assign(v=vs); g = {}
        for v, G in Q.groupby("v"):
            g[v] = {"n": int(len(G)), "되팔림12개월%": round(float(G.sold12.mean()) * 100, 1), "손해%": round(float(G.loss.mean()) * 100, 1) if G.loss.notna().sum() >= 10 else None}
        res[ty] = {"기준선 되팔림%": round(float(bs) * 100, 1), "기준선 손해%": round(float(bl) * 100, 1), "결과": g}
        print("  환금성 규칙 시험", ty, json.dumps(g, ensure_ascii=False))
    return res


def norm_case(c):
    return re.sub(r"[^0-9\-]", "", str(c or "")).strip("-")


def calibration(D, A, recs):
    """지난 실행의 예측을 지금 낙찰 결과와 비교(2026-10-14): 예상 입찰자 수 구간 확률(로그손실·구간 적중)과 추천가 1등 확률(예측 구간별 실제 1등 비율).
    로그 'signal|__bidscore_log__' = {pending:{물건id: 예측}, resolved:{집계}}. 결과가 확인된 물건은 pending에서 빼 집계에 더하고, 이번 예측을 pending에 넣음."""
    prev = sb_get("signal|__bidscore_log__") if SB else None
    pending = dict((prev or {}).get("pending") or {}); res = (prev or {}).get("resolved") or {"n": 0, "ll": 0.0, "hit": 0, "k": [0, 0, 0, 0, 0], "wc": [[0, 0.0, 0] for _ in range(5)], "nWin": 0}
    cases = D[D.actual > 0].copy(); cases["cn"] = cases.caseNo.map(norm_case)
    byc = {}
    for r in cases.itertuples():
        byc.setdefault(r.cn, []).append(r)
    new = {"n": 0, "ll": 0.0, "hit": 0, "winN": 0, "winPred": 0.0, "winReal": 0}; done = []
    for pid, it in pending.items():
        cand = [r for r in byc.get(it.get("cn", ""), []) if r.type == ("apt" if it.get("t") == "a" else "villa") and abs(float(r.area) - float(it.get("area") or r.area)) <= 1.0 and str(r.dt.date()) >= str(it.get("bid") or "2000")[:10]]
        if not cand: continue
        r = cand[0]; done.append(pid)
        if r.bidders == r.bidders and it.get("p"):
            b = binof(int(r.bidders)); pv = it["p"]; res["n"] += 1; new["n"] += 1; ll = -math.log(max(pv[b], 1e-6)); res["ll"] += ll; new["ll"] += ll
            hit = int(int(np.argmax(pv)) == b); res["hit"] += hit; new["hit"] += hit; res["k"][b] += 1
        if it.get("rec") and it.get("win") is not None:
            w = 1 if float(it["rec"]) >= float(r.actual) else 0; bk = min(4, int(float(it["win"]) * 5)); res["wc"][bk][0] += 1; res["wc"][bk][1] += float(it["win"]); res["wc"][bk][2] += w; res["nWin"] += 1
            new["winN"] += 1; new["winPred"] += float(it["win"]); new["winReal"] += w
    for pid in done: pending.pop(pid, None)
    for _, row in A.iterrows():
        rc = recs.get(row["id"])
        if not rc: continue
        pending[row["id"]] = {"cn": norm_case(row.get("caseNo")), "t": rc["t"], "area": round(float(row["area"]), 1), "bid": str(row.get("bidDate") or "")[:10], "p": [t["p"] if t else 0 for t in rc["tab"]], "rec": rc.get("rec"), "win": rc.get("win"), "at": str(TODAY.date())}
    pending = {k: v for k, v in pending.items() if (TODAY - pd.Timestamp(v.get("at") or TODAY)).days <= 120}
    sb_put([{"id": "signal|__bidscore_log__", "payload": clean({"pending": pending, "resolved": res}), "fetched_at": NOW.isoformat()}])
    out = {"누적 검증 물건": res["n"], "이번에 새로 확인": new["n"], "pending": len(pending)}
    if res["n"]: out["입찰자수 구간 평균 로그손실"] = round(res["ll"] / res["n"], 3); out["입찰자수 구간 적중%"] = round(res["hit"] / res["n"] * 100, 1)
    if res["nWin"]:
        out["추천가 1등 확률 - 예측 vs 실제"] = [{"예측구간": f"{i * 20}~{i * 20 + 20}%", "건수": int(c[0]), "예측 평균%": round(c[1] / c[0] * 100, 1), "실제 1등%": round(c[2] / c[0] * 100, 1)} for i, c in enumerate(res["wc"]) if c[0]]
    return out


if __name__ == "__main__":
    main()
