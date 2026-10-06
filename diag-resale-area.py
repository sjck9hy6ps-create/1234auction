"""
🔎 낙찰 후 매도 찾기 진단 (2026-10, 사용자: "낙찰 후 매도된 집을 찾는 과정을 심화하고 싶다 - 제일 의심되는 건 평형(면적):
건축물대장 평형과 CSV로 올린 면적이 일치하지 않는 경우가 많은 것 같다")
낙찰사례(2023-01~, 낙찰 후 1년 지난 것)마다 "왜 되팔기를 못 찾았는지"를 단계별로 나눠 센다:
 ① 단지를 실거래에서 못 찾음 ② 단지의 어떤 면적도 CSV 면적(±2㎡)과 안 맞음(→ 공급면적처럼 보이는지 따로) ③ 면적은 맞는데 낙찰 후 거래 없음
 ④ 거래는 있는데 다른 층만 ⑤ 같은 층인데 낙찰가의 70% 미만 ⑥ 같은 층·가격 OK인데 다른 동만 ⑦ 찾음(동 확인) ⑧ 찾음(층만, 동 모름)
그리고 ②의 "공급면적처럼 보이는" 사례를 전용면적으로 바꿔 다시 찾으면 몇 건이 더 찾아지는지(=면적 보정의 효과)를 센다.
"""
import os, re, json, importlib.util
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ab", os.path.join(HERE, "analyze-bidcases.py"))
ab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ab)
cyc, avm = ab.cyc, ab.avm
SITE = ab.SITE_URL


