"""
════════════════════════════════════════════════════════════
낙찰사례 대규모 검증 (2026-10)
════════════════════════════════════════════════════════════
사용자가 탱크옥션 CSV 68개(부산·대전·전남·광주 아파트 낙찰 6,800건, 2023~2026)를 낙찰사례로 올림 - 입찰자수·차순위(2등) 가격 포함.
앱 화면 검증은 지도용 최근 2년 실거래만 써서 2023~2025년 낙찰은 "당시 자료로 맞혔는지" 볼 수 없었음 - 여기서는
house_trades 2017~ 전체를 써서 사건마다 "입찰일 30일 전까지의 자료만으로" 예상매도가를 내고 실제 결과와 비교함.

예상매도가(앱 규칙을 단순화해 재현): 같은 단지(동+지번) 같은 면적(±2㎡) 실거래, 직거래 제외,
  같은 층 구간(1층 / 2층 이상) 우선 - 없으면 다른 층 구간을 1층 = 일반층의 91.5%로 보정,
  최근 1년 3건 이상이면 그것만, 아니면 3년까지 넓히고 시군구 월별 지수로 입찰 시점 가격으로 맞춤, 평당가 40% 지점 × 면적.
  같은 단지 거래가 없으면 예상매도가 없음(앱은 주변 단지를 쓰지만 여기선 제외 - 커버리지로 따로 보고).
재매도: 같은 단지·같은 면적·같은 층, 낙찰 14일 이후 첫 거래(직거래 제외), 낙찰가×1.02 이하인 건은 이상치로 제외.
낙찰 확률: 낙찰가 ÷ 예상매도가가 r 이하인 사건 비율 = "예상매도가의 r로 썼다면 낙찰됐을 비율"(1등보다 높게 쓰면 낙찰).
손해(근사): 재매도가 < 낙찰가 × 1.05 + 400만(비율 비용 5% + 명도·이사·청소·법무 고정 400만 가정 - 앱의 정밀 비용 계산은 아님).
⚠️ 2026-10 사용자 기준: "경매의 핵심은 낙찰될 가격이 아니라 낙찰·매도 후 수익을 구현할 수 있는지", "누구나 1등으로 보는
인기 물건보다 객관적 지표로 틈새를 찾는 게 중요" - 그래서 핵심 결과는 낙찰 확률이 아니라 "입찰 전에 알 수 있는 조건별로
낙찰자가 실제로 번 돈(실현 수익률)과 경쟁(입찰자 수)"이고, 수익은 높은데 입찰자가 적은 조건(틈새)을 찾아 순위를 매김.
실현 수익률(근사) = (재매도가 − 낙찰가 × 1.07) ÷ 낙찰가. 재매도 안 된 건은 수익을 알 수 없어 "재매도 비율"로 따로 봄.
결과: leader_follower_cache 'bidcase|__validation__' + GitHub 요약.
"""
import os
import re
import json
import math
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import requests
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py"))
cyc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cyc)
avm = cyc.avm

SITE_URL = (os.environ.get("SITE_URL") or "https://1234auction.vercel.app").rstrip("/")
GROUND_RATIO = 0.915
COST_RATIO = 1.05          # 비율 비용(취득세·등기·중개·이자 등)
FIXED_COST = 400           # 고정 비용(만원: 명도·이사·청소·법무 등) - 저가 물건에서 비중이 커서 따로 둠


def sido_norm(s):
    s = str(s or "")
    if s.startswith(("전남광주", "광주", "전남", "전라남")):
        return "전남광주"
    if s.startswith(("전북", "전라북")):
        return "전북"
    if s.startswith(("경남", "경상남")):
        return "경남"
    if s.startswith(("경북", "경상북")):
        return "경북"
    if s.startswith(("충남", "충청남")):
        return "충남"
    if s.startswith(("충북", "충청북")):
        return "충북"
    return s[:2]


def region_norm(addr_or_region):
    t = str(addr_or_region or "").split()
    if len(t) < 2:
        return None
    # 2026-10: 구가 있는 시는 실거래가 "전북 전주 완산구", 낙찰사례 주소가 "전북 전주시 완산구"라 서로 못 맞췄음 → 뒤에 구가 오면 "시"를 뗌
    city = t[1]
    if len(t) >= 3 and city.endswith("시") and t[2].endswith("구"):
        city = city[:-1]
    return sido_norm(t[0]) + " " + city


def dong_key(d):
    t = str(d or "").split()
    return t[-1] if t else ""


def ymd_int(d):
    return d.year * 10000 + d.month * 100 + d.day


