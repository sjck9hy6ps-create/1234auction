"""팔리는 곳 판정 4차(2026-11-24, 사용자: "같은 평형 12개월 거래 건수보다 더 잘 맞을 수 있는 방법").
같은 평형 12개월 거래 건수(현재 규칙) 대신 여러 신호를 같이 쓰는 모델이 '이후 6개월 같은 평형(가격대) 거래 0건'과 거래 수를 얼마나 더 잘 맞히는지.
신호 묶음(앞 묶음에 누적): G0 지금(12개월 건수만) → G1 같은 평형 3·6·12·24개월 건수 → G2 +마지막 거래 후 경과·작년 같은 계절 거래·월
 → G3 +같은 단지(생활권 넓은 범위) 전체 거래·평형 비중 → G4 +지역(시군구) 거래 흐름(작년 대비) → G5 +전월세 거래(수요, 아파트)·회전율·평형 크기
모델: 시간 순서로 앞쪽 학습, 뒤쪽 시험(6개월 비우고). 시험 시점은 오늘 기준 3·6·9·12개월 4구간(누적). 같은 비율을 거를 때 이후 0건을 얼마나 더 잡는지도 비교.
아파트=단지×면적대(5㎡) 단위, 빌라=경매 사건 위치×평형 반경 500m(±15㎡), 가격대는 같은 평형 12개월 거래가 중앙값의 1.0·1.25·1.5배(±10%)."""
import os, re, json, importlib.util
import numpy as np, pandas as pd
import requests
from scipy.spatial import cKDTree
from scipy.stats import rankdata
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py")); bv = importlib.util.module_from_spec(_s); _s.loader.exec_module(bv)
avm = bv.avm
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"
H = 6
RNG = np.random.default_rng(5)