def main():
    cases = pd.DataFrame(requests.get(f"{SITE}/api/auction?kind=bidCases", timeout=180).json())
    df = cases[cases["propertyType"].astype(str).str.contains("아파트", na=False)].copy()
    df["actual"] = pd.to_numeric(df["finalBidPrice"], errors="coerce") / 10000.0
    df["area"] = pd.to_numeric(df["areaM2"], errors="coerce")
    df["fl"] = pd.to_numeric(df["floor"], errors="coerce")
    df = df[(df["actual"] > 0) & df["area"].notna() & df["saleDate"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)]
    df["sale_int"] = df["saleDate"].str.replace("-", "").astype(int)
    cut_old = int((datetime.now() - timedelta(days=365)).strftime("%Y%m%d"))
    df = df[(df["sale_int"] >= 20230101) & (df["sale_int"] <= cut_old)].copy()
    df["region"] = df["addrJibun"].map(ab.region_norm)
    df["dk"] = df["dong"].map(ab.dong_key)

    def full_bunji(row):
        d = str(row.get("dong") or "")
        m = re.search(re.escape(d) + r"\s+(산?\d+(?:-\d+)?)", str(row.get("addrJibun") or "")) if d else None
        return m.group(1).replace("산", "").strip() if m else str(row.get("bunji") or "").strip()
    df["bunji_s"] = df.apply(full_bunji, axis=1)

    def case_adong(row):
        ad = row.get("aptDong")
        if isinstance(ad, str) and ad.strip().isdigit():
            return str(int(ad.strip()))
        txt = str(row.get("addrJibun") or ""); b = str(row.get("bunji") or "")
        tail = txt.split(b, 1)[1] if b and b in txt else txt
        for t in (tail, str(row.get("unitNo") or "")):
            m = re.search(r"(\d{1,4})\s*동(?![가-힣])", t)
            if m:
                return str(int(m.group(1)))
        return None
    df["adong"] = df.apply(case_adong, axis=1)
    df = df.dropna(subset=["region", "dk"]).reset_index(drop=True)
    print(f"  대상 낙찰사례 {len(df):,}건 (2023-01~낙찰 후 1년 지난 아파트)")

    names = set()
    for r in df["region"].unique():
        sd, gu = r.split(" ", 1)
        for alias in ({"전남광주": ["전남광주", "광주", "전남"]}.get(sd, [sd])):
            names.add(f"{alias} {gu}")
    flt = "&or=(" + ",".join('region.like."' + n + '*"' for n in sorted(names)) + ")"
    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,apt_dong,cdeal_type",
                            extra_filter=f"&deal_date=gte.20220601{flt}")
    if "cdeal_type" in tr.columns:
        tr = tr[tr["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    for c in ("price", "size", "floor", "deal_date"):
        tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"])
    tr["dk"] = tr["dong"].map(ab.dong_key); tr["region_n"] = tr["region"].map(ab.region_norm); tr["bunji_s"] = tr["bunji"].astype(str).str.strip()
    tr["adong"] = tr["apt_dong"].map(lambda v: str(int(re.search(r"(\d{1,4})", str(v)).group(1))) if re.search(r"(\d{1,4})", str(v or "")) else "") if "apt_dong" in tr.columns else ""
    groups = {k: g for k, g in tr.groupby(["region_n", "dk", "bunji_s"])}
    print(f"  실거래(2022-06~, 직거래 포함·해제 제외) {len(tr):,}건, 단지 {len(groups):,}곳")

    def find(g, c, area, tol=2.0):
        """(이유, 거래행) - 면적 area 기준으로 되팔기 찾기"""
        sd = ab.int_to_date(int(c.sale_int))
        same = g[(g["size"] - area).abs() <= tol]
        if not len(same):
            return "area", None
        after = same[same["deal_date"] >= ab.ymd_int(sd + timedelta(days=14))]
        if not len(after):
            return "nolater", None
        if pd.isna(c.fl):
            return "nofloor", None
        fl = after[after["floor"] == c.fl]
        if not len(fl):
            return "otherfloor", None
        fl = fl.sort_values("deal_date")
        ok = fl[fl["price"] >= c.actual * 0.7]  # 실거래 price·낙찰가 모두 만원 단위
        if not len(ok):
            return "lowprice", None
        ad = c.adong
        if isinstance(ad, str) and ad:
            ok2 = ok[(ok["adong"] == ad) | (ok["adong"] == "")]
            if not len(ok2):
                return "otherdong", None
            if ok2.iloc[0]["adong"] == ad:
                return "found_dong", ok2.iloc[0]
            return "found_floor", ok2.iloc[0]
        return "found_floor", ok.iloc[0]

    reasons = {}
    rows = []
    for c in df.itertuples():
        g = groups.get((c.region, c.dk, c.bunji_s))
        if g is None or not len(g):
            rows.append((c.id if hasattr(c, "id") else None, "nocomplex", None, c.sale_int // 10000)); continue
        # 낙찰가 단위: 실거래 price는 만원, c.actual도 만원
        why, hit = find(g, c, c.area)
        info = None
        if why == "area":
            sizes = sorted(set(np.round(g["size"].astype(float), 1)))
            near = min(sizes, key=lambda s: abs(s - c.area)) if sizes else None
            # 공급면적처럼 보이는지: CSV 면적이 어떤 전용면적의 1.22~1.42배
            cand = [s for s in sizes if 1.22 * s <= c.area <= 1.42 * s]
            info = {"csv": float(c.area), "near": near, "ratio": (c.area / near) if near else None, "supplyLike": bool(cand), "cand": cand[:3]}
            if len(cand) >= 1:
                best = min(cand, key=lambda s: abs(c.area / 1.3 - s))
                why2, hit2 = find(g, c, best, tol=1.0)
                info["remap"] = why2
        rows.append((None, why, info, c.sale_int // 10000))
    R = pd.DataFrame(rows, columns=["id", "why", "info", "year"])
    n = len(R)
    cnt = R["why"].value_counts().to_dict()
    pct = {k: round(v / n * 100, 1) for k, v in cnt.items()}
    print(f"\n=== 되팔기 못 찾은 이유 (전체 {n:,}건) ===")
    names_ko = {"nocomplex": "① 단지를 실거래에서 못 찾음", "area": "② 단지 면적 중 CSV 면적(±2㎡)과 맞는 게 없음", "nolater": "③ 면적은 맞는데 낙찰 후 거래 없음",
                "otherfloor": "④ 낙찰 후 거래는 있는데 다른 층만", "lowprice": "⑤ 같은 층인데 낙찰가의 70% 미만", "otherdong": "⑥ 같은 층·가격 OK인데 다른 동만",
                "found_dong": "⑦ 찾음(동까지 확인)", "found_floor": "⑧ 찾음(층만 맞음·동 모름)", "nofloor": "층 정보 없음"}
    for k in ["nocomplex", "area", "nolater", "otherfloor", "lowprice", "otherdong", "found_dong", "found_floor", "nofloor"]:
        if k in cnt:
            print(f"  {names_ko[k]}: {cnt[k]:,}건 ({pct[k]}%)")
    A = R[R["why"] == "area"]
    sl = sum(1 for i in A["info"] if i and i["supplyLike"])
    rm = [i.get("remap") for i in A["info"] if i and i.get("remap")]
    print(f"\n②번 {len(A):,}건 중 공급면적처럼 보이는 것(전용의 1.22~1.42배): {sl:,}건")
    print("   전용으로 바꿔 다시 찾으면:", pd.Series(rm).value_counts().to_dict())
    ratios = pd.Series([i["ratio"] for i in A["info"] if i and i["ratio"]])
    if len(ratios):
        print("   CSV 면적 ÷ 가장 가까운 단지 면적 분포:", ratios.describe(percentiles=[.1, .25, .5, .75, .9]).round(2).to_dict())
    # 오차 크기(단지 면적과 CSV 면적 차이) 분포 - 전체 사례 대상
    offs = []
    for c in df.itertuples():
        g = groups.get((c.region, c.dk, c.bunji_s))
        if g is None or not len(g): continue
        sizes = g["size"].astype(float).unique()
        offs.append(float(np.min(np.abs(sizes - c.area))))
    o = pd.Series(offs)
    print("\n단지를 찾은 사례의 |CSV 면적 − 가장 가까운 단지 면적| 분포(㎡): ≤0.1 %.1f%% · ≤0.5 %.1f%% · ≤1 %.1f%% · ≤2 %.1f%% · ≤5 %.1f%% · >5 %.1f%%" % tuple(
        [(o <= v).mean() * 100 for v in (0.1, 0.5, 1, 2, 5)] + [(o > 5).mean() * 100]))
    print("연도별 찾은 비율:", R.groupby("year")["why"].apply(lambda s: round(s.isin(["found_dong", "found_floor"]).mean() * 100, 1)).to_dict())
    ex = [i for i in A["info"] if i][:15]
    print("② 예시:", json.dumps(ex[:15], ensure_ascii=False, default=float)[:1500])
    # ── 면적 비교 방식 3가지(2026-10 발견: house_trades.size는 소수점을 버린 정수 → 84.97㎡·84.32㎡가 둘 다 84) ──
    #   T2 = 지금 방식(CSV 면적 ±2㎡), T1 = 정수로 내린 CSV 면적 ±1, T0 = 정수로 내린 CSV 면적과 정확히 같음
    import math
    def variant(tol, floor_csv):
        out = []
        for c in df.itertuples():
            g = groups.get((c.region, c.dk, c.bunji_s))
            if g is None or not len(g):
                out.append((None, None)); continue
            a = math.floor(c.area) if floor_csv else c.area
            why, hit = find(g, c, a, tol=tol)
            out.append((why, None if hit is None else (float(hit["price"]), int(hit["deal_date"]), float(hit["size"]))))
        return out
    V = {"T2 지금(±2㎡)": variant(2.0, False), "T1 정수±1": variant(1.0, True), "T0 정수 일치": variant(0.0, True)}
    print("\n=== 면적 비교 방식별 '찾음' 건수 ===")
    base = V["T2 지금(±2㎡)"]
    for k, v in V.items():
        fd = sum(1 for w, h in v if w == "found_dong"); ff = sum(1 for w, h in v if w == "found_floor"); ar = sum(1 for w, h in v if w == "area")
        diff = sum(1 for (w1, h1), (w2, h2) in zip(base, v) if (w1 in ("found_dong", "found_floor")) and (h1 != h2))
        print(f"  {k}: 찾음(동) {fd:,} · 찾음(층만) {ff:,} · 면적 불일치 {ar:,} · 지금 방식과 다른 거래가 잡힌/사라진 건 {diff:,}")
    # 지금 방식에선 찾았는데 정수 일치 방식에선 못 찾는 사례 = 이웃 평형(59·61㎡ 등)을 같은 것으로 본 의심 건
    lost = [(c, base[i][1], V["T0 정수 일치"][i][0]) for i, c in enumerate(df.itertuples()) if base[i][0] in ("found_dong", "found_floor") and V["T0 정수 일치"][i][0] not in ("found_dong", "found_floor")]
    print(f"\n지금은 찾았는데 정수 일치로는 못 찾는 건: {len(lost):,}건 (이웃 평형을 같은 집으로 본 의심)")
    if lost:
        sz = [(round(c.area, 1), h[2]) for c, h, w in lost[:12] if h]
        print("   예시(CSV 면적, 잡힌 거래 면적):", sz)
    # 층만 찾은 건: 동 정보가 어디서 빠졌는지
    ff = [(c, w) for c, (w, h) in zip(df.itertuples(), base) if w == "found_floor"]
    no_case = sum(1 for c, w in ff if not (isinstance(c.adong, str) and c.adong))
    print(f"\n'층만 찾음' {len(ff):,}건 중 낙찰사례에 동 번호가 없는 건 {no_case:,}건, 있는데 거래 쪽 동 정보가 없는 건 {len(ff) - no_case:,}건")
    summ = {"n": n, "counts": cnt, "supplyLikeInArea": sl, "remap": pd.Series(rm).value_counts().to_dict()}
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("## 되팔기 못 찾은 이유\n\n```\n" + json.dumps(summ, ensure_ascii=False, indent=1) + "\n```\n")


if __name__ == "__main__":
    main()
