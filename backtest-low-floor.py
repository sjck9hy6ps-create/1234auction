"""
🏢 1층 예상매도가 점검 (2026-10-29, 사용자: 대방개나리1차 1층 - 같은 단지 1층 실거래는 5개월 전 9,000만뿐이고 다른 층 직거래도 1.18억인데 예상매도가가 1.26억 → 1층이 그보다 높을 가능성은 희박)
시험 = 2025년~ 1층 거래(직거래 제외). 직전 정보만으로 예상: 같은 단지·같은 평형(±3㎡) 6개월 지역 규칙 값(층 구분 없음) → 1층 보정 방식 비교
 A 현재 방식 근사: 규칙 값 × (1 − 7.8%)   (대방개나리 사례의 앱 보정 수준)
 B 이 단지 1~2층 실거래 비율: 최근 18개월 같은 평형 1~2층 거래 ÷ 그 시점 ±60일 다른 층 중위 → 비율 중위 × 규칙 값 (1~2층 거래가 있을 때만)
 C 이 단지 1~2층 마지막 거래가를 시점 보정(그 시점 ±60일 다른 층 중위 → 지금 규칙 값 비율)
 D 혼합: B와 A의 평균
결과: 보통 오차·치우침·예상이 10%+/15%+ 높은 비율. 앱 계산은 바꾸지 않음.
"""
import os, re, json, importlib.util
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ab", os.path.join(HERE, "analyze-bidcases.py"))
ab = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ab)
avm = ab.avm
MAX_TEST = int(os.environ.get("MAX_TEST", "60000"))
rng = np.random.default_rng(7)


def cls_of(region):
    s = str(region or "").split(" ")[0]
    if s.startswith("서울"): return "서울"
    if s[:2] in ("경기", "인천"): return "경기·인천"
    return "지방"


def wq(vals, w, q=0.5):
    o = np.argsort(vals); v = np.asarray(vals)[o]; ww = np.asarray(w)[o]
    c = (np.cumsum(ww) - 0.5 * ww) / ww.sum()
    return float(np.interp(q, c, v))


