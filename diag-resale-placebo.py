"""
🔎 "확실"로 판정한 되판 기록은 얼마나 믿을 만한가? - 플라시보(가짜 시점) 검증 (2026-10, 사용자: "신뢰도 여부가 더 궁금")
같은 동·같은 층·같은 면적 거래가 낙찰 "이후" 12개월에 나타나는 비율(P후)과, 낙찰 "이전" 12개월·24~12개월 전에 나타나는 비율(P전)을 비교한다.
 - 이전에는 낙찰 때문에 일어난 되팔기가 있을 수 없으니 P전은 "같은 동·층의 형제 호수가 그냥 거래되는 우연"의 기준선이다.
 - P후 − P전 = 진짜 되팔기로 볼 수 있는 몫(초과분). 1 − P전/P후 = '확실' 판정 중 진짜일 비율의 추정.
⚠️ 한계: P전 구간에는 낙찰 집 자신의 이전 매수(채무자가 산 거래)가 섞일 수 있음(보통 수년 전이라 1~2년 안엔 드묾).
거래의 동 번호는 2023-01 이후만 있으므로 낙찰 2024-01 이후 사례만 사용(이전 12개월에도 동 번호가 있어야 하므로).
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
avm = ab.avm
SITE = ab.SITE_URL


def main():
    cases = pd.DataFrame(requests.get(f"{SITE}/api/auction?kind=bidCases", timeout=180).json())
    df = cases[cases["propertyType"].astype(str).str.contains("아파트", na=False)].copy()
    df["actual"] = pd.to_numeric(df["finalBidPrice"], errors="coerce") / 10000.0
    df["area"] = pd.to_numeric(df["areaM2"], errors="coerce")
    df["fl"] = pd.to_numeric(df["floor"], errors="coerce")
    df = df[(df["actual"] > 0) & df["area"].notna() & df["fl"].notna() & df["saleDate"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)]
    df["sale_int"] = df["saleDate"].str.replace("-", "").astype(int)
    cut_old = int((datetime.now() - timedelta(days=380)).strftime("%Y%m%d"))
    df = df[(df["sale_int"] >= 20240101) & (df["sale_int"] <= cut_old)].copy()
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
        return ""
    df["adong"] = df.apply(case_adong, axis=1)
    df = df[df["adong"] != ""].dropna(subset=["region", "dk"]).reset_index(drop=True)
    vc = df["region"].value_counts()
    df = df[df["region"].isin(vc[vc >= 150].index)].reset_index(drop=True)
    print(f"  대상 낙찰사례(2024-01~, 낙찰 후 1년+, 동 번호 있음, 사례 150건+ 지역) {len(df):,}건, 지역 {df['region'].nunique()}곳")

    names = set()
    for r in df["region"].unique():
        sd, gu = r.split(" ", 1)
        for alias in ({"전남광주": ["전남광주", "광주", "전남"]}.get(sd, [sd])):
            names.add(f"{alias} {gu}")
    flt = "&or=(" + ",".join('region.like."' + n + '*"' for n in sorted(names)) + ")"
    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,apt_dong,cdeal_type",
                            extra_filter=f"&deal_date=gte.20230101{flt}")
    if "cdeal_type" in tr.columns:
        tr = tr[tr["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    for c in ("price", "size", "floor", "deal_date"):
        tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"])
    tr["dk"] = tr["dong"].map(ab.dong_key); tr["region_n"] = tr["region"].map(ab.region_norm); tr["bunji_s"] = tr["bunji"].astype(str).str.strip()
    tr["adong"] = tr["apt_dong"].map(lambda v: str(int(re.search(r"(\d{1,4})", str(v)).group(1))) if re.search(r"(\d{1,4})", str(v or "")) else "")
    tr = tr[tr["adong"] != ""]
    groups = {k: g for k, g in tr.groupby(["region_n", "dk", "bunji_s"])}
    nD = {k: int(g["adong"].nunique()) for k, g in groups.items()}
    print(f"  거래(동 번호 있는 것) {len(tr):,}건, 단지 {len(groups):,}곳")

    def has(g, c, a_days, b_days):
        """낙찰일 + a_days ~ + b_days 사이(음수=이전) 같은 동·층·면적(±2)·가격(낙찰가의 70~150%) 거래가 있는가"""
        sd = ab.int_to_date(int(c.sale_int))
        lo, hi = ab.ymd_int(sd + timedelta(days=a_days)), ab.ymd_int(sd + timedelta(days=b_days))
        m = (g["adong"] == c.adong) & (g["floor"] == c.fl) & ((g["size"] - c.area).abs() <= 2) & (g["deal_date"] >= lo) & (g["deal_date"] <= hi)
        m &= (g["price"] >= c.actual * 0.7) & (g["price"] <= c.actual * 1.5)
        return bool(m.any())

    wins = {"후 14일~3개월": (14, 91), "후 14일~6개월": (14, 183), "후 14일~12개월": (14, 365),
            "전 3개월~14일": (-91, -14), "전 6개월~14일": (-183, -14), "전 12개월~14일": (-365, -14), "전 24~12개월": (-730, -365)}
    rows = []
    for c in df.itertuples():
        g = groups.get((c.region, c.dk, c.bunji_s))
        if g is None:
            continue
        r = {k: has(g, c, a, b) for k, (a, b) in wins.items()}
        r["nD"] = nD[(c.region, c.dk, c.bunji_s)]
        r["year"] = c.sale_int // 10000
        rows.append(r)
    R = pd.DataFrame(rows)
    n = len(R)
    print(f"\n분석 사례 {n:,}건 (동 번호 있고 단지·거래 찾음)")
    print("\n=== 같은 동·층·면적 거래가 나타난 비율 ===")
    for k in wins:
        print(f"  {k:>12}: {R[k].mean() * 100:5.1f}%")
    P = {k: R[k].mean() for k in wins}
    for post, pre in (("후 14일~3개월", "전 3개월~14일"), ("후 14일~6개월", "전 6개월~14일"), ("후 14일~12개월", "전 12개월~14일")):
        ex = P[post] - P[pre]
        print(f"\n  ▶ {post} vs {pre}: 후 {P[post] * 100:.1f}% - 전 {P[pre] * 100:.1f}% = 초과분 {ex * 100:.1f}%p → '확실' 중 진짜 비율 추정 {max(0, ex) / P[post] * 100:.0f}%")
    print("\n=== 단지 동 수별 (후 12개월 vs 전 12개월) ===")
    def nb(n):
        return "동 1~2개" if n <= 2 else ("3~5개" if n <= 5 else ("6~10개" if n <= 10 else ("11~20개" if n <= 20 else "21개+")))
    R["nb"] = R["nD"].map(nb)
    out = {}
    for b in ["동 1~2개", "3~5개", "6~10개", "11~20개", "21개+"]:
        S = R[R["nb"] == b]
        if len(S) < 30:
            continue
        post, pre = S["후 14일~12개월"].mean(), S["전 12개월~14일"].mean()
        print(f"  {b:>8} (n={len(S):,}): 후 {post * 100:5.1f}% · 전 {pre * 100:5.1f}% · 초과분 {(post - pre) * 100:5.1f}%p · 진짜 비율 추정 {max(0, post - pre) / post * 100 if post else 0:.0f}%")
        out[b] = {"n": len(S), "post": round(post, 4), "pre": round(pre, 4)}
    print("\n=== 낙찰 연도별 ===")
    for y, S in R.groupby("year"):
        print(f"  {y}: n={len(S):,} 후 {S['후 14일~12개월'].mean() * 100:.1f}% · 전 {S['전 12개월~14일'].mean() * 100:.1f}%")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("## 플라시보 검증\n\n```\n" + json.dumps({"n": n, "P": {k: round(v, 4) for k, v in P.items()}, "byDong": out}, ensure_ascii=False, indent=1) + "\n```\n")


if __name__ == "__main__":
    main()
