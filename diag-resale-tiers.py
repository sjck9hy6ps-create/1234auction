"""
🔎 낙찰 후 매도 판정 "확실 / 유력 / 불확실" 검증 (2026-10, 사용자 요청)
1) 정답이 있는 사례(낙찰사례에 동 번호가 있고 거래에도 동 번호가 있는 것)에서 동 정보를 일부러 가려 "층만 맞춘 결과가 진짜인지" 맞혀 봄
   → 단지 동 수(큰 단지일수록 우연히 같은 층의 다른 집이 걸림)·경쟁 후보 거래 수·기간별로 층만 맞춘 매칭의 정확도(정밀도)를 구함
2) 낙찰 후 최소 일수(0·14·30·45·60일)와 최대 기간(3~24개월·제한 없음)을 바꿔 찾은 건수와 정확도가 어떻게 달라지는지 봄
   사용자 기준(보유 기간): 1개월 안 매도 = 자랑할 만큼 빠름 · 2~3개월 = 잘함 · 5~6개월까지는 감안하고 입찰
3) 정확도 표로 동 번호가 없는 사례도 확실/유력/불확실로 나누고 되판 비율(확실만·확실+유력·기대값)을 다시 계산, 기간별 누적 비율도 계산
"""
import os, re, json, math, importlib.util
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
        return ""
    df["adong"] = df.apply(case_adong, axis=1)
    df = df.dropna(subset=["region", "dk"]).reset_index(drop=True)
    print(f"  대상 낙찰사례 {len(df):,}건, 동 번호 있음 {int((df['adong'] != '').sum()):,}건")

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
    tr["adong"] = tr["apt_dong"].map(lambda v: str(int(re.search(r"(\d{1,4})", str(v)).group(1))) if re.search(r"(\d{1,4})", str(v or "")) else "")
    groups = {}
    for k, g in tr.groupby(["region_n", "dk", "bunji_s"]):
        groups[k] = g.sort_values("deal_date").reset_index(drop=True)
    print(f"  실거래 {len(tr):,}건, 단지 {len(groups):,}곳")
    nD_of = {k: int(g.loc[g["adong"] != "", "adong"].nunique()) for k, g in groups.items()}

    def cands(g, c, min_days, max_months):
        sd = ab.int_to_date(int(c.sale_int))
        lo = ab.ymd_int(sd + timedelta(days=min_days))
        m = (g["size"] - c.area).abs() <= 2
        m &= (g["deal_date"] >= lo) & (g["floor"] == c.fl) & (g["price"] >= c.actual * 0.7)
        if max_months:
            m &= g["deal_date"] <= ab.ymd_int(sd + timedelta(days=int(max_months * 30.4)))
        return g[m]

    def days_after(c, d):
        return (ab.int_to_date(int(d)) - ab.int_to_date(int(c.sale_int))).days

    items = list(df.itertuples())
    out = {}

    # ── 1) 정답 있는 사례(동 번호 있음)에서 층만 맞춘 매칭의 정확도 ──
    known = [c for c in items if c.adong != "" and groups.get((c.region, c.dk, c.bunji_s)) is not None]
    print(f"\n정답 검증 대상(낙찰사례 동 번호 있음·단지 찾음): {len(known):,}건")

    def prec(cs, min_days, max_months, restrict=None):
        rule = truth = first_ok = 0
        for c in cs:
            if restrict and not restrict(c):
                continue
            g = groups[(c.region, c.dk, c.bunji_s)]
            sub = cands(g, c, min_days, max_months)
            sub = sub[sub["adong"] != ""]  # 정답 판정이 가능한 거래만
            if not len(sub):
                continue
            rule += 1
            same = sub[sub["adong"] == c.adong]
            if len(same):
                truth += 1
                if sub.iloc[0]["adong"] == c.adong:
                    first_ok += 1
        return rule, truth, first_ok

    print("\n=== 낙찰 후 최소 일수별 (최대 기간 제한 없음) ===")
    print("최소일수 | 층만 맞춘 매칭 | 이 중 진짜(같은 동 거래 있음) | 정확도 | 첫 거래가 진짜인 비율")
    tab = {}
    for md in (0, 14, 30, 45, 60):
        r, t, f = prec(known, md, None)
        tab[md] = (r, t, f)
        print(f"  {md:>3}일 | {r:>6,} | {t:>6,} | {t / r * 100:5.1f}% | {f / r * 100:5.1f}%")
    out["byMinDays"] = {str(k): {"rule": v[0], "truth": v[1], "first": v[2]} for k, v in tab.items()}

    print("\n=== 최대 기간별 (최소 14일) - 기간을 짧게 잡으면 정확도가 오르는지 ===")
    print("최대기간 | 층만 맞춘 매칭 | 진짜 | 정확도 | 첫 거래가 진짜인 비율")
    tabm = {}
    for mm in (1, 2, 3, 4, 6, 9, 12, 18, 24, None):
        r, t, f = prec(known, 14, mm)
        tabm[str(mm)] = (r, t, f)
        print(f"  {str(mm) + '개월' if mm else '제한없음':>6} | {r:>6,} | {t:>6,} | {t / r * 100:5.1f}% | {f / r * 100:5.1f}%")
    out["byMaxMonths"] = {k: {"rule": v[0], "truth": v[1], "first": v[2]} for k, v in tabm.items()}

    # 단지 동 수·후보 거래 수별 정확도(최소 14일, 12개월)
    def nd_bucket(n):
        return "동 1개" if n <= 1 else ("2개" if n == 2 else ("3~5개" if n <= 5 else ("6~10개" if n <= 10 else ("11~20개" if n <= 20 else "21개+"))))

    def seg(c):
        g = groups[(c.region, c.dk, c.bunji_s)]
        sub = cands(g, c, 14, 12)
        sub = sub[sub["adong"] != ""]
        return nd_bucket(nD_of[(c.region, c.dk, c.bunji_s)]), ("후보 1건" if len(sub) == 1 else ("2건" if len(sub) == 2 else "3건+"))
    segs = {}
    for c in known:
        g = groups[(c.region, c.dk, c.bunji_s)]
        sub = cands(g, c, 14, 12)
        sub = sub[sub["adong"] != ""]
        if not len(sub):
            continue
        k = seg(c)
        a = segs.setdefault(k, [0, 0])
        a[0] += 1
        if len(sub[sub["adong"] == c.adong]):
            a[1] += 1
    print("\n=== 층만 맞춘 매칭의 정확도: 단지 동 수 × 후보 거래 수 (최소 14일·최대 12개월) ===")
    order = ["동 1개", "2개", "3~5개", "6~10개", "11~20개", "21개+"]
    for nb in order:
        row = []
        for cb in ("후보 1건", "2건", "3건+"):
            v = segs.get((nb, cb))
            row.append(f"{cb} {v[1] / v[0] * 100:4.0f}%({v[0]})" if v and v[0] >= 20 else f"{cb}  -  ")
        print(f"  {nb:>6}: " + " | ".join(row))
    out["segments"] = {f"{k[0]}|{k[1]}": {"n": v[0], "true": v[1]} for k, v in segs.items()}

    # 정답 사례의 보유 기간 분포(같은 동 첫 거래, 최소 0일)
    def hold_bucket(d):
        return "14일 안" if d < 14 else ("14~30일" if d <= 30 else ("1~2개월" if d <= 61 else ("2~3개월" if d <= 91 else ("3~6개월" if d <= 183 else ("6~12개월" if d <= 365 else "12개월+")))))
    hb = {}
    hb_floor = {}
    for c in known:
        g = groups[(c.region, c.dk, c.bunji_s)]
        sub = cands(g, c, 0, None)
        sub = sub[sub["adong"] != ""]
        same = sub[sub["adong"] == c.adong]
        if len(same):
            b = hold_bucket(days_after(c, same.iloc[0]["deal_date"])); hb[b] = hb.get(b, 0) + 1
        other = sub[sub["adong"] != c.adong]
        if len(other):
            b = hold_bucket(days_after(c, other.iloc[0]["deal_date"])); hb_floor[b] = hb_floor.get(b, 0) + 1
    labs = ["14일 안", "14~30일", "1~2개월", "2~3개월", "3~6개월", "6~12개월", "12개월+"]
    tot, totf = sum(hb.values()), sum(hb_floor.values())
    print("\n=== 매도까지 걸린 기간 분포 ===")
    print("  구간      | 같은 동 거래(진짜 매도) | 다른 동의 같은 층 첫 거래(남의 집) ← 이 차이가 클수록 그 구간에 오탐이 몰린다는 뜻")
    for b in labs:
        print(f"  {b:>8} | {hb.get(b, 0):>5,} ({hb.get(b, 0) / max(tot, 1) * 100:4.1f}%) | {hb_floor.get(b, 0):>5,} ({hb_floor.get(b, 0) / max(totf, 1) * 100:4.1f}%)")
    out["holdTrue"] = hb; out["holdOther"] = hb_floor

    # ── 3) 전체 사례 확실/유력/불확실 분류 ──
    MIN_D, MAX_M = 14, 12
    seg_prec = {k: v[1] / v[0] for k, v in segs.items() if v[0] >= 20}
    total = len(items)
    tiers = {"확실": 0, "유력": 0, "불확실": 0}
    exp = 0.0
    notfound_known = 0  # 동 번호 있는데 같은 동 거래 없음(확인된 미매도)
    nofind = 0
    hold_sure = []
    rows = []
    for c in items:
        g = groups.get((c.region, c.dk, c.bunji_s))
        if g is None:
            nofind += 1; continue
        sub_all = cands(g, c, MIN_D, MAX_M)
        if not len(sub_all):
            nofind += 1; continue
        nd = nD_of[(c.region, c.dk, c.bunji_s)]
        if c.adong != "":
            same = sub_all[(sub_all["adong"] == c.adong) | (sub_all["adong"] == "")]
            if len(same):
                t = "확실" if (same.iloc[0]["adong"] == c.adong) else "유력"  # 거래에 동이 비어 있으면 유력
                p = 1.0 if t == "확실" else 0.7
                hold = days_after(c, same.iloc[0]["deal_date"])
            else:
                notfound_known += 1; continue
        else:
            sub_d = sub_all[sub_all["adong"] != ""]
            ncand = len(sub_all)
            key = (nd_bucket(nd), "후보 1건" if ncand == 1 else ("2건" if ncand == 2 else "3건+"))
            p = seg_prec.get(key)
            if nd <= 1:
                p = max(p or 0, 0.95) if nd == 1 else p
            if p is None:
                p = 0.4
            t = "확실" if p >= 0.9 else ("유력" if p >= 0.7 else "불확실")
            hold = days_after(c, sub_all.iloc[0]["deal_date"])
        tiers[t] += 1; exp += p
        rows.append((t, hold))
    print(f"\n=== 되판 비율 재계산 (전체 {total:,}건, 최소 {MIN_D}일·최대 {MAX_M}개월) ===")
    for t in ("확실", "유력", "불확실"):
        print(f"  {t}: {tiers[t]:,}건 ({tiers[t] / total * 100:.1f}%)")
    print(f"  확인된 미매도(동 번호 있는데 같은 동 거래 없음): {notfound_known:,}건 ({notfound_known / total * 100:.1f}%)")
    print(f"  후보 거래 자체가 없음(단지 못 찾음 포함): {nofind:,}건 ({nofind / total * 100:.1f}%)")
    sure = tiers["확실"]; sl = tiers["확실"] + tiers["유력"]
    print(f"  ▶ 되판 비율: 확실만 {sure / total * 100:.1f}% · 확실+유력 {sl / total * 100:.1f}% · 확실+유력+불확실(예전 방식) {(sl + tiers['불확실']) / total * 100:.1f}% · 기대값(불확실을 정확도만큼만 반영) {exp / total * 100:.1f}%")
    R = pd.DataFrame(rows, columns=["tier", "hold"])
    print("\n=== 기간별 누적 되판 비율(전체 대비) ===")
    for lab, d in (("1개월 안", 30), ("2개월 안", 61), ("3개월 안", 91), ("6개월 안", 183), ("12개월 안", 366)):
        a = (R[R["tier"] == "확실"]["hold"] <= d).sum() / total * 100
        b = (R[R["tier"].isin(["확실", "유력"])]["hold"] <= d).sum() / total * 100
        print(f"  {lab}: 확실 {a:.1f}% · 확실+유력 {b:.1f}%")
    sure_hold = R[R["tier"] == "확실"]["hold"]
    print(f"\n확실 중 보유 기간 중앙값 {sure_hold.median() / 30.4:.1f}개월 · 1개월 안 {(sure_hold <= 30).mean() * 100:.1f}% · 3개월 안 {(sure_hold <= 91).mean() * 100:.1f}% · 6개월 안 {(sure_hold <= 183).mean() * 100:.1f}%")
    out["tiers"] = tiers; out["notfoundKnown"] = notfound_known; out["total"] = total; out["segPrec"] = {f"{k[0]}|{k[1]}": round(v, 3) for k, v in seg_prec.items()}
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("## 낙찰 후 매도 판정 검증\n\n```\n" + json.dumps(out, ensure_ascii=False, indent=1) + "\n```\n")


if __name__ == "__main__":
    main()
