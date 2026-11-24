"""팔리는 곳 판정 3차(2026-11-24, 사용자: 아파트=단지 안에서 그 평형이 잘 팔리는지, 빌라=생활권에서 잘 팔리는 평형대·인정되는 가격대·같은 가격대 아파트와의 경쟁).
1) 아파트: 단지×면적대 단위. 같은 단지의 12개월 거래 중 그 평형 비중(균등 몫 대비 배수)이 같은 거래 건수에서도 이후 0건을 가려내는지.
2) 빌라 평형대 수요: 생활권(반경 500m) 안 비슷한 면적(±15㎡)의 12개월 거래 vs 면적 무관 거래.
3) 빌라 가격대 인정: 예상매도가(그 시점 앱이 낸 값)가 같은 생활권·같은 평형 12개월 거래가 분포의 어디쯤인지, 예상매도가 ±10% 가격대 거래가 이후에도 나는지.
4) 빌라 대체재: 같은 법정동에서 예상매도가 ±10% 가격대 아파트 거래가 많으면 같은 가격대 빌라 거래가 줄어드는지.
대상: 이후 6개월 같은 평형 같은 가격대(±10%) 빌라 거래(빌라), 이후 6개월 같은 단지 같은 면적대 거래(아파트). 시점 이후 자료는 쓰지 않음, 시간순 학습/시험. 시험 시점은 오늘 기준 3·6·9·12개월 4구간(누적)."""
import os, re, json, importlib.util
import numpy as np, pandas as pd
from scipy.spatial import cKDTree
from scipy.stats import rankdata

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py")); bv = importlib.util.module_from_spec(_s); _s.loader.exec_module(bv)
avm = bv.avm
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"
H = 6
RNG = np.random.default_rng(11)