def int_to_date(v):
    v = int(v)
    return datetime(v // 10000, (v // 100) % 100, v % 100)


def fails_from_ratio(r):
    if r is None or not np.isfinite(r):
        return None
    if r >= 0.995:
        return 0
    for n in range(1, 8):
        for lv in (0.8 ** n, 0.7 ** n, 0.7 * 0.8 ** (n - 1)):
            if abs(lv - r) < 0.004:
                return n
    return None


def main():
    now = datetime.now(timezone.utc).isoformat()
    print("🏃 낙찰사례 검증 시작", now)
    cases = requests.get(f"{SITE_URL}/api/auction?kind=bidCases", timeout=120).json()
    df = pd.DataFrame(cases)
    print(f"  낙찰사례 {len(df):,}건")
    df = df[df["propertyType"].astype(str).str.contains("아파트", na=False)]
    df = df[pd.to_numeric(df["finalBidPrice"], errors="coerce") > 0]
    df = df[df["saleDate"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)]
    df["actual"] = pd.to_numeric(df["finalBidPrice"]) / 10000.0
    df["appraisal"] = pd.to_numeric(df["appraisalPrice"], errors="coerce") / 10000.0
    df["minbid"] = pd.to_numeric(df["minBidPrice"], errors="coerce") / 10000.0
    df["second"] = pd.to_numeric(df.get("secondBidPrice"), errors="coerce") / 10000.0
    df["bidders"] = pd.to_numeric(df.get("bidders"), errors="coerce")
    df["area"] = pd.to_numeric(df["areaM2"], errors="coerce")
    df["floor_n"] = pd.to_numeric(df["floor"], errors="coerce")
    df["region"] = df["addrJibun"].map(region_norm)
    df["sido"] = df["region"].map(lambda r: r.split()[0] if r else None)
    df["dk"] = df["dong"].map(dong_key)
    # 2026-10: CSV 사례는 지번이 본번만("22") 있는 경우가 있어 주소의 "동 22-7"을 먼저 씀
    def full_bunji(row):
        d = str(row.get("dong") or "")
        m = re.search(re.escape(d) + r"\s+(산?\d+(?:-\d+)?)", str(row.get("addrJibun") or "")) if d else None
        return m.group(1).replace("산", "").strip() if m else str(row.get("bunji") or "").strip()
    df["bunji_s"] = df.apply(full_bunji, axis=1)
    # 낙찰된 집의 동(棟) - 주소 끝("… 절영아파트 215동")이나 호수 칸("215동 102호")
    def case_adong(row):
        ad = row.get("aptDong")
        if isinstance(ad, str) and ad.strip().isdigit():
            return str(int(ad.strip()))
        txt = str(row.get("addrJibun") or "")
        b = str(row.get("bunji") or "")
        tail = txt.split(b, 1)[1] if b and b in txt else txt
        for t in (tail, str(row.get("unitNo") or "")):
            m = re.search(r"(\d{1,4})\s*동(?![가-힣])", t)
            if m:
                return str(int(m.group(1)))
        return None
    df["adong"] = df.apply(case_adong, axis=1)
    df["sale_int"] = df["saleDate"].str.replace("-", "").astype(int)
    df["fails"] = (df["minbid"] / df["appraisal"]).map(fails_from_ratio)
    df = df.dropna(subset=["region", "area", "dk"]).reset_index(drop=True)
    print(f"  아파트·낙찰가 있음 {len(df):,}건, 지역 {df['region'].nunique()}곳")

    # ── 실거래(2017~) - 대상 시군구만 ──
    want = set(df["region"].unique())
    names = set()
    for r in want:
        sd, gu = r.split(" ", 1)
        for alias in ({"전남광주": ["전남광주", "광주", "전남"]}.get(sd, [sd])):
            names.add(f"{alias} {gu}")
    # 실거래 지역명은 "전북 전주 완산구"처럼 구까지 붙어 있어 정확히 같은 이름(in)으로는 못 찾음 → 앞부분 일치(like)로
    flt = "&or=(" + ",".join('region.like."' + n + '*"' for n in sorted(names)) + ")"
    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,build_year,apt_dong,cdeal_type",
                            extra_filter=f"&deal_date=gte.{cyc.START_DATE}{flt}")
    # 2026-10: 해제(취소)된 거래는 시세·되팔기 모두에서 뺌(응답의 3~8%)
    if "cdeal_type" in tr.columns:
        tr = tr[tr["cdeal_type"].fillna("").astype(str).str.strip() == ""].copy()
    # 되팔기 매칭용 직거래 포함본(가족·지인 간 매도도 "팔았다"에 해당) - 시세 추정은 직거래 제외본으로
    tr_all = tr.copy()
    tr = tr[tr["dealing_type"] != "직거래"].copy() if "dealing_type" in tr.columns else tr
    for c in ("price", "size", "floor", "deal_date", "build_year"):
        tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"])
    tr = tr[(tr["price"] > 0) & (tr["size"] > 10)]
    tr["region_n"] = tr["region"].map(region_norm)
    tr["dk"] = tr["dong"].map(dong_key)
    tr["bunji_s"] = tr["bunji"].astype(str).str.strip()
    tr["ppm"] = tr["price"] / tr["size"]
    tr["ym"] = (tr["deal_date"] // 100).astype(int)
    print(f"  실거래 {len(tr):,}건")
    def norm_adong(v):
        m = re.search(r"(\d{1,4})", str(v or ""))
        return str(int(m.group(1))) if m else ""
    for c_ in ("price", "size", "floor", "deal_date"):
        tr_all[c_] = pd.to_numeric(tr_all[c_], errors="coerce")
    tr_all = tr_all.dropna(subset=["price", "size", "deal_date"])
    tr_all["dk"] = tr_all["dong"].map(dong_key)
    tr_all["region_n"] = tr_all["region"].map(region_norm)
    tr_all["bunji_s"] = tr_all["bunji"].astype(str).str.strip()
    tr_all["adong"] = tr_all["apt_dong"].map(norm_adong) if "apt_dong" in tr_all.columns else ""
    groups_all = {k: g for k, g in tr_all.groupby(["region_n", "dk", "bunji_s"])}
    print(f"  되팔기 매칭용(직거래 포함·해제 제외) {len(tr_all):,}건, 동 정보 있는 거래 {int((tr_all['adong'] != '').sum()):,}건")

    # 시군구 월별 지수(평당가 중앙값, 3개월 이동평균) - 3년 창을 쓸 때 입찰 시점 가격으로 맞추는 데 씀
    idx = tr.groupby(["region_n", "ym"])["ppm"].median().rename("m").reset_index()
    idx_map = {}
    months = []
    y, m = 2017, 1
    while y * 100 + m <= int(datetime.now().strftime("%Y%m")):
        months.append(y * 100 + m)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    for rg, g in idx.groupby("region_n"):
        s = g.set_index("ym")["m"].sort_index().rolling(3, min_periods=1).median()
        idx_map[rg] = s.reindex(months).ffill().to_dict()  # 빈 달은 직전 값으로 채워 바로 찾기

    def idx_at(rg, ym):
        d = idx_map.get(rg)
        v = d.get(int(ym)) if d else None
        return v if v is not None and np.isfinite(v) else None

    groups = {k: g for k, g in tr.groupby(["region_n", "dk", "bunji_s"])}
    # 동 전체 거래 날짜(정렬) - 입찰 전 3년 동 거래량(거래가 되는 동네인지)
    dong_dates = {k: np.sort(g["deal_date"].to_numpy()) for k, g in tr.groupby(["region_n", "dk"])}
    # 인기 등급(현재 기준 - 약간의 미래 정보가 섞임): pop|<시군구>
    pop = {}
    try:
        ids = ["pop|" + r for r in want]
        url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/leader_follower_cache"
        hdr = {"apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"], "Authorization": "Bearer " + os.environ["SUPABASE_SERVICE_ROLE_KEY"]}
        for i in range(0, len(ids), 20):
            q = ",".join('"' + x + '"' for x in ids[i:i + 20])
            res = requests.get(url, headers=hdr, params={"select": "id,payload", "id": f"in.({q})"}, timeout=60).json()
            for row in res or []:
                rg = row["id"].split("|", 1)[1]
                p = row["payload"] or {}
                for dg, lst in (p.get("byDong") or {}).items():
                    for x in lst:
                        pop[(rg, dong_key(dg), avm.normalize_complex_name(x.get("danji")))] = x.get("tier")
                for dg, bands in (p.get("byDongBand") or {}).items():
                    for bn, lst in (bands or {}).items():
                        for x in lst:
                            pop[(rg, dong_key(dg), avm.normalize_complex_name(x.get("danji")), bn)] = x.get("tier")
    except Exception as e:
        print("  인기 등급 불러오기 실패(건너뜀):", e)

    out = []
    for c in df.itertuples():
        g = groups.get((c.region, c.dk, c.bunji_s))
        rec = {"id": getattr(c, "id", None), "region": c.region, "sido": c.sido, "resale_date": None, "resale_floor": None, "resale_size": None, "sale": c.sale_int, "actual": c.actual, "second": c.second, "bidders": c.bidders,
               "appraisal": c.appraisal, "minbid": c.minbid, "fails": c.fails, "est": None, "own": 0, "resale": None, "resale_m": None, "tier": None,
               "area": c.area, "floor": c.floor_n, "cx3y": 0, "age": None, "bandTier": None,
               "notes": str(getattr(c, "specialConditions", "") or ""), "land": str(getattr(c, "landType", "") or ""),
               "dk": c.dk, "dongName": str(c.dong), "cx": None, "dong3y": 0,
               "adong": c.adong if isinstance(c.adong, str) and c.adong else None}
        dd = dong_dates.get((c.region, c.dk))
        if dd is not None:
            _sd = int_to_date(c.sale_int)
            _cut = ymd_int(_sd - timedelta(days=30))
            rec["dong3y"] = int(np.searchsorted(dd, _cut) - np.searchsorted(dd, ymd_int(_sd - timedelta(days=30 + 1095))))
        if g is not None and len(g):
            same = g[(g["size"] - c.area).abs() <= 2]
            sale_d = int_to_date(c.sale_int)
            cut = ymd_int(sale_d - timedelta(days=30))
            ground = (c.floor_n == 1)
            hist = same[same["deal_date"] < cut]
            tier_same = hist[(hist["floor"] == 1) == ground] if pd.notna(c.floor_n) else hist
            other = hist[(hist["floor"] == 1) != ground] if pd.notna(c.floor_n) else hist.iloc[0:0]
            cut_ym = cut // 100
            est = None; own = 0
            for days in (365, 1095):
                lo = ymd_int(sale_d - timedelta(days=30 + days))
                use = tier_same[tier_same["deal_date"] >= lo]
                adj = 1.0
                if len(use) == 0:
                    use = other[other["deal_date"] >= lo]
                    adj = GROUND_RATIO if ground else 1 / GROUND_RATIO
                if len(use) >= 3 or (days == 1095 and len(use) >= 1):
                    base = idx_at(c.region, cut_ym)
                    vals = []
                    for t in use.itertuples():
                        f = 1.0
                        if days == 1095 and base:
                            b0 = idx_at(c.region, t.ym)
                            if b0:
                                f = max(0.7, min(1.4, base / b0))
                        vals.append(t.ppm * f * adj)
                    vals = np.sort(np.array(vals))
                    est = float(np.quantile(vals, 0.4)) * c.area
                    own = len(use)
                    break
            rec["est"] = est; rec["own"] = own
            # 재매도 - 2026-10 정확도 개선: 큰 단지는 같은 층에 같은 평형이 여러 채라 "같은 층 첫 거래"의 절반 이상이 다른 집이었음
            # (낙찰 12개월 안 같은 층 거래 56% vs 2층 위·아래 층 43%). 2023년부터 실거래에 동(棟)이 있어 같은 동·같은 층으로 좁힘:
            #  ① 낙찰 물건의 동을 알고 거래에도 동이 있으면 같은 동만(conf=dong) ② 거래에 동이 없으면(2023년 이전·등기 전) 층만 맞춤(conf=floor, 확신 낮음)
            #  ③ 같은 층 거래가 전부 다른 동이면 되판 것으로 보지 않음. 직거래(가족·지인 매도)도 "팔았다"에 포함.
            g_all = groups_all.get((c.region, c.dk, c.bunji_s))
            if pd.notna(c.floor_n) and g_all is not None:
                after = g_all[((g_all["size"] - c.area).abs() <= 2) & (g_all["deal_date"] >= ymd_int(sale_d + timedelta(days=14))) & (g_all["floor"] == c.floor_n)].sort_values("deal_date")
                conf = "floor"
                # 낙찰가의 70% 미만 거래(가족 간 직거래·다른 집 등)는 후보에서 빼고 그다음 거래를 봄
                after = after[after["price"] >= c.actual * 0.7]
                case_dong = c.adong if isinstance(c.adong, str) and c.adong else None  # ⚠️ 동이 없는 사례는 NaN(참으로 판정됨) - 문자열일 때만
                if len(after) and case_dong:
                    after = after[(after["adong"] == case_dong) | (after["adong"] == "")]
                    if len(after) and after.iloc[0]["adong"] == case_dong:
                        conf = "dong"
                if len(after):
                    t0 = after.iloc[0]
                    rec["resale_conf"] = conf
                    # 낙찰가 이하 매도도 포함(예전엔 이상치로 보고 뺐는데, 그러면 실제 손해 매도가 빠져 수익이 부풀려짐).
                    # 낙찰가의 70% 미만처럼 같은 집으로 보기 어려운 경우만 제외.
                    if t0["price"] >= c.actual * 0.7:
                        rec["resale"] = float(t0["price"])
                        rec["resale_date"] = str(int(t0["deal_date"]))
                        rec["resale_floor"] = int(t0["floor"]) if pd.notna(t0["floor"]) else None
                        rec["resale_size"] = float(t0["size"])
                        rec["resale_m"] = round((int_to_date(int(t0["deal_date"])) - sale_d).days / 30.4, 1)
            nm = avm.normalize_complex_name(g["danji"].mode().iloc[0]) if len(g) else None
            rec["tier"] = pop.get((c.region, c.dk, nm))
            rec["cx"] = nm
            band = "소형" if c.area < 60 else ("중형" if c.area <= 85 else "대형")
            rec["bandTier"] = pop.get((c.region, c.dk, nm, band))
            # 단지 전체 최근 3년 거래(입찰 전 기준) - 거래 활발도
            rec["cx3y"] = int(((g["deal_date"] < cut) & (g["deal_date"] >= ymd_int(sale_d - timedelta(days=30 + 1095)))).sum())
            by = pd.to_numeric(g["build_year"], errors="coerce").dropna()
            if len(by):
                rec["age"] = int(sale_d.year - int(by.mode().iloc[0]))
        out.append(rec)
    R = pd.DataFrame(out)
    R["ratio"] = R["actual"] / R["est"]
    R["err"] = (R["est"] - R["resale"]) / R["resale"]
    R["second_gap"] = (R["actual"] - R["second"]) / R["est"]
    R["loss"] = R["resale"] < R["actual"] * COST_RATIO + FIXED_COST
    obs_cut = ymd_int(datetime.now() - timedelta(days=270))  # 낙찰 후 9개월 이상 지난 건만 재매도 비율 계산

    def med(s):
        s = pd.Series(s).dropna()
        return round(float(s.median()), 3) if len(s) else None

    def block(G):
        e = G.dropna(subset=["est"])
        w = e[e["resale"].notna()]
        old = G[G["sale"] <= obs_cut]
        win = {}
        for r in (0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00):
            win[f"{int(r * 100)}%"] = round(float((e["ratio"] <= r).mean()) * 100, 1) if len(e) else None
        return {
            "n": int(len(G)), "estCoveragePct": round(len(e) / len(G) * 100, 1) if len(G) else None,
            "saleErrMedAbsPct": round(float(w["err"].abs().median()) * 100, 1) if len(w) else None,
            "saleErrBiasPct": round(float(w["err"].median()) * 100, 1) if len(w) else None,
            "resaleChecked": int(len(w)),
            "actualOverEstMed": med(e["ratio"]),
            "winProbByBidRatio": win,
            "secondGapMedPctOfEst": round(float(e["second_gap"].dropna().median()) * 100, 1) if e["second_gap"].notna().any() else None,
            "biddersMed": med(G["bidders"]),
            "resaleRateOld": round(float(old["resale"].notna().mean()) * 100, 1) if len(old) else None,
            "resaleMonthsMed": med(G["resale_m"]),
            "winnerLossPct": round(float(G.loc[G["resale"].notna(), "loss"].mean()) * 100, 1) if G["resale"].notna().any() else None,
        }

    summary = {"generatedAt": now, "n": int(len(R)), "all": block(R), "bySido": {}, "byFails": {}, "byBidders": {}, "byTierFails": {}, "byOwn": {}}
    for sd, G in R.groupby("sido"):
        summary["bySido"][sd] = block(G)
    R["fails_b"] = R["fails"].map(lambda f: "신건" if f == 0 else ("1회 유찰" if f == 1 else ("2회+ 유찰" if f and f >= 2 else None)))
    for k, G in R.groupby("fails_b"):
        summary["byFails"][k] = block(G)
    R["bid_b"] = R["bidders"].map(lambda b: None if pd.isna(b) else ("1명" if b <= 1 else ("2~3명" if b <= 3 else ("4~9명" if b <= 9 else "10명+"))))
    for k, G in R.groupby("bid_b"):
        summary["byBidders"][k] = block(G)
    R["own_b"] = R["own"].map(lambda o: "같은 단지 3건+" if o >= 3 else ("1~2건" if o >= 1 else "없음"))
    for k, G in R.groupby("own_b"):
        summary["byOwn"][k] = block(G)
    for (t, f), G in R.dropna(subset=["tier", "fails_b"]).groupby(["tier", "fails_b"]):
        summary["byTierFails"][f"{t}|{f}"] = block(G)

    # ── 틈새 찾기: 입찰 전에 알 수 있는 조건별 실현 수익 ──
    R["net"] = (R["resale"] - R["actual"] * COST_RATIO - FIXED_COST) / R["actual"]
    R["net_abs"] = R["resale"] - R["actual"] * COST_RATIO - FIXED_COST   # 실현 순이익(만원)
    R["band"] = R["area"].map(lambda a: "소형" if a < 60 else ("중형" if a <= 85 else "대형"))
    R["floor_b"] = R["floor"].map(lambda f: None if pd.isna(f) else ("1층" if f <= 1 else ("2~3층" if f <= 3 else "4층+")))
    R["age_b"] = R["age"].map(lambda a: None if a is None or pd.isna(a) else ("10년 이하" if a <= 10 else ("11~20년" if a <= 20 else ("21~30년" if a <= 30 else "30년 초과"))))
    R["price_b"] = R["actual"].map(lambda v: "1억 미만" if v < 10000 else ("1~2억" if v < 20000 else ("2~3억" if v < 30000 else ("3~5억" if v < 50000 else "5억+"))))
    R["liq_b"] = R["cx3y"].map(lambda n: "3년 거래 0~5건" if n <= 5 else ("6~20건" if n <= 20 else ("21~60건" if n <= 60 else "61건+")))
    R["disc"] = R["minbid"] / R["est"]
    R["disc_b"] = R["disc"].map(lambda d: None if pd.isna(d) else ("최저가 시세 70% 미만" if d < 0.7 else ("70~80%" if d < 0.8 else ("80~90%" if d < 0.9 else "90%+"))))
    R["appr_b"] = (R["appraisal"] / R["est"]).map(lambda d: None if pd.isna(d) else ("감정가<시세 90%" if d < 0.9 else ("감정가≈시세" if d <= 1.1 else "감정가>시세 110%")))
    R["note_b"] = R["notes"].map(lambda t: "토지별도등기" if "토지별도" in t else ("외 필지" if "필지" in t else "특이사항 없음"))
    R["tier_b"] = R["tier"].fillna("자료없음")
    R["bandTier_b"] = R["bandTier"].fillna("자료없음")
    R = R[R["land"] != "none"]
    OLD = R[R["sale"] <= obs_cut]

    def seg_stats(G):
        res = G[G["resale"].notna()]
        old = G[G["sale"] <= obs_cut]
        if len(res) == 0:
            return None
        return {"n": int(len(G)), "resold": int(len(res)),
                "netMedPct": round(float(res["net"].median()) * 100, 1),
                "netMedManwon": int(res["net_abs"].median()),
                "profitPct": round(float((res["net"] > 0).mean()) * 100, 1),
                "bigLossPct": round(float((res["net"] < -0.05).mean()) * 100, 1),
                "biddersMed": med(G["bidders"]),
                "resaleRateOld": round(float(old["resale"].notna().mean()) * 100, 1) if len(old) >= 10 else None,
                "monthsMed": med(res["resale_m"])}

    FEATS = ["fails_b", "tier_b", "bandTier_b", "band", "floor_b", "age_b", "price_b", "liq_b", "disc_b", "appr_b", "note_b"]
    single = {}
    for sd, GS in [("전체", R)] + list(R.groupby("sido")):
        single[sd] = {}
        for f in FEATS:
            single[sd][f] = {str(k): seg_stats(G) for k, G in GS.groupby(f) if seg_stats(G)}
    summary["profitBySingleFeature"] = single
    # 두 조건 조합 - 재매도 확인 30건 이상만, 수익률 높고 입찰자 적은 순(틈새 점수 = 수익률 중앙값 − 입찰자 1명당 0.3%p)
    combos = []
    for sd, GS in [("전체", R)] + list(R.groupby("sido")):
        for i, f1 in enumerate(FEATS):
            for f2 in FEATS[i + 1:]:
                for (k1, k2), G in GS.groupby([f1, f2]):
                    st = seg_stats(G)
                    if not st or st["resold"] < 30:
                        continue
                    base = GS[GS["resale"].notna()]["net"].median()
                    st.update({"sido": sd, "cond": f"{f1}={k1} & {f2}={k2}",
                               "vsRegionPctp": round((st["netMedPct"] / 100 - float(base)) * 100, 1),
                               "nicheScore": round(st["netMedPct"] - 0.3 * (st["biddersMed"] or 0), 1)})
                    combos.append(st)
    combos.sort(key=lambda x: -x["nicheScore"])
    summary["nicheTop"] = {sd: [c for c in combos if c["sido"] == sd and c["profitPct"] >= 70 and c["netMedManwon"] >= 1000][:15] for sd in ["전체"] + sorted(R["sido"].dropna().unique())}
    summary["crowdedWorst"] = sorted([c for c in combos if c["sido"] == "전체"], key=lambda x: x["netMedPct"])[:10]

    # ── 관심도: 거래는 되는데 입찰자가 덜 몰리는 곳(사용자 정의 틈새) ──
    # 유찰 단계마다 입찰자 수가 달라서(신건<1회<2회+) 같은 시도·같은 유찰 단계의 보통 입찰자 수로 나눠 비교.
    summary.update(attention_analysis(R, seg_stats, med))

    print(json.dumps(summary, ensure_ascii=False, indent=1))
    try:
        competition_stats(R, now)
    except Exception as e:
        print("  지역 경쟁 강도 계산 실패(건너뜀):", e)
    write_back_resale_matches(cases, out)
    try:
        write_back_villa_matches(cases)
    except Exception as e:
        print("  빌라 매칭 실패(건너뜀):", e)
    cyc.upsert_rows([{"id": "bidcase|__validation__", "payload": cyc.clean_json(summary), "fetched_at": now}])
    print("✅ 저장 완료")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("## 낙찰사례 검증\n\n```\n" + json.dumps(summary, ensure_ascii=False, indent=1) + "\n```\n")


