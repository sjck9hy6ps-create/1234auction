"""팔리는 곳 판정 시험 2차(2026-11-24, 1차의 약점 보완).
1차 약점: ①규모 효과(큰 곳이 당연히 거래 많음) ②맞히는 대상이 같은 평형 거래가 아님 ③시점 4개뿐·겹침 ④신고 지연 미반영.
보완
 - 매달 시점(2023-01 ~ 마지막 완성 달-6개월)마다 평가. 시점마다 '그때까지 알 수 있던' 거래만 사용(마지막 한 달은 신고 지연으로 빼고 계산).
 - 대상: 같은 평형 이후 6개월 거래(아파트=같은 단지 같은 면적대(5㎡ 단위), 빌라=반경 500m 안 비슷한 면적 ±15㎡, 경매 사건 위치·면적마다).
 - 시간 순서로 나눠 앞쪽(학습)으로 식을 만들고 뒤쪽(시험)에서만 평가. 시험 시점은 오늘 기준 3·6·9·12개월 4구간(누적)으로 보고.
 - 추세가 '수준을 이미 알 때 추가 정보'를 주는지: 식 비교(수준만 / 6개월 / 12칸 평균 / +추세 / +전부).
 - 실제 규칙 비교: 지금 규칙(최근 6개월 같은 평형 0건)과 같은 비율을 걸러 낼 때 새 점수가 '이후 0건'을 더 많이 잡는지.
 - 아파트 회전율: 단지별 이후 회전율(거래÷세대수)을 맞히는 정도를 세대수 구간 안에서 비교(규모 통제).
"""
import os, re, json, importlib.util
import numpy as np, pandas as pd
import requests
from scipy.spatial import cKDTree
from scipy.stats import rankdata, spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py")); bv = importlib.util.module_from_spec(_s); _s.loader.exec_module(bv)
avm = bv.avm
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"
H = 6
RNG = np.random.default_rng(7)