def ymi(deal_date):
    d = pd.to_numeric(deal_date, errors="coerce")
    return ((d // 10000) * 12 + (d // 100 % 100) - 1).astype("Int64")


def auc_low_dead(score, dead):
    nd = int(dead.sum()); nl = len(dead) - nd
    if nd < 20 or nl < 20: return None
    r = rankdata(score + RNG.normal(0, 1e-9, len(score)))
    return round(float(1 - (r[dead].sum() - nd * (nd + 1) / 2) / (nd * nl)), 4)


def ols_eval(Xtr, ytr, Xte, yte):
    A = np.column_stack([np.ones(len(ytr)), Xtr]); b, *_ = np.linalg.lstsq(A, ytr, rcond=None)
    p = np.column_stack([np.ones(len(yte)), Xte]) @ b
    return p, float(1 - ((yte - p) ** 2).sum() / ((yte - yte.mean()) ** 2).sum())


# ───────────────────────── 1) 아파트: 단지 안 평형 인기 ─────────────────────────
def apt_band():
    raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,floor,deal_date,dealing_type", extra_filter="&deal_date=gte.20210101")
    df = raw[raw["dealing_type"] != "직거래"].copy() if "dealing_type" in raw.columns else raw.copy()
    for c in ("price", "size", "deal_date"): df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["price", "size", "deal_date", "region", "dong", "danji"]); df = df[(df["price"] > 0) & (df["size"] > 10)]
    df["ymi"] = ymi(df["deal_date"]).astype(int); last = int(df["ymi"].max()) - 1; first = int(df["ymi"].min()); L = last - first + 1
    df = df[df["ymi"] <= last]; last = L - 1   # 이하 '월 번호'는 첫 달=0 기준 열 번호
    df["dong1"] = df["dong"].astype(str).str.split().str[-1].fillna("")
    df["ckey"] = df["region"].astype(str) + "|" + df["dong1"] + "|" + df["danji"].astype(str)
    df["band"] = (df["size"] / 5.0).round().astype(int)
    ub = df["ckey"] + "#" + df["band"].astype(str); codes, uniq = pd.factorize(ub)
    ccode, _ = pd.factorize(df["ckey"]); u2c = np.zeros(len(uniq), dtype=np.int64); u2c[codes] = ccode
    ym = df["ymi"].values - first
    M = np.zeros((len(uniq), L), dtype=np.int16); np.add.at(M, (codes, ym), 1)
    C = np.concatenate([np.zeros((M.shape[0], 1), dtype=np.int32), np.cumsum(M, axis=1, dtype=np.int32)], axis=1); del M
    nc = int(u2c.max()) + 1
    S = lambda a, b: C[:, b + 1] - C[:, a]
    Tstart = 2023 * 12 - first; Ts = list(range(Tstart, last - H + 1)); cut = Ts[int(len(Ts) * 0.55)]
    rows = []
    for T in Ts:
        Tobs = T - 1
        n12 = S(Tobs - 11, Tobs).astype(float); hist24 = S(Tobs - 23, Tobs)
        keep = (hist24 > 0) & (n12 >= 2)                      # 지금 규칙(12개월 2건 이상)을 통과한 평형만
        tot = np.bincount(u2c, weights=n12, minlength=nc); nb = np.bincount(u2c, weights=(n12 > 0).astype(float), minlength=nc)
        ratio = n12 / np.maximum(tot[u2c] / np.maximum(nb[u2c], 1), 1e-9)   # 균등 몫 대비 배수
        share = n12 / np.maximum(tot[u2c], 1)
        fwd = S(T + 1, T + H).astype(float)
        rows.append((T, n12[keep], ratio[keep], share[keep], tot[u2c][keep], nb[u2c][keep], fwd[keep]))
    def pack(rs): return {k: np.concatenate([r[i] for r in rs]) for i, k in enumerate(("T", "n12", "ratio", "share", "tot", "nb", "fwd")) if k != "T"} | {"T": np.concatenate([np.full(len(r[1]), r[0]) for r in rs])}
    tr = pack([r for r in rows if r[0] + H < cut]); res = {}
    def X(D): return np.column_stack([np.log1p(D["n12"]), np.log(np.clip(D["ratio"], 0.05, 20)), np.log1p(D["tot"])])
    for back in (3, 6, 9, 12):
        D = pack([r for r in rows if r[0] >= cut and r[0] >= last - H - (back - 1)])
        y = np.log1p(D["fwd"]); dead = D["fwd"] == 0
        tier = np.where((D["ratio"] >= 1.2), "활발", np.where((D["ratio"] <= 0.5) | (D["n12"] <= 1), "비활발", "보통"))
        out = {"행수": int(len(y)), "이후 0건 비율%": round(100 * float(dead.mean()), 1)}
        out["평형 인기 등급별"] = {t: {"행수": int((tier == t).sum()), "이후 0건%": round(100 * float(dead[tier == t].mean()), 1), "이후 평균 거래": round(float(D["fwd"][tier == t].mean()), 2)} for t in ("활발", "보통", "비활발") if (tier == t).sum() >= 30}
        strata = {}
        for lo, hi, lab in ((2, 4, "12개월 2~4건"), (5, 9, "5~9건"), (10, 19, "10~19건"), (20, 10 ** 9, "20건+")):
            m = (D["n12"] >= lo) & (D["n12"] <= hi)
            if m.sum() < 200: continue
            strata[lab] = {t: {"행수": int((m & (tier == t)).sum()), "이후 0건%": round(100 * float(dead[m & (tier == t)].mean()), 1)} for t in ("활발", "보통", "비활발") if (m & (tier == t)).sum() >= 50}
        out["같은 거래 건수 안에서 등급별"] = strata
        # 모델: 12개월 건수만 vs + 평형 비중
        p0, r0 = ols_eval(X(tr)[:, :1], np.log1p(tr["fwd"]), X(D)[:, :1], y)
        p1, r1 = ols_eval(X(tr)[:, :2], np.log1p(tr["fwd"]), X(D)[:, :2], y)
        p2, r2 = ols_eval(X(tr), np.log1p(tr["fwd"]), X(D), y)
        out["건수만"] = {"R2": round(r0, 4), "0건AUC": auc_low_dead(p0, dead)}
        out["건수+평형비중"] = {"R2": round(r1, 4), "0건AUC": auc_low_dead(p1, dead)}
        out["건수+평형비중+단지규모"] = {"R2": round(r2, 4), "0건AUC": auc_low_dead(p2, dead)}
        flag = tier == "비활발"
        out["비활발 평형 걸러내면"] = {"거른비율%": round(100 * float(flag.mean()), 1), "이후0건 중 잡은%": round(100 * float((flag & dead).sum() / max(1, dead.sum())), 1), "걸러진 것 중 실제 0건%": round(100 * float((flag & dead).sum() / max(1, flag.sum())), 1), "걸러진 것 중 이후 2건+%": round(100 * float((flag & (D["fwd"] >= 2)).sum() / max(1, flag.sum())), 1)}
        res[f"{back}개월"] = out
    return res, len(uniq)


# ───────────────────────── 2~4) 빌라 ─────────────────────────
def villa_cases():
    raw = avm.fetch_all_rows("villa_trades", cols="region,dong,danji,bunji,road_name,main_num,sub_num,price,size,floor,deal_date,dealing_type,build_year", extra_filter=f"&deal_date=gte.20210101{FLT}")
    df = bv.prep(raw)
    cc = avm.fetch_all_rows("complex_coords", cols="cache_key,lat,lon", order_col="id", extra_filter="&or=(sigungu_cd.like.11*,sigungu_cd.like.28*,sigungu_cd.like.41*)")
    cmap = {r.cache_key: (r.lat, r.lon) for r in cc.itertuples() if r.lat and r.lon}
    mnum = pd.to_numeric(df["main_num"], errors="coerce"); snum = pd.to_numeric(df["sub_num"], errors="coerce")
    base = df["dong"].fillna("").astype(str) + "|" + df["danji"].fillna("").astype(str) + "|" + df["bunji"].fillna("").astype(str) + "|" + df["road_name"].fillna("").astype(str) + "|"
    k_new = (base + mnum.fillna(0).astype(int).astype(str) + "|" + snum.fillna(0).astype(int).astype(str).where(snum.fillna(0) > 0, "")).str.lower()
    k_leg = (base + mnum.map(lambda v: "" if pd.isna(v) else str(int(v))) + "|" + snum.map(lambda v: "" if pd.isna(v) else str(int(v)))).str.lower()
    co = k_new.map(cmap).where(lambda s: s.notna(), k_leg.map(cmap))
    df["lat"] = co.map(lambda x: x[0] if isinstance(x, tuple) else np.nan); df["lon"] = co.map(lambda x: x[1] if isinstance(x, tuple) else np.nan)
    D = df[df["lat"].notna()].reset_index(drop=True)
    D["ymi"] = ymi(D["deal_date"]).astype(int); last = int(D["ymi"].max()) - 1; first = int(D["ymi"].min())
    tree = cKDTree(np.c_[D["lat"].values * 111.0, D["lon"].values * 111.0 * np.cos(np.radians(37.5))])
    ym = D["ymi"].values; sz = D["size"].values.astype(float); pr = D["price"].values.astype(float)
    # 아파트 거래(같은 법정동·가격대 대체재)
    raw_a = avm.fetch_all_rows("house_trades", cols="region,dong,price,size,deal_date,dealing_type", extra_filter="&deal_date=gte.20210101")
    ap = raw_a[raw_a["dealing_type"] != "직거래"].copy() if "dealing_type" in raw_a.columns else raw_a.copy()
    for c in ("price", "size", "deal_date"): ap[c] = pd.to_numeric(ap[c], errors="coerce")
    ap = ap.dropna(subset=["price", "deal_date", "region", "dong"]); ap["ymi"] = ymi(ap["deal_date"]).astype(int)
    ap["k"] = ap["region"].astype(str) + "|" + ap["dong"].astype(str).str.split().str[-1].fillna("")
    amap = {k: (g["ymi"].values, g["price"].values.astype(float)) for k, g in ap.groupby("k")}
    import requests
    SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
    cs = requests.get(f"{SITE}/api/auction?kind=bidCases", timeout=300).json(); pts_d = {}
    for c in cs:
        if not any(k in str(c.get("propertyType") or "") for k in ("다세대", "연립", "도시형")): continue
        if not str(c.get("addrJibun", "")).startswith(("서울", "경기", "인천")): continue
        lat, lon = c.get("lat"), c.get("lon")
        try: ar = float(c.get("areaM2"))
        except Exception: continue
        if lat and lon and ar > 0: pts_d[(round(float(lat), 4), round(float(lon), 4), int(round(ar / 5.0)))] = 1
    keys = list(pts_d); pts = np.array([[k[0] * 111.0, k[1] * 111.0 * np.cos(np.radians(37.5))] for k in keys]); areas = np.array([k[2] * 5.0 for k in keys])
    nbs = tree.query_ball_point(pts, 0.5); _, near = tree.query(pts, k=1)
    reg_n = D["region"].astype(str).values; dong_n = D["dong"].astype(str).str.split().str[-1].fillna("").values
    Ts = list(range(2023 * 12 - first, last - H + 1, 3)); MULTS = (0.8, 1.0, 1.25, 1.5)
    rec = []; aptkey_hit = 0
    for i, nb in enumerate(nbs):
        if not nb: continue
        nb = np.array(nb); m = ym[nb]; s_ = np.abs(sz[nb] - areas[i]) <= 15; p = pr[nb]
        a = amap.get(reg_n[near[i]] + "|" + dong_n[near[i]])
        if a is not None: aptkey_hit += 1
        for tm in Ts:
            h = (m >= tm - 12) & (m <= tm - 1); hs = h & s_
            if hs.sum() < 3: continue
            ref = float(np.median(p[hs])); f = (m >= tm + 1) & (m <= tm + H) & s_
            for mult in MULTS:
                P = mult * ref; band = (p >= 0.9 * P) & (p <= 1.1 * P)
                r = {"tm": tm, "mult": mult, "nAll12": int(h.sum()), "nSame12": int(hs.sum()), "nBand12": int((hs & band).sum()), "nBandAll12": int((h & band).sum()), "fBand": int((f & band).sum())}
                if a is not None:
                    am, apr = a; ah = (am >= tm - 12) & (am <= tm - 1); r["nApt12"] = int((ah & (apr >= 0.9 * P) & (apr <= 1.1 * P)).sum())
                else: r["nApt12"] = np.nan
                rec.append(r)
    R = pd.DataFrame(rec); print(f"빌라 위치×평형 {len(keys):,}곳 · 시점×가격대 조합 {len(R):,}건(아파트 같은 동 거래 연결 위치 {aptkey_hit:,}곳)", flush=True)
    R["aptShare"] = R["nApt12"] / (R["nApt12"] + R["nBandAll12"] + 1.0); R["pct"] = np.nan
    R = R.sort_values("tm").reset_index(drop=True); cut = int(np.quantile(R["tm"], 0.55)); cut = Ts[min(range(len(Ts)), key=lambda j: abs(Ts[j] - cut))]
    TR = R[R["tm"] + H < cut]; TE = R[R["tm"] >= cut]
    def feats(D, names):
        cols = []
        for nm in names:
            if nm == "lnAll": cols.append(np.log1p(D["nAll12"]))
            elif nm == "lnSame": cols.append(np.log1p(D["nSame12"]))
            elif nm == "shareSame": cols.append(D["nSame12"] / (D["nAll12"] + 1.0))
            elif nm == "lnBand": cols.append(np.log1p(D["nBand12"]))
            elif nm == "logm": cols.append(np.log(D["mult"]))
            elif nm == "hi": cols.append((D["mult"] > 1.1).astype(float))
            elif nm == "apt": cols.append(D["aptShare"].fillna(D["aptShare"].median()))
        return np.column_stack(cols).astype(float)
    MODELS = {"V0 면적무관 12개월(앱 지금)": ["lnAll"], "V1 같은 평형대 12개월": ["lnSame"], "V2 평형대+비중": ["lnSame", "shareSame"], "V3 평형대+그 가격대 12개월 거래": ["lnSame", "lnBand"],
              "V4 +시세 대비 가격대(높을수록)": ["lnSame", "lnBand", "logm", "hi"], "V5 +같은 가격대 아파트 비중": ["lnSame", "lnBand", "logm", "hi", "apt"], "V6 평형대+가격대 위치+아파트 비중": ["lnSame", "logm", "hi", "apt"]}
    res = {}; last_ok = last - H
    for back in (3, 6, 9, 12, 999):
        Dt = TE[TE["tm"] >= last_ok - (back - 1) - 2] if back < 999 else TE
        if len(Dt) < 200: continue
        y = np.log1p(Dt["fBand"].values.astype(float)); dead = Dt["fBand"].values == 0
        out = {"행수": int(len(Dt)), "이후 같은 가격대 거래 0건%": round(100 * float(dead.mean()), 1)}
        for nm, names in MODELS.items():
            p, r2 = ols_eval(feats(TR, names), np.log1p(TR["fBand"].values.astype(float)), feats(Dt, names), y)
            out[nm] = {"R2": round(r2, 4), "0건AUC": auc_low_dead(p, dead)}
        bk = lambda m: {"행수": int(m.sum()), "이후0건%": round(100 * float(dead[m.values].mean()), 1), "이후 평균 거래": round(float(Dt["fBand"].values[m.values].mean()), 2)} if m.sum() >= 50 else None
        sm = Dt["nSame12"]
        out["시세 대비 가격대별(같은 평형 12개월 거래가 중앙값 대비)"] = {f"{mu}배": {"전체": bk(Dt["mult"] == mu), "같은평형 12개월 5건 이상": bk((Dt["mult"] == mu) & (sm >= 5)), "5건 미만": bk((Dt["mult"] == mu) & (sm < 5))} for mu in MULTS}
        asr = Dt["aptShare"]; at1 = Dt["mult"] == 1.0
        out["같은 가격대 아파트 비중(시세 1.0배, 같은 평형 거래 5건+)"] = {lab: bk(at1 & (sm >= 5) & m) for lab, m in (("20% 미만", asr < 0.2), ("20~50%", (asr >= 0.2) & (asr < 0.5)), ("50% 이상", asr >= 0.5))}
        out["같은 평형대 12개월 거래(시세 1.0배)"] = {lab: bk(at1 & m) for lab, m in (("3~4건", (sm >= 3) & (sm <= 4)), ("5~9건", (sm >= 5) & (sm <= 9)), ("10건+", sm >= 10))}
        res["전체 시험구간" if back == 999 else f"{back}개월"] = out
    return res


def main():
    out = {}
    out["빌라(평형대·가격대·아파트 경쟁)"] = villa_cases()
    out["아파트 단지 내 평형 인기"], n = apt_band(); out["아파트 단위 수"] = n
    txt = json.dumps(out, ensure_ascii=False, indent=1); print(txt)
    json.dump(out, open("backtest-liquidity-band.json", "w"), ensure_ascii=False, indent=1)
    if os.environ.get("GITHUB_STEP_SUMMARY"): open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("```json\n" + txt + "\n```\n")


if __name__ == "__main__":
    main()