def write_back_resale_matches(cases, out):
    """2026-10: 낙찰사례의 "매도 매칭"을 2017년 이후 전체 실거래로 채워 저장. 예전 매칭(scripts/match-bid-cases.mjs)은
    주 120건씩·최근 2년 실거래만 봐서, CSV로 올린 7천 건 중 6,852건이 시도조차 안 된 상태였음.
    기준: 같은 시군구·동·지번, 전용 ±2㎡, 같은 층, 낙찰 14일 뒤 첫 중개거래(직거래 제외), 낙찰가의 70% 이상."""
    if os.environ.get("WRITE_BACK", "1") != "1":
        return
    by_id = {str(c.get("id")): c for c in cases if c.get("id") is not None}
    now_s = datetime.now().strftime("%Y-%m-%d")
    changed = []
    for r in out:
        c = by_id.get(str(r.get("id")))
        if not c:
            continue
        if r.get("resale"):
            m = {"date": r["resale_date"], "amount": int(r["resale"]), "floor": r["resale_floor"], "area": r["resale_size"],
                 "approx": False, "source": "db-full", "conf": r.get("resale_conf") or "floor"}
            old = c.get("resaleMatch") or {}
            if str(old.get("date")) == m["date"] and int(old.get("amount") or 0) == m["amount"] and old.get("conf") == m["conf"]:
                continue
            c2 = dict(c); c2["resaleMatch"] = m; c2["matchFailReason"] = None
        else:
            if c.get("resaleMatch") and (c.get("resaleMatch") or {}).get("source") != "db-full":
                continue  # 예전 방식으로 찾은 매칭(층 ±1 등)은 지우지 않음
            reason = "낙찰 후 같은 층·평형 매매 없음(" + now_s + " 기준)"
            if c.get("matchAttempted") and c.get("matchFailReason") == reason:
                continue
            c2 = dict(c); c2["resaleMatch"] = None; c2["matchFailReason"] = reason
        c2["matchAttempted"] = True
        c2["estMargin"] = None; c2["estRoi"] = None; c2["estTotalCost"] = None
        changed.append(c2)
    print(f"  매도 매칭 저장: 바뀐 {len(changed):,}건 (매칭됨 {sum(1 for x in changed if x.get('resaleMatch')):,})")
    for i in range(0, len(changed), 300):
        part = changed[i:i + 300]
        for attempt in range(3):
            try:
                r = requests.post(f"{SITE_URL}/api/auction?kind=bidCases", json=part, timeout=120)
                if r.status_code == 200:
                    break
                print("   저장 실패", r.status_code, r.text[:200])
            except Exception as e:
                print("   저장 오류", e)
        else:
            print("   ⚠️ 이 묶음은 건너뜀", i)