def main():
    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,cdeal_type", extra_filter="&deal_date=gte.20220101")
    if "cdeal_type" in tr.columns: tr = tr[tr["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    for c in ("price", "size", "deal_date", "floor"): tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"]); tr = tr[(tr["price"] > 0) & (tr["size"] > 10)]
    tr["dk"] = tr["dong"].map(ab.dong_key); tr["rg"] = tr["region"].map(ab.region_norm); tr["bj"] = tr["bunji"].astype(str).str.strip()
    tr["direct"] = (tr["dealing_type"] == "직거래")
    tr["ts"] = pd.to_datetime(tr["deal_date"].astype(int).astype(str), format="%Y%m%d", errors="coerce"); tr = tr.dropna(subset=["ts", "rg"])
    tr["t"] = (tr["ts"] - pd.Timestamp("2000-01-01")).dt.days.astype(float)
    tr["cls"] = tr["region"].map(cls_of)
    print(f"  거래 {len(tr):,}건")
    groups = {k: g.sort_values("t").reset_index(drop=True) for k, g in tr.groupby(["rg", "dk", "bj"])}
    t_start = (pd.Timestamp("2025-01-01") - pd.Timestamp("2000-01-01")).days
    MAIN = {"서울": "last3", "경기·인천": 1.0, "지방": 2.0}
    rows = []
    for k, g in groups.items():
        idx = np.where((g["t"].values >= t_start) & (~g["direct"].values) & (g["floor"].values == 1))[0]
        for i in idx:
            T = g.iloc[i]; H = g.iloc[:i]; H = H[(H["t"] < T["t"]) & (~H["direct"])]
            S = H[(H["size"] - T["size"]).abs() <= 3]
            if len(S) < 3: continue
            ag = (T["t"] - S["t"].values) / 30.4; pr = S["price"].values; fl = S["floor"].values
            p6 = pr[ag <= 6]; a6 = ag[ag <= 6]
            if len(p6) < 3: continue
            m = MAIN[T["cls"]]
            base = float(np.median(pr[np.argsort(ag)[:3]])) if m == "last3" else wq(p6, [0.5 ** (x / m) for x in a6])
            # 1층 보정 A (현재 방식 근사)
            eA = base * (1 - 0.078)
            # 이 단지 1~2층 비율
            ratios = []; lows = []
            for j in np.where((fl <= 2) & (ag <= 18))[0]:
                t0 = S["t"].values[j]
                oth = S[(np.abs(S["t"].values - t0) <= 60) & (S["floor"].values > 2)]["price"].values
                if len(oth) >= 2: ratios.append(pr[j] / np.median(oth)); lows.append((ag[j], pr[j], np.median(oth)))
            # 1층만 별도 계산(2026-10-29): 이 단지 같은 평형 1층 거래만 모아, 각 거래를 그 시점 ±60일 3층+ 중위 대비 현재 규칙 값 수준으로 시점 보정한 값들의 (최근 가중) 중위
            f1 = []
            for j in np.where((fl == 1) & (ag <= 12))[0]:
                t0 = S["t"].values[j]
                oth = S[(np.abs(S["t"].values - t0) <= 60) & (S["floor"].values > 2)]["price"].values
                if len(oth) >= 2: f1.append((ag[j], pr[j] * base / np.median(oth) / (base / np.median(oth)) , pr[j] / np.median(oth)))
            n1 = len(f1)
            rec = dict(cls=T["cls"], actual=float(T["price"]), base=base, eA=eA, nlow=len(ratios), n1=n1)
            if n1:
                # E: 1층 거래의 '다른 층 대비 비율' 중위 × 지금 규칙 값(시점 보정은 규칙 값이 이미 최근 시세)
                rec["eE"] = base * min(1.0, float(np.median([x[2] for x in f1])))
                # F: 1층 거래 가격 자체를 시점 보정(그 시점 다른 층 중위 → 지금 규칙 값) 한 값들의 중위
                rec["eF"] = float(np.median([min(1.0, x[2]) * base for x in f1]))
            if ratios:
                rB = float(np.median(ratios)); rec["eB"] = base * min(1.0, rB)   # 1층이 다른 층보다 비쌌던 경우도 있어 상한 1.0
                last = sorted(lows)[0]; rec["eC"] = base * min(1.0, last[1] / last[2])
                rec["eD"] = 0.5 * rec["eB"] + 0.5 * eA
            rows.append(rec)
    D = pd.DataFrame(rows); print(f"  1층 시험 거래 {len(D):,}건, 이 단지 1~2층 비교 거래가 있는 건 {int(D['eB'].notna().sum()):,}건")
    D.to_json("backtest-low-floor.json", orient="records", force_ascii=False)
    def st(d, c):
        r = d["actual"] / d[c] - 1
        return {"n": int(len(r)), "err": round(float(r.abs().median()) * 100, 2), "bias": round(float(r.median()) * 100, 2), "hi10": round(float((r < -0.10).mean()) * 100, 1), "hi15": round(float((r < -0.15).mean()) * 100, 1), "lo10": round(float((r > 0.10).mean()) * 100, 1)}
    out = {}
    print("\n==== 1층 예상매도가 보정 방식 비교 ====")
    sub = D[D["eB"].notna()]
    for nm, G in (("이 단지 1~2층 거래가 있는 건", sub), ("전체 1층", D)):
        print(f"[{nm}] n{len(G):,}")
        for c, lab in (("base", "보정 없음(규칙 값)"), ("eA", "A 현재 근사(−7.8%)"), ("eB", "B 이 단지 1~2층 비율"), ("eC", "C 마지막 1~2층 거래 시점보정"), ("eD", "D B·A 평균")):
            if c in G.columns and G[c].notna().sum() > 100:
                x = st(G[G[c].notna()], c); out[nm + "|" + lab] = x; print(f"   {lab:<24}", x)
    print("\n==== 1층만 별도 계산: 이 단지 같은 평형 1층 거래 수별 ====")
    for lab, lo, hi in (("1층 거래 1건", 1, 1), ("2건", 2, 2), ("3건+", 3, 99)):
        G = D[(D.n1 >= lo) & (D.n1 <= hi)]
        if len(G) < 150: continue
        print(f"[{lab}] n{len(G):,}")
        for c, nm in (("eA", "A 현재 근사"), ("eD", "D B·A 평균"), ("eE", "E 1층 거래 비율만"), ("eF", "F 1층 거래 시점보정 중위")):
            if c in G.columns and G[c].notna().sum() > 100: print(f"   {nm:<22}", st(G[G[c].notna()], c))
        if len(G) >= 150:
            m = G.assign(eG=0.5 * G["eE"] + 0.5 * G["eA"])
            print(f"   {'G E·A 평균':<22}", st(m, "eG"))
    for cls in ("서울", "경기·인천", "지방"):
        G = sub[sub.cls == cls]
        if len(G) < 150: continue
        print(f"[{cls}·1~2층 거래 있음] n{len(G):,}")
        for c, lab in (("eA", "A"), ("eB", "B"), ("eC", "C"), ("eD", "D")): print(f"   {lab}", st(G, c))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("### 1층 예상매도가 보정 비교\n```json\n" + json.dumps(out, ensure_ascii=False, indent=1) + "\n```\n")


if __name__ == "__main__":
    main()