def ymi(deal_date):
    d = pd.to_numeric(deal_date, errors="coerce")
    return ((d // 10000) * 12 + (d // 100 % 100) - 1).astype("Int64")


def auc_dead(score_dead, dead):
    """score_dead가 높을수록 '이후 0건'일 가능성이 높다고 볼 때의 맞히는 정도."""
    nd = int(dead.sum()); nl = len(dead) - nd
    if nd < 30 or nl < 30: return None
    r = rankdata(score_dead + RNG.normal(0, 1e-9, len(score_dead)))
    return round(float((r[dead].sum() - nd * (nd + 1) / 2) / (nd * nl)), 4)


GROUPS = [
    ("G0 지금: 12개월 건수만", ["n12"]),
    ("G1 +3·6·24개월 건수", ["n3", "n6", "n24"]),
    ("G2 +마지막 거래 경과·작년 같은 계절·월", ["recency", "seas", "month"]),
    ("G3 +단지/넓은 범위 전체 거래·평형 비중", ["tot12", "tot6", "share", "nb"]),
    ("G4 +지역 거래 흐름(작년 대비)", ["reg_yoy", "reg_n12"]),
    ("G5 +전월세 거래·회전율·평형 크기·가격대", ["rent12", "rent6", "turn", "size", "mult", "nBand12"]),
]


def run_models(df, tcol, cut, last_ok, target_cnt, label, feats_avail):
    tr = df[df[tcol] + H < cut]; te_all = df[df[tcol] >= cut]
    if len(tr) > 400000: tr = tr.sample(400000, random_state=1)
    res = {}; cols = []; models = {}
    use = [(n, [c for c in cs if c in feats_avail]) for n, cs in GROUPS]
    for gname, cs in use:
        cols = cols + cs
        if not cols: continue
        ytr = (tr[target_cnt] == 0).astype(int).values; ytc = np.log1p(tr[target_cnt].values.astype(float))
        clf = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.08, max_leaf_nodes=24, random_state=0).fit(tr[cols], ytr)
        reg = HistGradientBoostingRegressor(max_iter=150, learning_rate=0.08, max_leaf_nodes=24, random_state=0).fit(tr[cols], ytc)
        models[gname] = (list(cols), clf, reg)
    for back in (3, 6, 9, 12):
        te = te_all[te_all[tcol] >= last_ok - (back - 1)]
        if len(te) < 300: continue
        dead = (te[target_cnt] == 0).values; y = np.log1p(te[target_cnt].values.astype(float))
        out = {"행수": int(len(te)), "이후 0건%": round(100 * float(dead.mean()), 1)}
        sst = ((y - y.mean()) ** 2).sum(); P = {}
        for gname, (cs, clf, reg) in models.items():
            pd_ = clf.predict_proba(te[cs])[:, 1]; pr = reg.predict(te[cs]); P[gname] = pd_
            out[gname] = {"0건AUC": auc_dead(pd_, dead), "거래수 R2": round(float(1 - ((y - pr) ** 2).sum() / sst), 4)}
        # 같은 비율 비교: 지금 규칙(12개월 5건 미만 제외)이 거르는 비율만큼 모델이 걸렀을 때
        flag0 = (te["n12"] < 5).values if label.startswith("아파트") else (te["n12"] < 5).values
        sh = float(flag0.mean()); k = max(1, int(sh * len(te)))
        def stats(flag):
            n = int(flag.sum()); return {"거른비율%": round(100 * n / len(flag), 1), "이후0건 중 잡은%": round(100 * float((flag & dead).sum() / max(1, dead.sum())), 1), "걸러진 것 중 이후 2건+%": round(100 * float((flag & (te[target_cnt].values >= 2)).sum() / max(1, n)), 1)}
        out["규칙: 12개월 5건 미만 제외"] = stats(flag0)
        for gname in P:
            if gname.startswith(("G3", "G4", "G5")):
                thr = np.sort(P[gname])[::-1][k - 1]; out["같은 비율로 거르면 - " + gname] = stats(P[gname] >= thr)
        # 마지막 모델 보정(확률 구간별 실제 0건)
        lastg = list(P)[-1]; q = pd.qcut(P[lastg], 10, duplicates="drop", labels=False)
        out["보정(" + lastg + ")"] = {f"{int(i)+1}분위": {"예측0건%": round(100 * float(P[lastg][q == i].mean()), 1), "실제0건%": round(100 * float(dead[q == i].mean()), 1)} for i in sorted(set(q))}
        if back == 12:   # 요소별 기여도: 한 요소를 섞었을 때 0건AUC가 얼마나 떨어지는가(마지막 모델)
            cs, clf, reg = list(models.values())[-1]; base_auc = auc_dead(P[list(P)[-1]], dead); imp = {}
            sub = te.sample(min(len(te), 60000), random_state=2); dsub = (sub[target_cnt] == 0).values; b0 = auc_dead(clf.predict_proba(sub[cs])[:, 1], dsub)
            for c in cs:
                t2 = sub.copy(); t2[c] = RNG.permutation(t2[c].values); a2 = auc_dead(clf.predict_proba(t2[cs])[:, 1], dsub)
                if a2 is not None and b0 is not None: imp[c] = round(b0 - a2, 4)
            out["요소별 기여도(섞으면 AUC가 떨어진 폭)"] = dict(sorted(imp.items(), key=lambda kv: -kv[1]))
        res[f"{back}개월"] = out
    return res


# ───────────── 아파트 ─────────────
def apt():
    raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,floor,deal_date,dealing_type", extra_filter="&deal_date=gte.20210101")
    df = raw[raw["dealing_type"] != "직거래"].copy() if "dealing_type" in raw.columns else raw.copy()
    for c in ("price", "size", "deal_date"): df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["price", "size", "deal_date", "region", "dong", "danji"]); df = df[(df["price"] > 0) & (df["size"] > 10)]
    df["ymi"] = ymi(df["deal_date"]).astype(int); last = int(df["ymi"].max()) - 1; first = int(df["ymi"].min()); L = last - first + 1
    df = df[df["ymi"] <= last]; last = L - 1
    df["dong1"] = df["dong"].astype(str).str.split().str[-1].fillna("")
    df["ckey"] = df["region"].astype(str) + "|" + df["dong1"] + "|" + df["danji"].astype(str)
    df["band"] = (df["size"] / 5.0).round().astype(int)
    ym = df["ymi"].values - first
    codes, uniq = pd.factorize(df["ckey"] + "#" + df["band"].astype(str)); ccode, cuniq = pd.factorize(df["ckey"]); u2c = np.zeros(len(uniq), dtype=np.int64); u2c[codes] = ccode
    uband = np.array([int(u.rsplit("#", 1)[1]) for u in uniq]); nc = len(cuniq)
    c2r = pd.Series(pd.Categorical(pd.Series(cuniq).str.split("|").str[0]).codes).values; nr = int(c2r.max()) + 1
    M = np.zeros((len(uniq), L), dtype=np.int16); np.add.at(M, (codes, ym), 1)
    cum = lambda A: np.concatenate([np.zeros((A.shape[0], 1), dtype=np.int32), np.cumsum(A, axis=1, dtype=np.int32)], axis=1)
    C = cum(M)
    Rg = np.zeros((nr, L), dtype=np.int32); np.add.at(Rg, (c2r[ccode], ym), 1); CR = cum(Rg)
    # 전월세 거래(단지별)
    try:
        rr = avm.fetch_all_rows("house_rent", cols="region,dong,danji,deal_date", extra_filter="&deal_date=gte.20210101")
        rr["deal_date"] = pd.to_numeric(rr["deal_date"], errors="coerce"); rr = rr.dropna(subset=["region", "dong", "danji", "deal_date"])
        rr["ckey"] = rr["region"].astype(str) + "|" + rr["dong"].astype(str).str.split().str[-1].fillna("") + "|" + rr["danji"].astype(str)
        cmap = {k: i for i, k in enumerate(cuniq)}; rr["c"] = rr["ckey"].map(cmap); rr = rr.dropna(subset=["c"]); rym = ymi(rr["deal_date"]).astype(int).values - first
        ok = (rym >= 0) & (rym < L); RM = np.zeros((nc, L), dtype=np.int16); np.add.at(RM, (rr["c"].astype(int).values[ok], rym[ok]), 1); CRent = cum(RM); del rr, RM
        print(f"전월세 거래 연결 단지 {int((CRent[:, -1] > 0).sum()):,}", flush=True)
    except Exception as e:
        print("전월세 읽기 실패:", str(e)[:100], flush=True); CRent = None
    # 세대수
    def nm(x): return re.sub(r"[^0-9A-Za-z가-힣]", "", avm.normalize_complex_name(x or "")).replace("아파트", "")
    kp = avm.fetch_all_rows("kapt_complex_info", cols="kapt_code,kapt_name,as3,households", order_col="kapt_code", extra_filter="&households=gt.0")
    hm = {}
    for r in kp.itertuples(): hm.setdefault((str(r.as3).strip().split()[-1] if r.as3 else "", nm(r.kapt_name)), set()).add(int(r.households))
    hhc = np.full(nc, np.nan)
    for i, k in enumerate(cuniq):
        p = k.split("|"); v = hm.get((p[1], nm(p[2])))
        if v and len(v) == 1: hhc[i] = next(iter(v))
    S = lambda a, b: C[:, b + 1] - C[:, a]
    Ts = list(range(2023 * 12 - first, last - H + 1)); rows = []
    for T in Ts:
        To = T - 1; n12 = S(To - 11, To).astype(float); h24 = S(To - 23, To); keep = (h24 > 0) & (n12 >= 2)
        if keep.sum() == 0: continue
        n3 = S(To - 2, To); n6 = S(To - 5, To); n24 = h24
        win = (M[:, To - 23:To + 1][keep] > 0)[:, ::-1]; rec = np.where(win.any(axis=1), win.argmax(axis=1), 24)
        seas = S(To - 10, To - 5)
        tot12 = np.bincount(u2c, weights=n12, minlength=nc); tot6 = np.bincount(u2c, weights=n6.astype(float), minlength=nc); nb = np.bincount(u2c, weights=(n12 > 0).astype(float), minlength=nc)
        reg6 = (CR[:, To + 1] - CR[:, To - 5]).astype(float); regp = (CR[:, To - 11] - CR[:, To - 17]).astype(float); reg12 = (CR[:, To + 1] - CR[:, To - 11]).astype(float)
        ur = c2r[u2c]
        d = {"T": np.full(int(keep.sum()), T), "n12": n12[keep], "n3": n3[keep], "n6": n6[keep], "n24": n24[keep], "recency": rec, "seas": seas[keep], "month": np.full(int(keep.sum()), (T + first) % 12),
             "tot12": tot12[u2c][keep], "tot6": tot6[u2c][keep], "share": n12[keep] / np.maximum(tot12[u2c][keep], 1), "nb": nb[u2c][keep], "reg_yoy": ((reg6 + 1) / (regp + 1))[ur][keep], "reg_n12": reg12[ur][keep],
             "size": uband[keep] * 5.0, "mult": np.ones(int(keep.sum())), "nBand12": n12[keep], "fwd": S(T + 1, T + H)[keep].astype(float)}
        if CRent is not None:
            r12 = (CRent[:, To + 1] - CRent[:, To - 11]).astype(float); r6 = (CRent[:, To + 1] - CRent[:, To - 5]).astype(float)
            d["rent12"] = r12[u2c][keep]; d["rent6"] = r6[u2c][keep]
        else: d["rent12"] = d["rent6"] = np.full(int(keep.sum()), np.nan)
        d["turn"] = n12[keep] / hhc[u2c][keep]
        rows.append(pd.DataFrame(d))
        if len(rows) % 6 == 0: print("  아파트 시점", len(rows), "/", len(Ts), flush=True)
    A = pd.concat(rows, ignore_index=True); print(f"아파트 행 {len(A):,}", flush=True)
    Tu = sorted(A["T"].unique()); cut = Tu[int(len(Tu) * 0.55)]
    return run_models(A, "T", cut, last - H, "fwd", "아파트", set(A.columns)), len(uniq)