def write_back_villa_matches(cases):
    """2026-10: 빌라(연립·다세대) 낙찰사례도 같은 기준으로 되판 기록을 찾아 저장 - 빌라 판정 검증용.
    villa_trades(2017~)에서 같은 시군구·동·지번, 전용 ±2㎡, 같은 층, 낙찰 14일 뒤 첫 매매(직거래 제외), 낙찰가의 70% 이상."""
    V = pd.DataFrame([c for c in cases if c.get("id") is not None])
    if V.empty:
        return
    V = V[~V["propertyType"].astype(str).str.contains("아파트|오피스텔|상가|토지|근린|공장|숙박|임야|대지|전|답", na=False, regex=True)]
    V = V[pd.to_numeric(V["finalBidPrice"], errors="coerce") > 0]
    V = V[V["saleDate"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)].copy()
    if V.empty:
        return
    V["actual"] = pd.to_numeric(V["finalBidPrice"]) / 10000.0
    V["area"] = pd.to_numeric(V["areaM2"], errors="coerce")
    V["floor_n"] = pd.to_numeric(V["floor"], errors="coerce")
    V["region"] = V["addrJibun"].map(region_norm)
    V["dk"] = V["dong"].map(dong_key)
    V["bunji_s"] = V["bunji"].astype(str).str.strip()
    V["sale_int"] = V["saleDate"].str.replace("-", "").astype(int)
    V = V.dropna(subset=["region", "area", "dk", "floor_n"])
    print(f"  빌라 낙찰사례 {len(V):,}건 매칭 시작")
    names = set()
    for r in V["region"].unique():
        sd, gu = r.split(" ", 1)
        for alias in ({"전남광주": ["전남광주", "광주", "전남"]}.get(sd, [sd])):
            names.add(f"{alias} {gu}")
    # 실거래 지역명은 "전북 전주 완산구"처럼 구까지 붙어 있어 정확히 같은 이름(in)으로는 못 찾음 → 앞부분 일치(like)로
    flt = "&or=(" + ",".join('region.like."' + n + '*"' for n in sorted(names)) + ")"
    tr = avm.fetch_all_rows("villa_trades", cols="region,dong,bunji,price,size,floor,deal_date,dealing_type",
                            extra_filter=f"&deal_date=gte.{cyc.START_DATE}{flt}")
    if tr is None or len(tr) == 0:
        return
    tr = tr[tr["dealing_type"] != "직거래"].copy() if "dealing_type" in tr.columns else tr
    for c in ("price", "size", "floor", "deal_date"):
        tr[c] = pd.to_numeric(tr[c], errors="coerce")
    tr = tr.dropna(subset=["price", "size", "deal_date"])
    tr["region_n"] = tr["region"].map(region_norm)
    tr["dk"] = tr["dong"].map(dong_key)
    tr["bunji_s"] = tr["bunji"].astype(str).str.strip()
    groups = {k: g for k, g in tr.groupby(["region_n", "dk", "bunji_s"])}
    out = []
    for c in V.itertuples():
        rec = {"id": c.id, "resale": None}
        g = groups.get((c.region, c.dk, c.bunji_s))
        if g is not None:
            sale_d = int_to_date(c.sale_int)
            after = g[((g["size"] - c.area).abs() <= 2) & (g["floor"] == c.floor_n) & (g["deal_date"] >= ymd_int(sale_d + timedelta(days=14)))]
            if len(after):
                t0 = after.sort_values("deal_date").iloc[0]
                if t0["price"] >= c.actual * 0.7:
                    rec.update({"resale": float(t0["price"]), "resale_date": str(int(t0["deal_date"])), "resale_floor": int(t0["floor"]), "resale_size": float(t0["size"])})
        out.append(rec)
    print(f"  빌라 되판 기록 {sum(1 for r in out if r['resale']):,}건")
    write_back_resale_matches(cases, out)


