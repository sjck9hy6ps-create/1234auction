"""팔리는 곳 판정 시험(2026-11-24, 사용자: "거래량으로만 팔린다/안 팔린다를 판정, 아파트=회전율, 빌라=생활권 거래량을 매달 한 칸씩 미는 6개월 합으로 과거와 현재 비교").
대상: 아파트 = 단지(회전율은 K-apt 세대수가 있는 단지만), 빌라 = 경매 사건 위치 반경 500m 생활권.
방법: 오늘 기준 3·6·9·12개월 전을 시점 T로 잡고, T까지의 거래만으로 예측해 T 이후 실제 월평균 거래와 비교(되팔림 자료는 쓰지 않음).
  예측 방식(월평균 거래 예측)
   - 현재 앱 방식: 최근 6개월 합(W0)  /  12개월 합  /  구간 비교(최근6개월 vs 직전6개월, 절반만 반영해 이어 그리기)
   - 새 방식(매달 미는 6개월 합 W0..W5, 한 달씩 민 값): 최근 합 W0 / 미는 합 6개의 평균 / 미는 합의 기울기를 절반만 반영해 이어 그리기
  지표: 순위 일치(스피어만), 월평균 오차(절대), '이후 거래 0건'을 알아맞히는 정도(AUC), 예측 하위 30%의 실제 0건 비율
"""
import os, re, json, importlib.util
import numpy as np, pandas as pd
import requests
from scipy.spatial import cKDTree
from scipy.stats import spearmanr, mannwhitneyu

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "backtest-villa.py")); bv = importlib.util.module_from_spec(_s); _s.loader.exec_module(bv)
avm = bv.avm
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
FLT = "&or=(" + ",".join('region.like."' + n + '*"' for n in ("서울", "인천", "경기")) + ")"