# ───────────── 빌라 ─────────────
def villa():
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.20210101{FLT}")
    df = bv.prep(raw)
    cc = avm.fetch_all_rows("complex_coords", cols="cache_key,lat,lon", order_col="id", extra_filter="&or=(sigungu_cd.like.11*,sigungu_cd.like.28*,sigungu_cd.like.41*)")
    cmap = {r.cache_key: (r.lat, r.lon) for r in cc.itertuples() if r.lat and r.lon}
    mnum = pd.to_numeric(df["main_num"], errors="coerce"); snum = pd.to_numeric(df["sub_num"], errors="coerce")
    base = df["dong"].fillna("").astype(str) + "|" + df["danji"].fillna("").astype(str) + "|" + df["bunji"].fillna("").astype(str) + "|" + df["road_name"].fillna("").astype(str) + "|"
    k_new = (base + mnum.fillna(0).astype(int).astype(str) + "|" + snum.fillna(0).astype(int).astype(str).where(snum.fillna(0) > 0, "")).str.lower()
    k_leg = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "" if pd.isna(v) else str(int(v)))).str.lower()
    co = k_new.map(cmap).where(lambda s: s.notna(), k_leg.map(cmap))
    df["ymi"] = ymi(df["deal_date"]).astype(int); first = int(df["ymi"].min()); last = int(df["ymi"].max()) - 1
    # 지역(시군구) 월별 거래 흐름(좌표 없는 거래 포함)
    reg_codes, reg_uniq = pd.factorize(df["region"]); L = last - first + 1
    Rg = np.zeros((len(reg_uniq), L + 1), dtype=np.int32); okm = (df["ymi"].values - first) < L + 1; np.add.at(Rg, (reg_codes[okm], (df["ymi"].values - first)[okm]), 1)
    CR = np.concatenate([np.zeros((Rg.shape[0], 1), dtype=np.int32), np.cumsum(Rg, axis=1, dtype=np.int32)], axis=1)
    df["lat"] = co.map(lambda x: x[0] if isinstance(x, tuple) else np.nan); df["lon"] = co.map(lambda x: x[1] if isinstance(x, tuple) else np.nan)
    D = df[df["lat"].notna()].reset_index(drop=True); reg_of = pd.Series(reg_codes, index=df.index).loc[df["lat"].notna()].values
    tree = cKDTree(np.c_[D["lat"].values * 111.0, D["lon"].values * 111.0 * np.cos(np.radians(37.5))])
    ym = D["ymi"].values; sz = D["size"].values.astype(float); pr = D["price"].values.astype(float)
    raw_a = avm.fetch_all_rows("house_trades", cols="region,dong,price,size,deal_date,dealing_type", extra_filter="&deal_date=gte.20210101")
    ap = raw_a[raw_a["dealing_type"] != "직거래"].copy() if "dealing_type" in raw_a.columns else raw_a.copy()
    for c in ("price", "size", "deal_date"): ap[c] = pd.to_numeric(ap[c], errors="coerce")
    ap = ap.dropna(subset=["price", "deal_date", "region", "dong"]); ap["ymi"] = ymi(ap["deal_date"]).astype(int)
    ap["k"] = ap["region"].astype(str) + "|" + ap["dong"].astype(str).str.split().str[-1].fillna("")
    amap = {k: (g["ymi"].values, g["price"].values.astype(float)) for k, g in ap.groupby("k")}
    cs = requests.get(f"{SITE}/api/auction?kind=bidCases", timeout=300).json(); pts_d = {}
    for c in cs:
        if not any(k in str(c.get("propertyType") or "") for k in ("다세대", "연립", "도시형")): continue
        if not str(c.get("addrJibun", "")).startswith(("서울", "경기", "인천")): continue
        lat, lon = c.get("lat"), c.get("lon")
        try: ar = float(c.get("areaM2"))
        except Exception: continue
        if lat and lon and ar > 0: pts_d[(round(float(lat), 4), round(float(lon), 4), int(round(ar / 5.0)))] = 1
    keys = list(pts_d); pts = np.array([[k[0] * 111.0, k[1] * 111.0 * np.cos(np.radians(37.5))] for k in keys]); areas = np.array([k[2] * 5.0 for k in keys])
    nb5 = tree.query_ball_point(pts, 0.5); nb10 = tree.query_ball_point(pts, 1.0); _, near = tree.query(pts, k=1)
    reg_n = df["region"].astype(str).values[df["lat"].notna().values]; dong_n = D["dong"].astype(str).str.split().str[-1].fillna("").values
    Ts = list(range(2023 * 12 - first, last - H + 1, 2)); MULTS = (1.0, 1.25, 1.5); rec = []
    for i in range(len(keys)):
        if not nb5[i]: continue
        a5 = np.array(nb5[i]); m = ym[a5]; s_ = np.abs(sz[a5] - areas[i]) <= 15; p = pr[a5]
        a10 = np.array(nb10[i]); m10 = ym[a10]; s10 = np.abs(sz[a10] - areas[i]) <= 15
        ak = amap.get(reg_n[near[i]] + "|" + dong_n[near[i]]); rg = reg_of[near[i]]
        for tm in Ts:
            To = tm - 1; hs = (m >= tm - 12) & (m <= tm - 1) & s_
            if hs.sum() < 3: continue
            ref = float(np.median(p[hs])); f = (m >= tm + 1) & (m <= tm + H) & s_
            same_m = m[s_ & (m <= To)]; recency = (To - same_m.max()) if len(same_m) else 24
            r6 = float(CR[rg, To + 1 - first] - CR[rg, To - 5 - first]); rp = float(CR[rg, To - 11 - first] - CR[rg, To - 17 - first]); r12 = float(CR[rg, To + 1 - first] - CR[rg, To - 11 - first])
            base_ = {"T": tm, "n12": int(hs.sum()), "n3": int(((m >= tm - 3) & (m <= tm - 1) & s_).sum()), "n6": int(((m >= tm - 6) & (m <= tm - 1) & s_).sum()), "n24": int(((m >= tm - 24) & (m <= tm - 1) & s_).sum()),
                     "recency": min(recency, 24), "seas": int(((m >= tm - 11) & (m <= tm - 6) & s_).sum()), "month": (tm) % 12, "tot12": int(((m >= tm - 12) & (m <= tm - 1)).sum()), "tot6": int(((m >= tm - 6) & (m <= tm - 1)).sum()),
                     "share": float(hs.sum() / max(1, ((m >= tm - 12) & (m <= tm - 1)).sum())), "nb": int(((m10 >= tm - 12) & (m10 <= tm - 1) & s10).sum()), "reg_yoy": (r6 + 1) / (rp + 1), "reg_n12": r12,
                     "size": areas[i], "rent12": np.nan, "rent6": np.nan, "turn": np.nan}
            for mu in MULTS:
                P = mu * ref; band = (p >= 0.9 * P) & (p <= 1.1 * P); r = dict(base_); r["mult"] = mu; r["nBand12"] = int((hs & band).sum()); r["fwd"] = int((f & band).sum())
                if ak is not None: am, apr = ak; r["aptBand12"] = int(((am >= tm - 12) & (am <= tm - 1) & (apr >= 0.9 * P) & (apr <= 1.1 * P)).sum())
                else: r["aptBand12"] = np.nan
                rec.append(r)
    V = pd.DataFrame(rec); V["T"] = V["T"].astype(int); print(f"빌라 행 {len(V):,}", flush=True)
    Tu = sorted(V["T"].unique()); cut = Tu[int(len(Tu) * 0.55)]
    # 빌라에서 n12는 '평형대 12개월 거래'이므로 가격대 거래(nBand12)와 구분: 모델 입력은 같은 이름 사용
    return run_models(V, "T", cut, last - H, "fwd", "빌라", set(V.columns) | {"aptBand12"}), len(keys)


def main():
    out = {}
    out["아파트"], n = apt(); out["아파트 단위 수"] = n
    out["빌라"], n = villa(); out["빌라 위치×평형 수"] = n
    txt = json.dumps(out, ensure_ascii=False, indent=1); print(txt)
    json.dump(out, open("backtest-liquidity-best.json", "w"), ensure_ascii=False, indent=1)
    if os.environ.get("GITHUB_STEP_SUMMARY"): open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("```json\n" + txt + "\n```\n")


if __name__ == "__main__":
    main()
