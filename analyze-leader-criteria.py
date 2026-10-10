"""
대장아파트 판별 기준 비교 (2026-10-10, 사용자: "대장아파트 판별을 거래량으로 계산했는데 이 기준이 맞아?")
같은 법정동에서 과거 시점(컷오프)마다 그 시점까지의 자료만으로 대장을 뽑고, 그 뒤 4분기 동안 같은 동 나머지 단지가
(시군구 평균 대비) 대장을 따라 움직였는지 채점. 대장의 '최근 4분기 변화'가 '나머지의 다음 4분기 초과 변화'를 얼마나 맞히나.
방법: A 인기(3년 거래량 70%+관심증가 30%, 앱 지방 기준에서 세대수 회전율만 뺀 근사) / V 거래량 최다 / P 평단가 최고 /
      L 시세 선행(나머지 동네보다 1~3분기 먼저 움직인 정도, 상관 0.55↑ - 앱 수도권 기준) / 전체 후보 평균(무작위 단지 기준선)
"""
import os, json, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py"))
cyc = importlib.util.module_from_spec(_s); _s.loader.exec_module(cyc)
avm = cyc.avm
MIN_TRADES = 20
MIN_Q = 8
LEAD_MIN = 0.55


def corr(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = ~(np.isnan(a) | np.isnan(b))
    if m.sum() < 8 or np.std(a[m]) == 0 or np.std(b[m]) == 0:
        return None
    return float(np.corrcoef(a[m], b[m])[0, 1])


def pct_scores(vals):
    idx = [i for i, v in enumerate(vals) if v is not None]
    idx.sort(key=lambda i: -vals[i])
    n = len(idx); out = {}
    for r, i in enumerate(idx):
        out[i] = (n - r) / n if n > 1 else 1.0
    return out


def main():
    raw = avm.fetch_all_rows("house_trades", cols="region,dong,danji,price,size,floor,deal_date,dealing_type", extra_filter=f"&deal_date=gte.{cyc.START_DATE}")
    df = raw[raw["dealing_type"] != "직거래"].copy() if "dealing_type" in raw.columns else raw.copy()
    for c in ("price", "size", "floor", "deal_date"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["price", "size", "deal_date", "region", "dong", "danji"])
    df = df[(df["price"] > 0) & (df["size"] > 10) & (df["floor"].fillna(5) >= 2)]
    df["logp"] = np.log(df["price"] / df["size"] * 3.305785)
    df["ym"] = cyc.ym_of(df["deal_date"]); df["q"] = df["ym"] // 3
    df["dongk"] = df["dong"].astype(str).str.split().str[-1]
    df["ckey"] = df["region"].astype(str) + "|" + df["dongk"] + "|" + df["danji"].astype(str)
    df["unit"] = df["ckey"] + "|" + (df["size"] / cyc.SIZE_BUCKET_M2).round().astype(int).astype(str)
    df = df.reset_index(drop=True)
    qmin, qmax = int(df["q"].min()), int(df["q"].max()) - 1  # 마지막 분기는 신고 덜 들어옴
    print(f"거래 {len(df):,}건, 분기 {cyc.q_label(qmin)}~{cyc.q_label(qmax)}")
    cutoffs = [q for q in range(qmin + 16, qmax - 4 + 1) if q % 2 == 0]
    S = {g: {m: [] for m in ("A", "V", "P", "L", "ALL")} for g in ("local", "metro")}
    cover = {"local": [0, 0, 0], "metro": [0, 0, 0]}  # 표본, L 성립, A==L 같은 단지
    methods = ("A", "V", "P", "L")
    agree = {g: {"AV": [0, 0], "AL": [0, 0], "VL": [0, 0]} for g in S}
    for region, dfr in df.groupby("region"):
        grp = "metro" if str(region).startswith(("서울", "인천", "경기")) else "local"
        cq = cyc.complex_quarterly(dfr)
        counts_all = dfr.groupby("ckey", observed=True).size()
        good = set(counts_all[counts_all >= MIN_TRADES].index)
        cq = cq[cq["ckey"].isin(good)]
        if cq.empty: continue
        qs = np.arange(qmin, qmax + 1)
        M = cq.pivot(index="q", columns="ckey", values="mean").reindex(qs)
        N = cq.pivot(index="q", columns="ckey", values="count").reindex(qs).fillna(0)
        Mi = M.interpolate(limit=2, limit_area="inside")
        Dm = Mi.diff()
        W = N.where(Dm.notna(), 0).clip(lower=0) + Dm.notna() * 0.5
        dongk = dfr.drop_duplicates("ckey").set_index("ckey")["dongk"].to_dict()
        ppp = dfr.groupby("ckey", observed=True)["logp"].mean().to_dict()
        # 시군구 전체 분기 변화(가중평균)
        Dz = Dm.fillna(0)
        reg_d = (Dz * W).sum(axis=1) / W.sum(axis=1).replace(0, np.nan)
        for dk in sorted(set(dongk[c] for c in Dm.columns)):
            cols = [c for c in Dm.columns if dongk.get(c) == dk]
            if len(cols) < 3: continue
            Dd, Wd, Nd = Dz[cols].to_numpy(), W[cols].to_numpy(), N[cols].to_numpy()
            tcount = Nd.sum(axis=0)
            for c in cutoffs:
                ci = c - qmin
                # 컷오프까지 조건: 거래 20건 이상, 활동 8분기 이상
                hist_n = Nd[:ci + 1].sum(axis=0)
                active = (~np.isnan(Dm[cols].to_numpy()[:ci + 1])).sum(axis=0)
                cand = [j for j in range(len(cols)) if hist_n[j] >= MIN_TRADES and active[j] >= MIN_Q]
                if len(cand) < 3: continue
                lo = max(1, ci - 11)
                # 지표 계산
                r3 = [Nd[lo:ci + 1, j].sum() for j in cand]
                r1 = [Nd[ci - 3:ci + 1, j].sum() for j in cand]
                first = [np.argmax(Nd[:ci + 1, j] > 0) for j in cand]
                inter = []
                for k, j in enumerate(cand):
                    yrs = (ci + 1 - first[k]) / 4
                    prior = (hist_n[j] - r1[k]) / (yrs - 1) if yrs > 1.5 else None
                    inter.append(r1[k] / prior if prior and prior > 0 else None)
                pv, pi = pct_scores(r3), pct_scores(inter)
                A = [0.7 * pv.get(k, 0) + (0.3 * pi[k] if k in pi else 0) for k in range(len(cand))]
                pick = {"A": int(np.argmax(A)), "V": int(np.argmax(r3)), "P": int(np.argmax([ppp[cols[j]] for j in cand]))}
                # L: 나머지 대비 1~3분기 선행 상관
                best = (None, None)
                for k, j in enumerate(cand):
                    others = [o for o in range(len(cols)) if o != j]
                    wo = Wd[:ci + 1, others]; do = Dd[:ci + 1, others]
                    rest = (do * wo).sum(axis=1) / np.where(wo.sum(axis=1) > 0, wo.sum(axis=1), np.nan)
                    own = Dm[cols[j]].to_numpy()[:ci + 1]
                    cs = [corr(own[1:ci + 1 - lag][ :len(own) - 1 - lag], rest[1 + lag:ci + 1]) for lag in (1, 2, 3)]
                    cs = [x for x in cs if x is not None]
                    if cs and (best[0] is None or max(cs) > best[0]): best = (max(cs), k)
                pick["L"] = best[1] if best[0] is not None and best[0] >= LEAD_MIN else None
                cover[grp][0] += 1
                if pick["L"] is not None: cover[grp][1] += 1
                for a, b in (("A", "V"), ("A", "L"), ("V", "L")):
                    if pick[a] is not None and pick[b] is not None:
                        agree[grp][a + b][0] += 1; agree[grp][a + b][1] += int(pick[a] == pick[b])
                # 채점: 대장 최근 4분기 변화 → 나머지의 다음 4분기 초과 변화
                def score(k):
                    j = cand[k]
                    x = Dd[ci - 3:ci + 1, j].sum()
                    others = [o for o in range(len(cols)) if o != j]
                    wo = Wd[ci + 1:ci + 5, others]; do = Dd[ci + 1:ci + 5, others]
                    if wo.sum() == 0: return None
                    rest_f = ((do * wo).sum(axis=1) / np.where(wo.sum(axis=1) > 0, wo.sum(axis=1), np.nan))
                    rf = np.nansum(rest_f)
                    rg = np.nansum(reg_d.to_numpy()[ci + 1:ci + 5])
                    return float(x), float(rf - rg)
                for m in methods:
                    k = pick.get(m)
                    if k is None: continue
                    sc = score(k)
                    if sc: S[grp][m].append(sc)
                for k in range(len(cand)):
                    sc = score(k)
                    if sc: S[grp]["ALL"].append(sc)
    names = {"A": "인기(거래량 중심)", "V": "거래량 최다", "P": "평단가 최고", "L": "시세 선행", "ALL": "아무 단지(기준선)"}
    out = {}
    for g in S:
        out[g] = {"표본(동×시점)": cover[g][0], "선행 성립": cover[g][1], "같은 단지 비율": {k: (round(v[1] / v[0] * 100, 1) if v[0] else None) for k, v in agree[g].items()}}
        for m, rows in S[g].items():
            if len(rows) < 100: continue
            a = np.array(rows); x, y = a[:, 0], a[:, 1]
            big = x > 0.03
            out[g][names[m]] = {"n": len(a), "상관": round(float(np.corrcoef(x, y)[0, 1]), 3),
                                "대장 3%↑일 때 나머지 초과상승 평균%": round(float(y[big].mean()) * 100, 2) if big.any() else None,
                                "그때 나머지가 시군구보다 더 오른 비율%": round(float((y[big] > 0).mean()) * 100, 1) if big.any() else None,
                                "전체 평균 초과%": round(float(y.mean()) * 100, 2)}
    txt = json.dumps(out, ensure_ascii=False, indent=1)
    print(txt)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("```json\n" + txt + "\n```\n")


if __name__ == "__main__":
    main()