def ymi(deal_date):
    d = pd.to_numeric(deal_date, errors="coerce")
    return ((d // 10000) * 12 + (d // 100 % 100) - 1).astype("Int64")


def auc_low_dead(score, dead):
    """score가 낮을수록 '이후 0건'일 확률이 높다고 볼 때의 맞히는 정도(0.5=무작위)."""
    nd = int(dead.sum()); nl = len(dead) - nd
    if nd < 30 or nl < 30: return None
    r = rankdata(score)
    return float(1 - (r[dead].sum() - nd * (nd + 1) / 2) / (nd * nl))


def features(C, Tobs):
    """C: 누적합(단위×(월+1)), Tobs: 마지막으로 알 수 있는 달 번호. S(a,b)=a..b월 합."""
    S = lambda a, b: C[:, b + 1] - C[:, a]
    W = [S(Tobs - k - 5, Tobs - k) for k in range(12)]
    W0, W6 = W[0], W[6]
    lvl6, lvl12 = W0, W0 + W6
    f12 = np.mean(np.vstack(W), axis=0)
    f6 = np.mean(np.vstack(W[:6]), axis=0)
    x = np.arange(6) - 2.5; Wm = np.vstack([W[5 - i] for i in range(6)])
    slope = (x[:, None] * (Wm - Wm.mean(axis=0))).sum(axis=0) / (x ** 2).sum()
    return {"lvl6": lvl6.astype(float), "lvl12": lvl12.astype(float), "f12": f12, "f6": f6,
            "g_old": (W0 - W6) / (W0 + W6 + 1.0), "g_roll": slope * 5 / (f6 + 1.0)}


def ols(X, y):
    b, *_ = np.linalg.lstsq(X, y, rcond=None); return b


def build(Fs, keep_masks, ys, deads):
    """시점별 특징을 하나로 합침."""
    out = {}
    for k in Fs[0]: out[k] = np.concatenate([f[k][m] for f, m in zip(Fs, keep_masks)])
    out["y"] = np.concatenate([y[m] for y, m in zip(ys, keep_masks)]); out["dead"] = np.concatenate([d[m] for d, m in zip(deads, keep_masks)])
    return out


def run_panel(C, L, label, Tstart):
    """L=마지막 완성 달의 열 번호+1(열 0..L-1이 완성된 달). 시점 T(마지막으로 거래를 '아는' 달 = T-1)."""
    last = L - 1
    Ts = [T for T in range(Tstart, last - H + 1)]            # T ≤ last-6 : 이후 6개월이 모두 완성
    rows = []; meta = []
    S = lambda a, b: C[:, b + 1] - C[:, a]
    for T in Ts:
        Tobs = T - 1                                          # 신고 지연: 평가 시점의 마지막 달은 빼고 계산
        hist = S(Tobs - 23, Tobs)
        keep = hist > 0                                       # 최근 24개월 안에 거래가 있었던 단위만(앞 시험과 같은 대상)
        F = features(C, Tobs)
        fwd = S(T + 1, T + H).astype(float)
        rows.append((T, F, keep, fwd))
    cut = Ts[int(len(Ts) * 0.55)]
    tr = [r for r in rows if r[0] + H < cut]; te = [r for r in rows if r[0] >= cut]
    pack = lambda rs: build([r[1] for r in rs], [r[2] for r in rs], [np.log1p(r[3]) for r in rs], [r[3] == 0 for r in rs])
    TR = pack(tr)
    MODELS = {
        "M0 수준만(12개월 합)": lambda D: [np.log1p(D["lvl12"])],
        "M1 최근6개월 합(앱 지금)": lambda D: [np.log1p(D["lvl6"])],
        "M2 미는 6개월 합 12칸 평균": lambda D: [np.log1p(D["f12"])],
        "M3 수준+기존 추세(최근6 vs 직전6)": lambda D: [np.log1p(D["lvl12"]), D["g_old"]],
        "M4 수준+미는 추세(기울기)": lambda D: [np.log1p(D["lvl12"]), D["g_roll"]],
        "M5 12칸 평균+6개월+추세 모두": lambda D: [np.log1p(D["f12"]), np.log1p(D["lvl6"]), D["g_old"], D["g_roll"]],
    }
    coefs = {}
    for name, fn in MODELS.items():
        X = np.column_stack([np.ones(len(TR["y"]))] + fn(TR)); coefs[name] = ols(X, TR["y"])
    res = {}
    for back in (3, 6, 9, 12):
        sel = [r for r in te if r[0] >= last - H - (back - 1)]    # 오늘 기준 가장 최근 평가 가능 시점부터 back개월
        if not sel: continue
        D = pack(sel); y = D["y"]; dead = D["dead"]
        out = {"행수": int(len(y)), "이후 0건 비율%": round(float(dead.mean()) * 100, 1), "시점수": len(sel)}
        sst = ((y - y.mean()) ** 2).sum()
        for name, fn in MODELS.items():
            X = np.column_stack([np.ones(len(y))] + fn(D)); p = X @ coefs[name]
            out[name] = {"설명력R2": round(float(1 - ((y - p) ** 2).sum() / sst), 4), "0건AUC": None if (a := auc_low_dead(p + RNG.normal(0, 1e-9, len(p)), dead)) is None else round(a, 4)}
        # 실제 규칙 비교: 지금 규칙(최근 6개월 0건)이 거르는 비율만큼 새 점수로 걸렀을 때
        flagA = D["lvl6"] == 0; share = float(flagA.mean())
        def flag_stats(flag):
            n = int(flag.sum());
            return {"거른비율%": round(100 * n / len(flag), 1), "이후0건 중 잡은%": round(100 * float((flag & dead).sum() / max(1, dead.sum())), 1), "걸러진 것 중 실제 0건%": round(100 * float((flag & dead).sum() / max(1, n)), 1), "걸러진 것 중 이후 2건+%": round(100 * float((flag & (np.expm1(y) >= 2)).sum() / max(1, n)), 1)}
        out["규칙 지금(최근6개월 0건)"] = flag_stats(flagA)
        for kk in (0, 1, 2, 3, 4):   # 12개월 합이 kk건 이하면 거름(기준값 정하기용)
            out[f"규칙 12개월 합≤{kk}건"] = flag_stats(D["lvl12"] <= kk)
        for nm_, key in (("규칙 12칸 평균", "f12"), ("규칙 12개월 합", "lvl12")):
            sc = D[key] + RNG.normal(0, 1e-6, len(y)); k = max(1, int(share * len(y)))
            thr = np.sort(sc)[k - 1]; out[nm_ + "(같은 비율)"] = flag_stats(sc <= thr)
        res[f"{back}개월"] = out
    return res


def type_matrix(codes, ym, first, L, nunits):
    M = np.zeros((nunits, L), dtype=np.int16)
    ok = (ym >= 0) & (ym < L)
    np.add.at(M, (codes[ok], ym[ok]), 1)
    return M


def to_cum(M): return np.concatenate([np.zeros((M.shape[0], 1), dtype=np.int32), np.cumsum(M, axis=1, dtype=np.int32)], axis=1)


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
    df["lat"] = co.map(lambda x: x[0] if isinstance(x, tuple) else np.nan); df["lon"] = co.map(lambda x: x[1] if isinstance(x, tuple) else np.nan)
    D = df[df["lat"].notna()].reset_index(drop=True)
    D["ymi"] = ymi(D["deal_date"]).astype(int); last = int(D["ymi"].max()) - 1; first = int(D["ymi"].min()); L = last - first + 1
    X = np.c_[D["lat"].values * 111.0, D["lon"].values * 111.0 * np.cos(np.radians(37.5))]; tree = cKDTree(X)
    ym = D["ymi"].values - first; sz = D["size"].values.astype(float)
    cases = requests.get(f"{SITE}/api/auction?kind=bidCases", timeout=300).json()
    pts = {}
    for c in cases:
        if not any(k in str(c.get("propertyType") or "") for k in ("다세대", "연립", "도시형")): continue
        if not str(c.get("addrJibun", "")).startswith(("서울", "경기", "인천")): continue
        lat, lon = c.get("lat"), c.get("lon")
        try: ar = float(c.get("areaM2"))
        except Exception: continue
        if lat and lon and ar > 0: pts[(round(float(lat), 4), round(float(lon), 4), int(round(ar / 5.0)))] = 1
    keys = list(pts); P = np.array([[k[0] * 111.0, k[1] * 111.0 * np.cos(np.radians(37.5))] for k in keys]); areas = np.array([k[2] * 5.0 for k in keys])
    print(f"빌라 사건 위치×면적 {len(keys):,}곳, 기간 {first // 12}-{first % 12 + 1:02d}~{last // 12}-{last % 12 + 1:02d}", flush=True)
    Mt = np.zeros((len(keys), L), dtype=np.int16); Ma = np.zeros((len(keys), L), dtype=np.int16)
    for i, nb in enumerate(tree.query_ball_point(P, 0.5)):
        if not nb: continue
        nb = np.array(nb); m = ym[nb]; ok = m < L
        Ma[i] = np.bincount(m[ok], minlength=L)[:L]
        s = np.abs(sz[nb] - areas[i]) <= 15
        Mt[i] = np.bincount(m[ok & s], minlength=L)[:L]
    Tstart = (2023 * 12) - first
    return {"같은 면적대 기준(반경500m ±15㎡)": run_panel(to_cum(Mt), L, "빌라", Tstart), "면적 무관(반경500m 전체)": run_panel(to_cum(Ma), L, "빌라전체", Tstart)}, len(keys)


def nm(x):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", avm.normalize_complex_name(x or "")).replace("아파트", "")


def apt():
    raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,floor,deal_date,dealing_type", extra_filter="&deal_date=gte.20210101")
    df = raw[raw["dealing_type"] != "직거래"].copy() if "dealing_type" in raw.columns else raw.copy()
    for c in ("price", "size", "deal_date"): df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["price", "size", "deal_date", "region", "dong", "danji"]); df = df[(df["price"] > 0) & (df["size"] > 10)]
    df["ymi"] = ymi(df["deal_date"]).astype(int); last = int(df["ymi"].max()) - 1; first = int(df["ymi"].min()); L = last - first + 1
    df = df[df["ymi"] <= last]
    df["dong1"] = df["dong"].astype(str).str.split().str[-1].fillna("")
    df["ckey"] = df["region"].astype(str) + "|" + df["dong1"] + "|" + df["danji"].astype(str)
    df["band"] = (df["size"] / 5.0).round().astype(int)
    ym = df["ymi"].values - first; Tstart = (2023 * 12) - first
    # 같은 단지 같은 면적대(5㎡) 단위
    ub = df["ckey"] + "#" + df["band"].astype(str); codes, uniq = pd.factorize(ub)
    Mb = type_matrix(codes, ym, first, L, len(uniq)); print(f"아파트 단지×면적대 {len(uniq):,}곳", flush=True)
    res = {"같은 단지 같은 면적대 기준": run_panel(to_cum(Mb), L, "아파트", Tstart)}
    del Mb
    # 단지 전체 + 회전율(세대수 구간 안에서 비교)
    codes2, uniq2 = pd.factorize(df["ckey"]); Mc = type_matrix(codes2, ym, first, L, len(uniq2)); C = to_cum(Mc)
    kp = avm.fetch_all_rows("kapt_complex_info", cols="kapt_code,kapt_name,as3,households", order_col="kapt_code", extra_filter="&households=gt.0")
    hmap = {}
    for r in kp.itertuples():
        key = (str(r.as3).strip().split()[-1] if r.as3 else "", nm(r.kapt_name)); hmap.setdefault(key, set()).add(int(r.households))
    hh = np.full(len(uniq2), np.nan)
    for i, k in enumerate(uniq2):
        p = k.split("|"); v = hmap.get((p[1], nm(p[2])))
        if v and len(v) == 1: hh[i] = next(iter(v))
    okh = np.isfinite(hh); print(f"세대수 연결 단지 {int(okh.sum()):,} / {len(uniq2):,}", flush=True)
    last_c = L - 1; S = lambda a, b: C[:, b + 1] - C[:, a]
    turn = {}
    Ts = list(range(Tstart, last_c - H + 1)); cut = Ts[int(len(Ts) * 0.55)]
    for back in (3, 6, 9, 12):
        vals = {"거래량(최근6개월)": [], "회전율(최근6개월÷세대수)": [], "거래량(12칸 평균)": [], "회전율(12칸 평균÷세대수)": []}
        for T in [t for t in Ts if t >= cut and t >= last_c - H - (back - 1)]:
            Tobs = T - 1; keep = okh & (S(Tobs - 23, Tobs) > 0)
            if keep.sum() < 200: continue
            F = features(C, Tobs); fwd = S(T + 1, T + H).astype(float) / hh
            q = np.digitize(hh, np.nanquantile(hh[keep], [0.25, 0.5, 0.75]))
            for nmv, sc in (("거래량(최근6개월)", F["lvl6"]), ("회전율(최근6개월÷세대수)", F["lvl6"] / hh), ("거래량(12칸 평균)", F["f12"]), ("회전율(12칸 평균÷세대수)", F["f12"] / hh)):
                rs = []
                for g in range(4):
                    m = keep & (q == g)
                    if m.sum() > 100: rs.append(spearmanr(sc[m], fwd[m])[0])
                if rs: vals[nmv].append(float(np.mean(rs)))
        turn[f"{back}개월"] = {k: (round(float(np.mean(v)), 3) if v else None) for k, v in vals.items()}
    res["회전율 비교(세대수 4구간 안에서 이후 회전율과의 순위 일치)"] = turn
    return res, len(uniq)


def main():
    out = {}
    out["빌라"], n = villa(); out["빌라 단위 수"] = n
    out["아파트"], n = apt(); out["아파트 단위 수"] = n
    txt = json.dumps(out, ensure_ascii=False, indent=1); print(txt)
    json.dump(out, open("backtest-liquidity-rolling2.json", "w"), ensure_ascii=False, indent=1)
    if os.environ.get("GITHUB_STEP_SUMMARY"): open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("```json\n" + txt + "\n```\n")


if __name__ == "__main__":
    main()