def attention_analysis(R, seg_stats, med):
    R = R.copy()
    R = R[R["fails_b"].notna()]
    norm = R.dropna(subset=["bidders"]).groupby(["sido", "fails_b"])["bidders"].median().to_dict()
    R["att"] = [b / norm[(sd, f)] if pd.notna(b) and norm.get((sd, f)) else np.nan for b, sd, f in zip(R["bidders"], R["sido"], R["fails_b"])]
    R["att_b"] = R["att"].map(lambda a: None if pd.isna(a) else ("관심 적음" if a <= 0.6 else ("보통" if a < 1.4 else "관심 많음")))
    R["trad_b"] = R["cx3y"].map(lambda n: "단지 3년 거래 6건+" if n >= 6 else "단지 거래 드묾")
    R["dong_b"] = R["dong3y"].map(lambda n: "동 3년 거래 0~60건" if n <= 60 else ("61~300건" if n <= 300 else "301건+"))
    out = {"attentionNorm": {f"{k[0]}|{k[1]}": v for k, v in norm.items()}}

    # 1) 관심도 × 거래 가능 → 실현 수익
    t1 = {}
    for sd, GS in [("전체", R)] + list(R.groupby("sido")):
        t1[sd] = {}
        for (ab, tb), G in GS.dropna(subset=["att_b"]).groupby(["att_b", "trad_b"]):
            st = seg_stats(G)
            if st:
                st["winVsEstMed"] = med(G["ratio"])
                t1[sd][f"{ab}|{tb}"] = st
    out["attentionProfit"] = t1

    # 2) 같은 동의 과거 관심도가 이어지는지(입찰 전 정보만): 이 사건 이전 같은 동 사례 2건+의 관심도 중앙값
    R = R.sort_values("sale")
    prev_att = []
    hist = {}
    for r in R.itertuples():
        k = (r.region, r.dk)
        h = hist.get(k, [])
        prev_att.append(float(np.median(h)) if len(h) >= 2 else np.nan)
        if pd.notna(r.att):
            hist.setdefault(k, []).append(r.att)
    R["prev_att"] = prev_att
    R["prev_b"] = R["prev_att"].map(lambda a: None if pd.isna(a) else ("과거 관심 적던 동" if a <= 0.7 else ("과거 보통" if a < 1.3 else "과거 관심 많던 동")))
    t2 = {}
    for sd, GS in [("전체", R)] + list(R.groupby("sido")):
        t2[sd] = {}
        for (pb, tb), G in GS.dropna(subset=["prev_b"]).groupby(["prev_b", "trad_b"]):
            st = seg_stats(G) or {"n": int(len(G)), "resold": 0}
            st["attNowMed"] = med(G["att"])
            st["biddersMed"] = med(G["bidders"])
            st["winVsEstMed"] = med(G["ratio"])
            t2[sd][f"{pb}|{tb}"] = st
    out["dongAttentionPersistence"] = t2

    # 3) 입찰 전에 알 수 있는 조건 중 '관심 적음'과 이어지는 것(거래 되는 단지만)
    T = R[(R["trad_b"] == "단지 3년 거래 6건+") & R["att"].notna()]
    t3 = {}
    for f in ["tier_b", "bandTier_b", "band", "floor_b", "age_b", "price_b", "liq_b", "dong_b", "appr_b", "note_b"]:
        t3[f] = {}
        for k, G in T.groupby(f):
            if len(G) < 30:
                continue
            st = seg_stats(G) or {"n": int(len(G))}
            st["attMed"] = med(G["att"])
            st["lowAttPct"] = round(float((G["att"] <= 0.6).mean()) * 100, 1)
            t3[f][str(k)] = st
    out["attentionPredictors"] = t3

    # 4) 동 목록: 거래는 되는데(동 3년 거래 60건+ 또는 단지 6건+) 입찰자가 적은 동 - 앱 표시용
    D = []
    for (rg, dk), G in R[R["att"].notna()].groupby(["region", "dk"]):
        if len(G) < 3:
            continue
        res = G[G["resale"].notna()]
        D.append({"region": rg, "dong": G["dongName"].mode().iloc[0], "dk": dk, "cases": int(len(G)),
                  "attMed": round(float(G["att"].median()), 2), "biddersMed": med(G["bidders"]),
                  "dong3yMed": int(G["dong3y"].median()), "tradableShare": round(float((G["cx3y"] >= 6).mean()), 2),
                  "resold": int(len(res)), "netMedManwon": int(res["net_abs"].median()) if len(res) else None,
                  "profitPct": round(float((res["net"] > 0).mean()) * 100, 1) if len(res) else None,
                  "winVsEstMed": med(G["ratio"])})
    out["dongAttention"] = sorted(D, key=lambda x: x["attMed"])

    # 5) "순수익 1천만 원 목표"로 입찰했다면 - 사용자가 실제로 쓰는 기준(지방 아파트 1천만 원)으로 조건별 결과를 봄.
    #    입찰가 = (예상매도가 − 고정비 − 매도 부가세 − 1천만) ÷ 비율비용. 실제 낙찰가 이상이면 낙찰로 보고,
    #    되판 기록이 있으면 그 가격으로 실현 순이익 계산. 85㎡ 초과는 매매사업자 건물분 부가세(매도가×65%×10/110) 포함.
    TARGET = 1000
    vat = lambda sale, area: sale * 0.65 * 0.1 / 1.1 if area and area > 85 else 0.0
    S = R[R["est"].notna()].copy()
    S["myBid"] = [(e - FIXED_COST - vat(e, a) - TARGET) / COST_RATIO for e, a in zip(S["est"], S["area"])]
    S["win"] = S["myBid"] >= S["actual"]
    S["myNet"] = [(rs - b * COST_RATIO - FIXED_COST - vat(rs, a)) if pd.notna(rs) else np.nan for rs, b, a in zip(S["resale"], S["myBid"], S["area"])]
    S["winnerNetVat"] = [(rs - ac * COST_RATIO - FIXED_COST - vat(rs, a)) if pd.notna(rs) else np.nan for rs, ac, a in zip(S["resale"], S["actual"], S["area"])]

    def sim(G):
        W = G[G["win"]]
        WR = W[W["myNet"].notna()]
        GR = G[G["winnerNetVat"].notna()]
        return {"n": int(len(G)), "winPct": round(float(G["win"].mean()) * 100, 1) if len(G) else None,
                "wins": int(len(W)), "winsResold": int(len(WR)),
                "myNetMed": int(WR["myNet"].median()) if len(WR) else None,
                "myHit1000Pct": round(float((WR["myNet"] >= TARGET).mean()) * 100, 1) if len(WR) else None,
                "myLossPct": round(float((WR["myNet"] < 0).mean()) * 100, 1) if len(WR) else None,
                "winnerNetVatMed": int(GR["winnerNetVat"].median()) if len(GR) else None}
    t5 = {}
    for sd, GS in [("전체", S)] + list(S.groupby("sido")):
        t5[sd] = {"전체": sim(GS)}
        for f in ["att_b", "liq_b", "band", "tier_b", "bandTier_b", "price_b", "note_b", "fails_b", "prev_b"]:
            for k, G in GS.groupby(f):
                if len(G) >= 30:
                    t5[sd][f + "=" + str(k)] = sim(G)
        for (k1, k2), G in GS.groupby(["liq_b", "band"]):
            if len(G) >= 30:
                t5[sd]["liq_b=" + str(k1) + " & band=" + str(k2)] = sim(G)
    out["target1000"] = t5
    return out