def ymi(deal_date):
    d = pd.to_numeric(deal_date, errors="coerce")
    return ((d // 10000) * 12 + (d // 100 % 100) - 1).astype("Int64")


def preds(M, T):
    """M: 단위×월 거래건수. T: 시점 열 번호(포함). 월평균 예측들."""
    W = [M[:, T - k - 5:T - k + 1].sum(axis=1) for k in range(0, 12)]   # W[k] = k개월 전에 끝나는 6개월 합 (매달 한 칸씩 민 값)
    W0 = W[0]; W6 = W[6]
    s = np.polyfit(np.arange(6), np.vstack([W[5 - i] for i in range(6)]), 1)[0]   # 한 달당 기울기(오래된→최근)
    P = {
        "A 최근6개월 합(앱 지금)": W0 / 6.0,
        "B 최근12개월 합": (W0 + W6) / 12.0,
        "C 구간 비교(최근6 vs 직전6)": np.maximum(0, W0 + 0.5 * (W0 - W6)) / 6.0,
        "D 미는 6개월 합 평균": np.mean(np.vstack(W[:6]), axis=0) / 6.0,
        "E 미는 합 기울기 이어그리기": np.maximum(0, W0 + 3.0 * s) / 6.0,
        "F 미는 합 12칸 평균": np.mean(np.vstack(W), axis=0) / 6.0,
    }
    return P


def auc_dead(pred, dead):
    """dead(이후 0건)인 단위가 pred가 더 낮을수록 높은 확률로 맞히는 정도(0.5=무작위)."""
    if dead.sum() < 20 or (~dead).sum() < 20: return None
    u = mannwhitneyu(pred[dead], pred[~dead], alternative="less")
    return float(u.statistic / (dead.sum() * (~dead).sum()) * -1 + 1) if False else float(1 - u.statistic / (dead.sum() * (~dead).sum()))


def evaluate(M, last, label, extra=None):
    out = {}
    for back in (3, 6, 9, 12):
        T = last - back; H = back
        fwd = M[:, T + 1:last + 1].sum(axis=1).astype(float) / H
        hist = M[:, T - 16:T + 1].sum(axis=1)
        keep = hist > 0 if label.startswith("아파트") else np.ones(len(M), bool)   # 아파트는 최근 거래가 있던 단지만(앞 시험과 같은 대상)
        P = preds(M, T)
        res = {"n": int(keep.sum()), "이후 거래0건 비율%": round(float((fwd[keep] == 0).mean()) * 100, 1)}
        dead = fwd[keep] == 0
        for name, p in P.items():
            p = p[keep]
            r = spearmanr(p, fwd[keep])[0]
            mae = float(np.abs(p - fwd[keep]).mean())
            a = auc_dead(p, dead)
            lo = p <= np.quantile(p, 0.30)
            res[name] = {"순위일치": round(float(r), 3), "월평균오차": round(mae, 3), "0건AUC": None if a is None else round(a, 3), "하위30%중 실제0건%": round(float((fwd[keep][lo] == 0).mean()) * 100, 1)}
        if extra is not None:
            for name, fn in extra.items():
                p = fn(M, T)[keep]; ok = ~np.isnan(p)
                if ok.sum() >= 100:
                    a = auc_dead(p[ok], dead[ok])
                    res[name] = {"순위일치": round(float(spearmanr(p[ok], fwd[keep][ok])[0]), 3), "0건AUC": None if a is None else round(a, 3), "대상": int(ok.sum())}
        out[f"{back}개월"] = res
    return out


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
    print(f"빌라 거래 {len(df):,}건, 좌표 있는 거래 {len(D):,}건", flush=True)
    D["ymi"] = ymi(D["deal_date"]).astype(int); last = int(D["ymi"].max()) - 1; first = int(D["ymi"].min())
    X = np.c_[D["lat"].values * 111.0, D["lon"].values * 111.0 * np.cos(np.radians(37.5))]; tree = cKDTree(X)
    cases = requests.get(f"{SITE}/api/auction?kind=bidCases", timeout=300).json()
    pts = {}
    for c in cases:
        if not any(k in str(c.get("propertyType") or "") for k in ("다세대", "연립", "도시형")): continue
        if not str(c.get("addrJibun", "")).startswith(("서울", "경기", "인천")): continue
        lat, lon = c.get("lat"), c.get("lon")
        if lat and lon: pts[(round(float(lat), 4), round(float(lon), 4))] = 1
    P = np.array([[la * 111.0, lo * 111.0 * np.cos(np.radians(37.5))] for la, lo in pts])
    print(f"생활권 위치 {len(P):,}곳, 거래 기간 {first // 12}-{first % 12 + 1:02d} ~ {last // 12}-{last % 12 + 1:02d}", flush=True)
    L = last - first + 1; M = np.zeros((len(P), L), dtype=np.int32); ym = D["ymi"].values - first
    for i, nb in enumerate(tree.query_ball_point(P, 0.5)):
        if nb: M[i] = np.bincount(ym[nb], minlength=L)
    return evaluate(M, L - 1, "빌라 생활권(반경 500m)"), len(P)


def nm(x):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", avm.normalize_complex_name(x or "")).replace("아파트", "")


def apt():
    raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,floor,deal_date,dealing_type", extra_filter="&deal_date=gte.20210101")
    df = raw[raw["dealing_type"] != "직거래"].copy() if "dealing_type" in raw.columns else raw.copy()
    for c in ("price", "size", "deal_date"): df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["price", "size", "deal_date", "region", "dong", "danji"]); df = df[(df["price"] > 0) & (df["size"] > 10)]
    df["ymi"] = ymi(df["deal_date"]).astype(int); last = int(df["ymi"].max()) - 1; first = int(df["ymi"].min())
    df["dong1"] = df["dong"].astype(str).str.split().str[-1]
    df["ckey"] = df["region"].astype(str) + "|" + df["dong1"] + "|" + df["danji"].astype(str)
    keys = df["ckey"].unique(); kid = {k: i for i, k in enumerate(keys)}
    L = last - first + 1; M = np.zeros((len(keys), L), dtype=np.int32)
    g = df[df["ymi"] <= last].groupby(["ckey", "ymi"], observed=True).size()
    for (k, m), n in g.items(): M[kid[k], m - first] = n
    # 세대수: 같은 동·정규화 단지명이 K-apt에서 하나로 특정될 때만
    kp = avm.fetch_all_rows("kapt_complex_info", cols="kapt_code,kapt_name,as3,households", order_col="kapt_code", extra_filter="&households=gt.0")
    hmap = {}
    for r in kp.itertuples():
        key = (str(r.as3).strip().split()[-1] if r.as3 else "", nm(r.kapt_name)); hmap.setdefault(key, set()).add(int(r.households))
    hh = np.full(len(keys), np.nan)
    for k, i in kid.items():
        p = k.split("|"); v = hmap.get((p[1], nm(p[2])))
        if v and len(v) == 1: hh[i] = next(iter(v))
    print(f"아파트 단지 {len(keys):,}곳, 세대수 연결 {int(np.isfinite(hh).sum()):,}곳", flush=True)
    extra = {
        "G 회전율(최근6개월÷세대수)": lambda M_, T: preds(M_, T)["A 최근6개월 합(앱 지금)"] / hh,
        "H 회전율(미는 합 평균÷세대수)": lambda M_, T: preds(M_, T)["D 미는 6개월 합 평균"] / hh,
        "I 거래량 같은 단지만(최근6개월·비교용)": lambda M_, T: np.where(np.isfinite(hh), preds(M_, T)["A 최근6개월 합(앱 지금)"], np.nan),
    }
    return evaluate(M, L - 1, "아파트 단지", extra), len(keys)


def main():
    out = {}
    out["빌라"], n = villa(); out["빌라 위치 수"] = n
    out["아파트"], n = apt(); out["아파트 단지 수"] = n
    txt = json.dumps(out, ensure_ascii=False, indent=1); print(txt)
    json.dump(out, open("backtest-liquidity-rolling.json", "w"), ensure_ascii=False, indent=1)
    if os.environ.get("GITHUB_STEP_SUMMARY"): open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("```json\n" + txt + "\n```\n")


if __name__ == "__main__":
    main()