def competition_stats(R, now):
    """2026-10(사용자: "틈새시장의 큰 틀 - 실제로 낙찰 가능성이 있고 낙찰 후 매도까지 잘되는 지역"): 시군구별 경쟁 강도.
    최근 3년(2023~) 낙찰사례로 ① 1등 낙찰가 ÷ 입찰 당시 시세(같은 단지·평형 실거래 기반 추정) 중간값 - 낮을수록 경쟁 약함
    ② 응찰자 수 중간값 ③ 되판 비율·보유 기간(동까지 확인된 매칭, 낙찰 후 12개월 넘은 사례만) ④ 계절별(전체).
    2024~2025 앱 백테스트에서 겨울(12~2월) 1등가÷예상매도가 0.88~0.90·앱 낙찰률 약 2배, 전남 중소도시(광양·여수·목포) 0.87~0.88로 확인됨."""
    D = R[(R["sale"] >= 20230101) & R["est"].notna() & (R["est"] > 0)].copy()
    D["comp"] = D["actual"] / D["est"]
    D = D[(D["comp"] > 0.4) & (D["comp"] < 1.6)]
    cut12 = int((datetime.now() - timedelta(days=365)).strftime("%Y%m%d"))
    def stat(G):
        old = G[(G["sale"] <= cut12) & G["adong"].notna()]
        sold = old[old["resale_conf"] == "dong"] if "resale_conf" in old.columns else old.iloc[0:0]
        return {"n": int(len(G)), "compMed": round(float(G["comp"].median()), 3),
                "biddersMed": (float(G["bidders"].median()) if G["bidders"].notna().any() else None),
                "soldN": int(len(old)), "soldPct": (round(len(sold) / len(old) * 100) if len(old) >= 10 else None),
                "holdMed": (round(float(sold["resale_m"].median()), 1) if len(sold) >= 5 else None)}
    out = {"generatedAt": now, "base": stat(D), "bySido": {}, "byRegion": {}, "bySeason": {}}
    for sd, G in D.groupby("sido"):
        if len(G) >= 30:
            out["bySido"][sd] = stat(G)
    for rg, G in D.groupby("region"):
        if len(G) >= 15:
            out["byRegion"][rg] = stat(G)
    D["season"] = ((D["sale"] // 100) % 100).map(lambda m: "겨울" if m in (12, 1, 2) else ("봄" if m <= 5 else ("여름" if m <= 8 else "가을")))
    for se, G in D.groupby("season"):
        out["bySeason"][se] = stat(G)
    print(f"  지역 경쟁 강도: 시군구 {len(out['byRegion'])}곳, 기준 {out['base']}")
    cyc.upsert_rows([{"id": "signal|__competition__", "payload": cyc.clean_json(out), "fetched_at": now}])


if __name__ == "__main__":
    main()
