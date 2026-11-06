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
import time
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
    load_flow_coef()
    cases = requests.get(f"{SITE_URL}/api/auction?kind=bidCases", timeout=120).json()
    df = pd.DataFrame(cases)
    print(f"  낙찰사례 {len(df):,}건")
    df = df[df["propertyType"].astype(str).str.contains("아파트", na=False)]
    df = df[pd.to_numeric(df["finalBidPrice"], errors="coerce") > 0]
    # 2026-11-03 낙찰/입찰예정 구분: 상태가 '매각'이고(상태 칸이 있을 때) 입찰일이 오늘(한국) 이전인 낙찰만 분석에 씀 - 입찰예정·결과 미확인 사건이 섞이지 않게
    _today = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")
    if "status" in df.columns:
        df = df[df["status"].isna() | (df["status"].astype(str) == "매각")]
    df = df[df["saleDate"].astype(str) <= _today]
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
    tr = avm.fetch_all_rows("house_trades", cols="region,dong,danji,bunji,price,size,floor,deal_date,dealing_type,build_year,apt_dong,cdeal_type,road_name,main_num,sub_num",
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
    # 2026-10-11 같은 단지 거래가 0~2건일 때를 위한 같은 동 시세(변형 시험): 동별 거래 배열
    dgroups = {k: (g["deal_date"].to_numpy(), g["size"].to_numpy(dtype=float), g["ppm"].to_numpy(dtype=float), pd.to_numeric(g["build_year"], errors="coerce").to_numpy(dtype=float)) for k, g in tr.sort_values("deal_date").groupby(["region_n", "dk"])}
    # 🌊 시군구 전체 거래 배열(흐름용): 법정동 배열을 시군구별로 합쳐 날짜순 정렬
    _rg_parts = {}
    for (rg_, dk_), (dd_, sz_, pp_, yb_) in dgroups.items():
        _rg_parts.setdefault(rg_, []).append((dd_, pp_))
    rgroups = {}
    for rg_, parts in _rg_parts.items():
        _d = np.concatenate([x[0] for x in parts]); _p = np.concatenate([x[1] for x in parts]); _o = np.argsort(_d, kind="stable"); rgroups[rg_] = (_d[_o], _p[_o])
    # 🏘 생활반경·세대수 흐름용 단지 인덱스(2026-11-04, 사용자: 한 단지만으로는 아쉽고 거래량에 세대수를 넣어야 신빙성 - 반경 안 단지들의 거래·세대수로 흐름을 봄)
    # 단지 키(complex_coords의 cache_key와 같은 규칙) → 좌표, (법정동코드·본번·부번) → 세대수(건축물대장). 실패하면 이 요인만 건너뛰고 나머지는 그대로
    CX = None
    try:
        from sklearn.neighbors import BallTree
        def _ck(r_):
            mn = r_.get("main_num"); sn = r_.get("sub_num")
            mn = 0 if mn is None or (isinstance(mn, float) and np.isnan(mn)) else int(float(mn))
            sn = "" if sn is None or (isinstance(sn, float) and np.isnan(sn)) or str(sn).strip() in ("", "0", "0.0") else str(int(float(sn)))
            return "|".join(str(x) for x in [r_.get("dong") or "", r_.get("danji") or "", r_.get("bunji") or "", r_.get("road_name") or "", mn, sn]).lower()
        _tk = tr[["dong", "danji", "bunji", "road_name", "main_num", "sub_num"]].drop_duplicates()
        _tk["ckey"] = [_ck(r_) for r_ in _tk.to_dict("records")]
        tr = tr.merge(_tk[["dong", "danji", "bunji", "road_name", "main_num", "sub_num", "ckey"]], on=["dong", "danji", "bunji", "road_name", "main_num", "sub_num"], how="left")
        cc = avm.fetch_all_rows("complex_coords", cols="cache_key,lat,lon,sigungu_cd,bjdong_cd", order_col="id", extra_filter="&lat=not.is.null")
        cc["ck"] = cc["cache_key"].astype(str).str.lower(); cc = cc.drop_duplicates("ck").set_index("ck")
        keys_ = tr["ckey"].dropna().unique(); cc_hit = cc.reindex(keys_); ok_ = cc_hit["lat"].notna().values
        print(f"  🏘 단지 좌표 연결: 단지 {len(keys_):,}곳 중 {int(ok_.sum()):,}곳({ok_.mean() * 100:.1f}%)")
        HH = {}
        try:
            bi = avm.fetch_all_rows("building_info", cols="sigungu_cd,bjdong_cd,bun,ji,hh:title_json->>hhldCnt,hs:title_json->>hhldSum", order_col="id")
            for r_ in bi.itertuples():
                try:
                    h_ = int(float(r_.hh)) if r_.hh not in (None, "", "nan") and float(r_.hh) > 0 else (int(float(r_.hs)) if r_.hs not in (None, "", "nan") else 0)
                except Exception:
                    h_ = 0
                if h_ > 0: HH[(str(r_.sigungu_cd), str(r_.bjdong_cd), str(r_.bun).zfill(4), str(r_.ji).zfill(4))] = h_
            print(f"  🏘 건축물대장 세대수 {len(HH):,}건")
        except Exception as e_:
            print("  🏘 세대수 불러오기 건너뜀:", e_)
        cx_keys, cx_lat, cx_lon, cx_dd, cx_pp, cx_hh = [], [], [], [], [], []
        _trs = tr.sort_values("deal_date")
        for ck_, g_ in _trs.groupby("ckey"):
            row_ = cc_hit.loc[ck_] if ck_ in cc_hit.index else None
            if row_ is None or not np.isfinite(row_["lat"]): continue
            parts_ = ck_.split("|")[2].replace("산", "").split("-")
            try: bun_ = parts_[0].zfill(4); ji_ = (parts_[1] if len(parts_) > 1 else "0").zfill(4)
            except Exception: bun_, ji_ = "", ""
            hh_ = HH.get((str(row_["sigungu_cd"]), str(row_["bjdong_cd"]), bun_, ji_), 0)
            cx_keys.append(ck_); cx_lat.append(float(row_["lat"])); cx_lon.append(float(row_["lon"]))
            cx_dd.append(g_["deal_date"].to_numpy()); cx_pp.append(g_["ppm"].to_numpy(dtype=float)); cx_hh.append(hh_)
        cx_xy = np.radians(np.c_[cx_lat, cx_lon]); CX = {"tree": BallTree(cx_xy, metric="haversine"), "dd": cx_dd, "pp": cx_pp, "hh": np.array(cx_hh), "ck": {k_: i_ for i_, k_ in enumerate(cx_keys)}, "n": len(cx_keys)}
        print(f"  🏘 생활반경용 단지 {CX['n']:,}곳(세대수 아는 곳 {int((CX['hh'] > 0).sum()):,})")
    except Exception as e_:
        print("  🏘 생활반경 요인 건너뜀:", e_); CX = None

    def radius_flow(lat_, lon_, cut_ymd, km, ck_self=None):
        """반경 km 안 모든 단지(자기 단지 포함)의 거래를 모아 가격(㎡당)·거래량 흐름과 회전율(최근 3개월 거래 ÷ 세대수×100, 세대수 아는 단지만) 계산. 표본 모자라면 None"""
        if CX is None or lat_ is None or lon_ is None or not (np.isfinite(lat_) and np.isfinite(lon_)): return None
        idx_ = CX["tree"].query_radius(np.radians([[lat_, lon_]]), r=km / 6371.0)[0]
        if len(idx_) == 0: return None
        ref = int_to_date(int(cut_ymd)); lo1, lo2, lo3 = ymd_int(ref - timedelta(days=90)), ymd_int(ref - timedelta(days=180)), ymd_int(ref - timedelta(days=360))
        Rp, Pp, nR, nB, nRh, Hs = [], [], 0, 0, 0, 0
        for i_ in idx_:
            dd_, pp_ = CX["dd"][i_], CX["pp"][i_]
            a0, a1, a2, a3 = np.searchsorted(dd_, lo3), np.searchsorted(dd_, lo2), np.searchsorted(dd_, lo1), np.searchsorted(dd_, int(cut_ymd))
            r_n = a3 - a2; nR += r_n; nB += a2 - a0
            if r_n: Rp.append(pp_[a2:a3])
            if a2 - a1: Pp.append(pp_[a1:a2])
            if CX["hh"][i_] > 0: nRh += r_n; Hs += int(CX["hh"][i_])
        out = {"n_cx": int(len(idx_)), "p": None, "v": None, "t": None}
        if Rp and Pp:
            R_ = np.concatenate(Rp); P_ = np.concatenate(Pp)
            if len(R_) >= 20 and len(P_) >= 20: out["p"] = float(np.log(np.median(R_) / np.median(P_)))
        if nB >= 60: out["v"] = float(np.log((nR + 1) / (nB / 3.0 + 1)))
        if Hs >= 1000: out["t"] = nRh / Hs * 100.0
        return out
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
               "caseNo": str(getattr(c, "caseNo", "") or ""), "bname": str(getattr(c, "buildingName", "") or ""),
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
            est = None; own = 0; rec_est = {}
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
                    # 2026-10-11 예상매도가 변형 시험(사용자: "오차를 더 줄일 방법") - 같은 거래 묶음으로 계산 방식만 바꿔 est_* 열로 저장(앱 계산엔 영향 없음)
                    try:
                        ages = np.array([(sale_d - int_to_date(int(x))).days - 30 for x in use["deal_date"].values], dtype=float)
                        raw = use["ppm"].values.astype(float) * adj
                        base0 = idx_at(c.region, cut_ym)
                        fi = np.array([max(0.7, min(1.4, base0 / idx_at(c.region, int(y)))) if base0 and idx_at(c.region, int(y)) else 1.0 for y in use["ym"].values])
                        def wq(v, w, q):
                            o = np.argsort(v); v2 = v[o]; w2 = w[o]; cs = np.cumsum(w2) / w2.sum(); return float(v2[min(np.searchsorted(cs, q), len(v2) - 1)])
                        w90 = 0.5 ** (np.maximum(ages, 0) / 90.0); w180 = 0.5 ** (np.maximum(ages, 0) / 180.0)
                        rec_est = {"est_q60": float(np.quantile(np.array(vals), 0.6)) * c.area, "est_q50": float(np.quantile(raw if days == 1095 and False else np.array(vals), 0.5)) * c.area,
                                   "est_w90_q50": wq(np.array(vals), w90, 0.5) * c.area, "est_w90_q40": wq(np.array(vals), w90, 0.4) * c.area, "est_w180_q40": wq(np.array(vals), w180, 0.4) * c.area,
                                   "est_idx_q40": float(np.quantile(raw * fi, 0.4)) * c.area, "est_idx_w180_q50": wq(raw * fi, w180, 0.5) * c.area, "est_idx_w90_q50": wq(raw * fi, w90, 0.5) * c.area}
                        o3 = np.argsort(ages)[:3]
                        rec_est["est_last3"] = float(np.median(raw[o3] * fi[o3])) * c.area if len(use) >= 3 else est
                        rec_est["est_n"] = len(use); rec_est["est_days"] = days
                    except Exception:
                        rec_est = {}
                    break
            rec["est"] = est; rec["own"] = own
            try:
                rec["est_rule"] = est_rule_asof(g, c, sale_d, cut, cut_ym, idx_at)
            except Exception:
                rec["est_rule"] = None
            try:  # 📈 흐름 반영 시세(est_rule_f): 같은 규칙 + 오래된 거래를 지역 가격 흐름만큼 지금 시점으로(수도권 법정동→시군구, 지방 같은 단지→시군구, 불확실하면 보정 안 함)
                _sido_e = str(c.region).split(" ")[0]; _cls_e = "수도권" if _sido_e[:2] in ("서울", "경기", "인천") else "지방"
                _dgE = dgroups.get((c.region, c.dk)); _rgE = rgroups.get(c.region)
                _dres = adaptive_flow(_dgE[0], _dgE[2], cut, 20, 365) if _dgE else None
                _sres = adaptive_flow(_rgE[0], _rgE[1], cut, 40, 365) if _rgE else None
                _gE = g.sort_values("deal_date"); _gE = _gE[(_gE["size"] - c.area).abs() <= 10]
                _cres = adaptive_flow(_gE["deal_date"].to_numpy(), _gE["ppm"].to_numpy(dtype=float), cut, 5, 730)
                _fl = pick_flow(_cls_e, _dres, _sres, _cres)
                rec["est_rule_f"] = est_rule_asof(g, c, sale_d, cut, cut_ym, idx_at, flow=_fl)
                rec["est_flow_rate"] = _fl["rate"] if _fl else None
            except Exception:
                rec["est_rule_f"] = None
            # 2026-10-11 환금성: 입찰 30일 전 기준 같은 단지·같은 평형(±3㎡) 최근 1년 중개거래 수 - 앱의 "최근 1년 같은 평형 거래"와 같은 정의
            # 낙찰 뒤 6개월 안 같은 단지·같은 평형(±3㎡) 시장 실거래 중위값(되팔기와 무관한 시장 가격) - 지방 성적표에서 예상매도가와 비교
            _aft = g[(g["deal_date"] >= ymd_int(sale_d)) & (g["deal_date"] < ymd_int(sale_d + timedelta(days=183))) & ((g["size"] - c.area).abs() <= 3)]
            # 시세 근거가 얇을 때의 편향 진단용 특징(입찰 30일 전 시점, 미래 정보 없음): 같은 평형 36개월 거래 수·가장 최근 거래 나이(개월)·최근 가격 흩어짐·다른 평형 12개월 거래 수
            _s36 = g[(g["deal_date"] >= ymd_int(sale_d - timedelta(days=30 + 1095))) & (g["deal_date"] < cut) & ((g["size"] - c.area).abs() <= 3)]
            rec["t_n36"] = int(len(_s36))
            if len(_s36):
                _ls = _s36.sort_values("deal_date")
                rec["t_last_age"] = float((int_to_date(cut) - int_to_date(int(_ls["deal_date"].iloc[-1]))).days / 30.4); rec["t_last_price"] = float(_ls["price"].iloc[-1])
                rec["t_disp"] = float(np.std(np.log(_ls["price"].values[-5:].astype(float)))) if len(_ls) >= 2 else None
            rec["t_n_other12"] = int(((g["deal_date"] >= ymd_int(sale_d - timedelta(days=30 + 365))) & (g["deal_date"] < cut) & ((g["size"] - c.area).abs() > 3)).sum())
            rec["mkt_after_n"] = int(len(_aft)); rec["mkt_after"] = float(_aft["price"].median()) if len(_aft) else None
            rec["n6"] = int(((g["deal_date"] >= ymd_int(sale_d - timedelta(days=30 + 183))) & (g["deal_date"] < cut) & ((g["size"] - c.area).abs() <= 3)).sum())
            rec["n12"] = int(((g["deal_date"] >= ymd_int(sale_d - timedelta(days=30 + 365))) & (g["deal_date"] < cut) & ((g["size"] - c.area).abs() <= 3)).sum())
            if rec["n6"] <= 2 and str(c.region).split(" ")[0][:2] not in ("서울", "경기", "인천"):   # 2026-11-06 얇은 근거 시세 후보(시험용): 앱·모델 계산엔 영향 없음
                try:
                    rec.update(thin_variants(g, c, cut, cut_ym, idx_at, dgroups.get((c.region, c.dk)), rgroups.get(c.region)))
                except Exception:
                    pass
            rec.update(rec_est)
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
                        try:
                            b_cut, b_res = idx_at(c.region, cut_ym), idx_at(c.region, int(t0["deal_date"]) // 100)
                            rec["mkt"] = float(b_res / b_cut) if b_cut and b_res else None  # 입찰 30일 전 → 되판 달 사이 시군구 ㎡당 가격 지수 변화
                        except Exception:
                            rec["mkt"] = None
            nm = avm.normalize_complex_name(g["danji"].mode().iloc[0]) if len(g) else None
            rec["tier"] = pop.get((c.region, c.dk, nm))
            rec["cx"] = nm
            band = "소형" if c.area < 60 else ("중형" if c.area <= 85 else "대형")
            rec["bandTier"] = pop.get((c.region, c.dk, nm, band))
            # 단지 전체 최근 3년 거래(입찰 전 기준) - 거래 활발도
            rec["cx3y"] = int(((g["deal_date"] < cut) & (g["deal_date"] >= ymd_int(sale_d - timedelta(days=30 + 1095)))).sum())
            try:  # 2026-10-24 최근 거래 점프: 입찰 30일 전 기준 같은 평형 최근 90일 가장 최근 중개거래 ÷ 시세(est) - 최근 거래가 시세보다 높으면 낙찰가도 오르는지(낙찰가 모델 요인 jb)
                _h90 = hist[hist["deal_date"] >= ymd_int(sale_d - timedelta(days=30 + 90))]
                if len(_h90) and est:
                    _l = _h90.sort_values("deal_date").iloc[-1]; rec["jb"] = float(np.log(float(_l["ppm"]) * c.area / est))
            except Exception:
                pass
            rec["cx12"] = int(((g["deal_date"] < cut) & (g["deal_date"] >= ymd_int(sale_d - timedelta(days=30 + 365)))).sum())  # 2026-10-24 단지 전체 평형 최근 1년 거래 수(몰림 예측 요인 - 앱의 ownStats.v6+vPrev6와 같은 정의)
            by = pd.to_numeric(g["build_year"], errors="coerce").dropna()
            if len(by):
                rec["age"] = int(sale_d.year - int(by.mode().iloc[0]))
        try:
            if rec.get("own", 0) <= 2:
                dg = dgroups.get((c.region, c.dk))
                if dg is not None:
                    dd_, sz_, pp_, yb_ = dg; sd_ = int_to_date(c.sale_int); cut_ = ymd_int(sd_ - timedelta(days=30)); lo_ = ymd_int(sd_ - timedelta(days=30 + 365))
                    i0, i1 = np.searchsorted(dd_, lo_), np.searchsorted(dd_, cut_)
                    m_ = np.abs(sz_[i0:i1] - c.area) <= 8
                    by_ = (sd_.year - rec["age"]) if rec.get("age") is not None else None
                    mb_ = m_ & (np.isnan(yb_[i0:i1]) | (np.abs(yb_[i0:i1] - by_) <= 5)) if by_ else m_
                    for tag, mm_ in (("", m_), ("_by", mb_)):
                        v_ = pp_[i0:i1][mm_]
                        if len(v_) >= 3:
                            rec["est_dong" + tag] = float(np.quantile(v_, 0.4)) * c.area; rec["n_dong" + tag] = int(len(v_))
                    for tag in ("", "_by"):
                        ed = rec.get("est_dong" + tag)
                        if ed:
                            rec["est_blend" + tag] = ed if not rec.get("est") else 0.5 * rec["est"] + 0.5 * ed
                            rec["est_blend70" + tag] = ed if not rec.get("est") else 0.7 * rec["est"] + 0.3 * ed
        except Exception:
            pass
        try:  # 🌊 시세 흐름(입찰 30일 전 기준): 시군구·법정동(수도권용)·같은 크기대 단지(지방용). 표본이 모자라면 None
            _sd2 = int_to_date(c.sale_int); _cut2 = ymd_int(_sd2 - timedelta(days=30)); _sido = str(c.region).split(" ")[0]
            rec["flow_cls"] = "수도권" if _sido[:2] in ("서울", "경기", "인천") else "지방"
            _rg = rgroups.get(c.region); _dg = dgroups.get((c.region, c.dk))
            rec["flow_sgg"], rec["flow_sgg_v"] = flow_pv(_rg[0], _rg[1], _rg[0], _cut2, 30, 90) if _rg else (None, None)
            rec["flow_dong"], rec["flow_dong_v"] = flow_pv(_dg[0], _dg[2], _dg[0], _cut2, 10, 30) if _dg else (None, None)
            if g is not None and len(g):
                _ga = g.sort_values("deal_date"); _gs = _ga[(_ga["size"] - c.area).abs() <= 10]
                rec["flow_cx"], rec["flow_cx_v"] = flow_pv(_gs["deal_date"].to_numpy(), _gs["ppm"].to_numpy(dtype=float), _ga["deal_date"].to_numpy(), _cut2, 3, 6)
            else:
                rec["flow_cx"], rec["flow_cx_v"] = None, None
            if CX is not None:  # 🏘 생활반경 1·2·3km 흐름(가격·거래량·회전율)과 같은 단지(150m) 회전율
                _la, _lo = getattr(c, "lat", None), getattr(c, "lon", None)
                for _km in (1, 2, 3):
                    _rf = radius_flow(_la, _lo, _cut2, _km)
                    rec[f"flowR{_km}_p"], rec[f"flowR{_km}_v"], rec[f"flowR{_km}_t"] = (_rf["p"], _rf["v"], _rf["t"]) if _rf else (None, None, None)
                _r0 = radius_flow(_la, _lo, _cut2, 0.15); rec["flow_cx_t"] = _r0["t"] if _r0 else None
                try:  # 적응형 흐름: 단지(같은 크기대)·반경 1/2/3km·법정동·시군구, 회전율(세대수)
                    def _gather(km, hh_only, mx):
                        if _la is None or _lo is None or not (np.isfinite(_la) and np.isfinite(_lo)): return None, 0
                        ix = CX["tree"].query_radius(np.radians([[_la, _lo]]), r=km / 6371.0)[0]
                        lo_ = ymd_int(int_to_date(int(_cut2)) - timedelta(days=mx)); D_, P_, H_ = [], [], 0
                        for j_ in ix:
                            if hh_only and CX["hh"][j_] <= 0: continue
                            dd_ = CX["dd"][j_]; a0 = int(np.searchsorted(dd_, lo_)); a1 = int(np.searchsorted(dd_, int(_cut2)))
                            if a1 > a0: D_.append(dd_[a0:a1]); P_.append(CX["pp"][j_][a0:a1])
                            H_ += int(max(CX["hh"][j_], 0)) if hh_only else 0
                        if not D_: return None, H_
                        dd2 = np.concatenate(D_); pp2 = np.concatenate(P_); o_ = np.argsort(dd2, kind="stable"); return (dd2[o_], pp2[o_]), H_
                    for _nm, _km, _K in (("R1", 1.0, 12), ("R2", 2.0, 16), ("R3", 3.0, 20)):
                        _gd, _ = _gather(_km, False, 365)
                        _af = adaptive_flow(_gd[0], _gd[1], _cut2, _K, 365) if _gd else None
                        rec[f"af{_nm}_rate"], rec[f"af{_nm}_z"], rec[f"af{_nm}_vol"] = (_af["rate"], _af["z"], _af["vol"]) if _af else (None, None, None)
                    _gd, _H = _gather(2.0, True, 365)   # 회전율: 세대수 아는 단지만(거래도 그 단지만)
                    _af = adaptive_flow(_gd[0], _gd[1], _cut2, 16, 365) if (_gd and _H >= 500) else None
                    rec["afR2_t"] = (_af["dens"] * 91.0 / _H * 100.0) if _af else None
                    _gd, _H = _gather(0.15, True, 730)
                    _af = adaptive_flow(_gd[0], _gd[1], _cut2, 6, 730) if (_gd and _H >= 100) else None
                    rec["afC_t"] = (_af["dens"] * 91.0 / _H * 100.0) if _af else None
                except Exception:
                    pass
            if g is not None and len(g):
                _ga2 = g.sort_values("deal_date"); _gb = _ga2[(_ga2["size"] - c.area).abs() <= 10]
                _af = adaptive_flow(_gb["deal_date"].to_numpy(), _gb["ppm"].to_numpy(dtype=float), _cut2, 5, 730)
                rec["afC_rate"], rec["afC_z"], rec["afC_vol"] = (_af["rate"], _af["z"], _af["vol"]) if _af else (None, None, None)
            _af = adaptive_flow(_dg[0], _dg[2], _cut2, 20, 365) if _dg else None
            rec["afD_rate"], rec["afD_z"], rec["afD_vol"] = (_af["rate"], _af["z"], _af["vol"]) if _af else (None, None, None)
            _af = adaptive_flow(_rg[0], _rg[1], _cut2, 40, 365) if _rg else None
            rec["afS_rate"], rec["afS_z"], rec["afS_vol"] = (_af["rate"], _af["z"], _af["vol"]) if _af else (None, None, None)
        except Exception:
            pass
        out.append(rec)
    R = pd.DataFrame(out)
    try:  # 🌊 적응형 흐름 상태(수도권·지방 따로 눈금: 그룹 안 분위수로 구간을 나눔 - 같은 고정 경계를 두 그룹에 쓰지 않음)
        def _cls_q(col, cls_col, qs):
            res_ = {}
            for cl_ in ("수도권", "지방"):
                v_ = pd.to_numeric(R.loc[R[cls_col] == cl_, col], errors="coerce").dropna()
                res_[cl_] = [float(v_.quantile(q_)) for q_ in qs] if len(v_) >= 30 else None
            return res_
        def _st_price(lvl):
            rt, zz = pd.to_numeric(R.get(f"af{lvl}_rate"), errors="coerce"), pd.to_numeric(R.get(f"af{lvl}_z"), errors="coerce")
            strong = {}
            for cl_ in ("수도권", "지방"):
                m_ = (R["flow_cls"] == cl_) & (zz.abs() >= 1.0); strong[cl_] = float(rt[m_].abs().median()) if m_.sum() >= 30 else None
            out_ = []
            for a_, z_, c_ in zip(rt, zz, R["flow_cls"]):
                if not np.isfinite(a_) or not np.isfinite(z_): out_.append("-")
                elif abs(z_) < 1.0: out_.append("u")
                else:
                    t_ = strong.get(c_) or 0.0; out_.append(("up2" if abs(a_) >= t_ else "up1") if a_ > 0 else ("dn2" if abs(a_) >= t_ else "dn1"))
            return out_
        def _st_terc(col):
            q_ = _cls_q(col, "flow_cls", (1 / 3, 2 / 3)); vv = pd.to_numeric(R.get(col), errors="coerce"); o_ = []
            for v_, c_ in zip(vv, R["flow_cls"]):
                if not np.isfinite(v_) or q_.get(c_) is None: o_.append("-")
                else: o_.append("lo" if v_ <= q_[c_][0] else ("hi" if v_ >= q_[c_][1] else "mid"))
            return o_
        _lv = [l_ for l_ in ("C", "R1", "R2", "R3", "D", "S") if f"af{l_}_rate" in R.columns]
        for l_ in _lv:
            pr_, vo_ = _st_price(l_), _st_terc(f"af{l_}_vol")
            R[f"af{l_}_s"] = [f"{c_}|{a_}|{b_}" for c_, a_, b_ in zip(R["flow_cls"], pr_, vo_)]
        if "afR2_t" in R.columns and "R2" in _lv:
            R["afT2_s"] = [f"{c_}|T{t_}|{p_}" for c_, t_, p_ in zip(R["flow_cls"], _st_terc("afR2_t"), _st_price("R2"))]
        if "afC_t" in R.columns and "C" in _lv:
            R["afTC_s"] = [f"{c_}|T{t_}|{v_}" for c_, t_, v_ in zip(R["flow_cls"], _st_terc("afC_t"), _st_terc("afC_vol"))]
        print("  🌊 적응형 흐름 상태 계산:", {l_: round(float((R[f"af{l_}_s"].str.split("|").str[1] != "-").mean()) * 100, 1) for l_ in _lv})
    except Exception as e_:
        print("  적응형 흐름 상태 건너뜀:", e_)
    R["ratio"] = R["actual"] / R["est"]
    R["err"] = (R["est"] - R["resale"]) / R["resale"]
    R["second_gap"] = (R["actual"] - R["second"]) / R["est"]
    R["loss"] = R["resale"] < R["actual"] * COST_RATIO + FIXED_COST
    # 2026-10: 낙찰가 예측 검증용 - 사례별 표를 파일로 남김(Actions 아티팩트로 내려받아 분석)
    try:
        R.drop(columns=["notes"], errors="ignore").to_csv("bidcases-R.csv.gz", index=False, compression="gzip")
    except Exception as e:
        print("  사례표 저장 실패(건너뜀):", e)
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
        try:
            winbid_model(R, now)
            try:
                crowd_analysis(R, now)
                crowd_item_model(R, now)
            except Exception as e:
                print('  몰림 분석 건너뜀:', e)
            try: liquidity_curve(R, now)
            except Exception as e: print('  환금성 곡선 실패(건너뜀):', e)
        except Exception as e:
            print('  예상 낙찰가 모델 실패(건너뜀):', e)
        try:
            weekly_report(R, datetime.now(), now)
        except Exception as e:
            print('  주간 리포트 실패(건너뜀):', e)
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



CROWD_FACTORS = [("lb", 10), ("fails", 120), ("tier", 5), ("floor", 5), ("size", 30), ("own", 120), ("minb", 30), ("ageb", 60), ("cxb", 30), ("lbcx", 60), ("lbo", 60)]
CROWD_RC_FACTORS = [("rc", 120), ("rclb", 60)]  # 큰 지역(서울·경기·인천·지방) 요인 - 시군구·법정동 평균이 아니라 3개 권역(2026-10-24 검증 후 쓸지 결정)
CROWD_LAB_EDGES = [-0.2, -0.1, 0, 0.1, 0.2, 0.35]


def crowd_bucket(minb, age, cx):
    """앱(index.html crowdFor)과 같은 구간 정의 - 바꾸면 양쪽을 같이 바꿔야 함"""
    mb = "<0.5억" if minb < 5000 else ("0.5-1억" if minb < 10000 else ("1-1.5억" if minb < 15000 else ("1.5-2억" if minb < 20000 else ("2-3억" if minb < 30000 else ("3-4억" if minb < 40000 else "4억+")))))
    ab = "?" if age is None or not np.isfinite(age) else ("0-5" if age <= 5 else ("6-10" if age <= 10 else ("11-15" if age <= 15 else ("16-20" if age <= 20 else ("21-25" if age <= 25 else ("26-30" if age <= 30 else "31+"))))))
    cb = "?" if cx is None or not np.isfinite(cx) else ("0-9" if cx < 10 else ("10-24" if cx < 25 else ("25-49" if cx < 50 else ("50-99" if cx < 100 else ("100-199" if cx < 200 else "200+")))))
    return mb, ab, cb


def crowd_features(D, use_region=False):
    """물건 자신의 정보만 사용(지역·법정동 평균 요인은 쓰지 않음 - 사용자: 전국/법정동 기준이 아니라 물건별 예상 응찰자 수)"""
    X = pd.DataFrame(index=D.index)
    lm = np.log(D["minbid"].astype(float) / D["est"].astype(float))
    X["lb"] = np.clip(np.floor(lm / 0.05), -24, 9).astype(int).astype(str)
    X["fails"] = D["fails"].map(lambda v: "?" if v is None or pd.isna(v) else str(min(int(v), 3)))
    X["tier"] = D["tier"].fillna("없음").astype(str)
    X["floor"] = D["floor"].map(lambda f: "?" if f is None or pd.isna(f) else ("1층" if f == 1 else ("2~3층" if f <= 3 else "4층+")))
    X["size"] = D["area"].map(lambda a: "소형" if a < 60 else ("중형" if a <= 85 else "대형"))
    X["own"] = D["own"].map(lambda n: "1~2" if n <= 2 else ("3~5" if n <= 5 else ("6~10" if n <= 10 else "11+")))
    bk = [crowd_bucket(m, a, c) for m, a, c in zip(D["minbid"].astype(float), D["age"].astype(float), D["cx12"].astype(float))]
    X["minb"] = [b[0] for b in bk]; X["ageb"] = [b[1] for b in bk]; X["cxb"] = [b[2] for b in bk]
    lbc = lm.map(lambda v: "L" if v <= -0.25 else ("M" if v <= -0.10 else "H"))
    X["lbcx"] = lbc.values + "|" + X["cxb"].values; X["lbo"] = lbc.values + "|" + X["own"].values
    X["dong"] = D["region"].fillna("?").astype(str).values + "|" + D["dk"].fillna("").astype(str).values  # 법정동(시군구|동) - 사용자: 지방도 인기 동네 쏠림이 두드러짐
    X["regionf"] = D["region"].fillna("?").astype(str).values
    rc = D["region"].map(lambda r: "서울" if str(r).startswith("서울") else ("경기·인천" if str(r)[:2] in ("경기", "인천") else "지방"))
    X["rc"] = rc.values; X["rclb"] = rc.values + "|" + lbc.values
    if use_region:
        X["region"] = D["region"].fillna("?").astype(str)
    return X


def crowd_fit(X, y, factors, iters=6):
    base = float(np.median(y)); eff = {f: {} for f, _ in factors}; pred = np.full(len(y), base)
    for _ in range(iters):
        for f, k in factors:
            cur = X[f].map(eff[f]).fillna(0).values
            r = y - (pred - cur)
            g = pd.DataFrame({"k": X[f].values, "r": r}).groupby("k")["r"].agg(["median", "count"])
            new = (g["median"] * g["count"] / (g["count"] + k)).to_dict()
            eff[f] = new; pred = pred - cur + X[f].map(new).fillna(0).values
    return {"base": base, "eff": eff}


def crowd_predict(m, X, factors):
    p = np.full(len(X), m["base"])
    for f, _ in factors:
        p = p + X[f].map(m["eff"][f]).fillna(0).values
    return p


def crowd_item_model(R, now):
    """2026-10-24(사용자: 입찰자 몰릴 물건 필터 + 물건별 예상 응찰자 수, 앱 로딩시간 변화 없이) - 앱에서 바로 계산 가능한 덧셈형 모델(로그 응찰자 수).
    지역·법정동 요인 없이 물건 자신의 조건(최저가÷시세·유찰·인기 등급·층·평형·시세 근거 거래 수·감정가 비율·최저가 금액·준공 연차·단지 거래량)만 사용.
    예측값을 학습에 안 쓴 최근 12개월에서 실제 응찰자 수(중앙·몰림 확률)로 보정한 표를 함께 저장 → 앱이 '예상 응찰 약 N명 · 8명 이상일 확률 P%'를 보여줌."""
    from sklearn.metrics import roc_auc_score
    D = R[R["bidders"].notna() & (R["bidders"] > 0) & R["est"].notna() & (R["est"] > 0) & R["minbid"].notna() & (R["minbid"] > 0) & R["cx12"].notna() & R["area"].notna() & (R["sale"] >= 20230101)].copy()
    D = D[D["own"].notna()]
    if len(D) < 3000:
        print("  물건별 응찰자 모델: 사례 부족"); return
    X = crowd_features(D); Xr = crowd_features(D, use_region=True)
    y = np.log(D["bidders"].astype(float)).values; crowd = (D["bidders"] >= 8).astype(int).values
    last = pd.to_datetime(str(int(D["sale"].max())), format="%Y%m%d"); cut = int((last - pd.DateOffset(months=12)).strftime("%Y%m%d"))
    tr = (D["sale"] < cut).values; te = ~tr
    FACT0 = list(CROWD_FACTORS)
    VAR = {"물건 조건만": FACT0, "+권역": FACT0 + CROWD_RC_FACTORS, "+법정동": FACT0 + [("dong", 40)], "+시군구+법정동": FACT0 + [("regionf", 120), ("dong", 40)], "+권역+시군구+법정동": FACT0 + CROWD_RC_FACTORS + [("regionf", 120), ("dong", 40)]}
    rc_te = X.loc[te, "rc"].values
    def bias_by_class(pp):
        bn_ = np.exp(pp); ed = np.quantile(bn_, np.linspace(0, 1, 13)); pr = np.zeros(len(bn_)); Bt = D["bidders"].values[te].astype(float)
        for i2 in range(12):
            mk = (bn_ >= ed[i2]) & (bn_ <= ed[i2 + 1]) if i2 == 11 else (bn_ >= ed[i2]) & (bn_ < ed[i2 + 1])
            if mk.sum(): pr[mk] = (Bt[mk] >= 8).mean()
        out = {}
        for c in ("서울", "경기·인천", "지방"):
            mk = rc_te == c
            if mk.sum() >= 100: out[c] = {"n": int(mk.sum()), "예측 몰림%": round(float(pr[mk].mean() * 100), 1), "실제 몰림%": round(float((Bt[mk] >= 8).mean() * 100), 1)}
        return out
    res_v = {}; preds = {}
    for nm, fct in VAR.items():
        mm = crowd_fit(X[tr], y[tr], fct); pp = crowd_predict(mm, X[te], fct); preds[nm] = (mm, pp, fct)
        auc_all = float(roc_auc_score(crowd[te], pp)); aucs = {}
        for c in ("서울", "경기·인천", "지방"):
            mk = rc_te == c
            if mk.sum() >= 200 and 0 < crowd[te][mk].mean() < 1: aucs[c] = round(float(roc_auc_score(crowd[te][mk], pp[mk])), 3)
        mae_b = float(np.median(np.abs(np.exp(pp) - D["bidders"].values[te].astype(float))))
        res_v[nm] = {"auc": round(auc_all, 4), "aucByRc": aucs, "medAbsErrBidders": round(mae_b, 2)}
        print("  🌏 요인 비교", nm, res_v[nm], "| 권역별 쏠림", bias_by_class(pp))
    base_auc = res_v["물건 조건만"]["auc"]
    best_nm = max(res_v, key=lambda k: res_v[k]["auc"])
    use_pick = best_nm if res_v[best_nm]["auc"] >= base_auc + 0.002 else "물건 조건만"
    m, p_te, CF = preds[use_pick]
    print("  → 선택:", use_pick)
    auc, auc_r = res_v[use_pick]["auc"], res_v["+시군구+법정동"]["auc"]
    print(f"  물건별 응찰자 모델 AUC {auc:.3f} (지역 요인을 넣으면 {auc_r:.3f}), 학습 {tr.sum():,} 시험 {te.sum():,}")
    bn = np.exp(p_te); B = D["bidders"].values[te].astype(float)
    # 보정표: 예측 응찰자 수(bn)를 12분위로 나눠 실제 중앙·평균·몰림(8명+) 비율
    edges = np.quantile(bn, np.linspace(0, 1, 13)); edges[0] = 0; edges[-1] = 1e9
    calib = []
    for i in range(12):
        msk = (bn >= edges[i]) & (bn < edges[i + 1])
        if msk.sum() < 30: continue
        calib.append({"lo": round(float(edges[i]), 3), "hi": round(float(min(edges[i + 1], 1e6)), 3), "n": int(msk.sum()), "median": float(np.median(B[msk])), "q25": float(np.quantile(B[msk], .25)), "q75": float(np.quantile(B[msk], .75)), "mean": round(float(B[msk].mean()), 2), "crowdPct": round(float((B[msk] >= 8).mean() * 100), 1), "le3Pct": round(float((B[msk] <= 3).mean() * 100), 1)})
    # 몰림 예상 기준: 몰림 확률 50% 이상이 되는 가장 낮은 예측값, 적게 몰림: 확률 15% 이하
    hi = next((c["lo"] for c in calib if c["crowdPct"] >= 50), None); lo = max([c["hi"] for c in calib if c["crowdPct"] <= 15], default=None)
    def lvl_stat(msk):
        return {"n": int(msk.sum()), "share": round(float(msk.mean() * 100), 1), "crowdPct": round(float((B[msk] >= 8).mean() * 100), 1) if msk.sum() else None, "median": float(np.median(B[msk])) if msk.sum() else None}
    levels = {"몰림 예상": lvl_stat(bn >= hi) if hi else None, "적게 예상": lvl_stat(bn <= lo) if lo else None}
    # 개별 예상 오차: 예측 응찰자 수 vs 실제(중앙 절대 오차, 명)
    mae = float(np.median(np.abs(bn - B)))
    print("  보정표:", calib); print("  기준:", {"hi": hi, "lo": lo}, levels, "| 예측-실제 중앙 절대 오차", round(mae, 2), "명")
    # 2026-10-25(사용자: 입찰자 수는 정답을 찾는 분야가 아니다 - 그날 분위기에 따라 다르고 반대로 갈 수 있다) 얼마나 불확실한가
    try:
        Dte = D[te].copy(); Dte["bn"] = bn; Dte["res"] = np.log(Dte["bidders"].astype(float)) - np.log(bn)
        Dte["day"] = Dte["sale"].astype(int)
        # 같은 날 낙찰 사례끼리 잔차가 얼마나 같이 움직이나(그날 분위기): 날짜별 평균 잔차의 분산 ÷ 전체 분산
        g = Dte.groupby("day")["res"]; cnt = g.transform("count"); mean_day = g.transform("mean")
        # 자기 자신을 뺀 같은 날 평균과의 상관 = 그날 공통 요인
        loo = (mean_day * cnt - Dte["res"]) / (cnt - 1).replace(0, np.nan)
        ok = loo.notna() & (cnt >= 5)
        icc = float(np.corrcoef(Dte.loc[ok, "res"], loo[ok])[0, 1]) if ok.sum() > 500 else None
        # 같은 날 다른 사례들이 평소보다 많이 몰렸을 때(분위기) 내 사례 잔차 평균
        hot = Dte[ok & (loo > loo[ok].quantile(.75))]["res"].mean(); cold = Dte[ok & (loo < loo[ok].quantile(.25))]["res"].mean()
        # 예상이 반대로 간 비율
        hi_m = bn >= hi if hi else np.zeros(len(bn), bool); lo_m = bn <= lo if lo else np.zeros(len(bn), bool)
        rev = {"몰림 예상인데 4명 이하": round(float((B[hi_m] <= 4).mean() * 100), 1) if hi_m.sum() else None, "몰림 예상인데 8명 미만": round(float((B[hi_m] < 8).mean() * 100), 1) if hi_m.sum() else None,
               "적게 예상인데 6명 이상": round(float((B[lo_m] >= 6).mean() * 100), 1) if lo_m.sum() else None, "적게 예상인데 8명 이상": round(float((B[lo_m] >= 8).mean() * 100), 1) if lo_m.sum() else None}
        within = {"예측±2명 안": round(float((np.abs(bn - B) <= 2).mean() * 100), 1), "예측±3명 안": round(float((np.abs(bn - B) <= 3).mean() * 100), 1), "예측 25~75% 구간 안": None}
        covered = 0
        for c in calib:
            mk = (bn >= c["lo"]) & (bn < c["hi"]); covered += int(((B[mk] >= c["q25"]) & (B[mk] <= c["q75"])).sum())
        within["예측 25~75% 구간 안"] = round(covered / len(B) * 100, 1)
        # 표시 범위 후보별 적중률: 중앙값 ±1·±2·±3명, 25~75%, 중앙값 ±2와 25~75% 중 좁은 쪽
        cov = {}
        meds = np.zeros(len(bn)); q25s = np.zeros(len(bn)); q75s = np.zeros(len(bn))
        for c in calib:
            mk = (bn >= c["lo"]) & (bn < c["hi"]); meds[mk] = c["median"]; q25s[mk] = c["q25"]; q75s[mk] = c["q75"]
        for k in (1, 2, 3):
            cov[f"중앙값±{k}명"] = round(float((np.abs(B - meds) <= k).mean() * 100), 1)
        lo2 = np.maximum(q25s, meds - 2); hi2 = np.minimum(q75s, meds + 2)
        cov["좁은쪽(±2와 25~75% 중)"] = round(float(((B >= lo2) & (B <= hi2)).mean() * 100), 1)
        cov["넓이(좁은쪽) 평균 명"] = round(float((hi2 - lo2 + 1).mean()), 1)
        for nm2, mk2 in (("몰림예상", hi_m), ("적게예상", lo_m)):
            if mk2.sum(): cov[nm2 + " ±2명 적중"] = round(float((np.abs(B[mk2] - meds[mk2]) <= 2).mean() * 100), 1)
        print("  🎯 표시 범위 적중률:", cov)
        unc = {"coverage": cov, "dayCommonCorr": None if icc is None else round(icc, 3), "hotDayResid": round(float(hot), 3), "coldDayResid": round(float(cold), 3), "reversal": rev, "hit": within}
        print("  🎲 불확실성:", unc)
    except Exception as e:
        unc = None; print("  불확실성 계산 건너뜀:", e)
    # 2026-10-25 (낙찰 가능성 높은 구간 점검) 입찰자가 몰릴 것으로 예상된 물건은 예상 낙찰가보다 비싸게 낙찰되나? - 물건별 몰림 수준(몰림 예상/보통/적게 예상)별 예상 낙찰가 잔차를
    # 앞 절반으로 구해 뒤 절반에 적용했을 때 오차가 줄면 보정 값을 예상 낙찰가 모델에 저장(앱이 몰림 수준에 따라 예상 낙찰가를 조정). 아니면 저장 안 함
    crowd_adj = None
    try:
        mwb = wb_fit(D[tr]); pw = wb_predict(mwb, D[te])
        resw = (np.log(D["actual"].astype(float) / D["est"].astype(float)).values[te] - pw)
        lvl = np.where(hi_m, "높음", np.where(lo_m, "낮음", "보통"))
        order = np.argsort(D["sale"].values[te], kind="stable"); h = len(order) // 2
        a_i, b_i = order[:h], order[h:]
        sh = {}
        for L in ("높음", "보통", "낮음"):
            mk = lvl[a_i] == L
            if mk.sum() >= 150: sh[L] = float(np.median(resw[a_i][mk]))
        e_before = float(np.median(np.abs(np.exp(resw[b_i]) - 1))); adj = np.array([sh.get(L, 0.0) for L in lvl[b_i]])
        e_after = float(np.median(np.abs(np.exp(resw[b_i] - adj) - 1)))
        byl = {L: {"n": int((lvl == L).sum()), "medResid": round(float(np.median(resw[lvl == L])) * 100, 2)} for L in ("높음", "보통", "낮음") if (lvl == L).sum() >= 100}
        print("  🔥 몰림 수준별 예상 낙찰가 잔차:", byl, "| 시험(뒤 절반) 보통 오차", round(e_before * 100, 3), "→", round(e_after * 100, 3))
        if e_after < e_before - 0.0005 and "높음" in sh:
            allm = {L: float(np.median(resw[lvl == L])) for L in ("높음", "보통", "낮음") if (lvl == L).sum() >= 150}
            crowd_adj = {"adj": {L: round(max(-0.08, min(0.08, v)), 4) for L, v in allm.items()}, "n": int(len(resw)), "errBefore": round(e_before * 100, 3), "errAfter": round(e_after * 100, 3)}
        else:
            print("  → 몰림 수준 보정은 효과가 없어 저장하지 않음")
    except Exception as e:
        print("  몰림 수준 보정 검증 건너뜀:", e)
    if crowd_adj:
        try:
            _rr = requests.get(f"{cyc.SUPABASE_URL}/rest/v1/leader_follower_cache?select=payload&id=eq.signal%7C__winbid__", headers=cyc.HEADERS, timeout=60)
            if _rr.ok and _rr.json():
                _wb = _rr.json()[0].get("payload") or {}; _wb["crowdAdj"] = {**crowd_adj, "generatedAt": now}
                cyc.upsert_rows([{"id": "signal|__winbid__", "payload": cyc.clean_json(_wb), "fetched_at": now}]); print("  ✅ 몰림 수준 보정표 저장:", crowd_adj)
        except Exception as e:
            print("  몰림 수준 보정 저장 건너뜀:", e)
    # 배포용: 전체 데이터로 다시 학습
    mf = crowd_fit(X, y, CF)
    payload = {"generatedAt": now, "n": int(len(D)), "base": mf["base"], "eff": {f: {str(k): round(float(v), 4) for k, v in d.items()} for f, d in mf["eff"].items()}, "factors": [f for f, _ in CF],
               "calib": calib, "hiCut": hi, "loCut": lo, "levels": levels, "variants": res_v, "picked": use_pick, "uncertainty": unc, "metrics": {"auc": round(auc, 3), "aucWithRegion": round(auc_r, 3), "medAbsErrBidders": round(mae, 2), "testN": int(te.sum()), "testCrowdPct": round(float(crowd[te].mean() * 100), 1)}}
    cyc.upsert_rows([{"id": "signal|__crowd_model__", "payload": cyc.clean_json(payload), "fetched_at": now}])
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("### 물건별 예상 응찰자 수 모델\n```json\n" + json.dumps({k: payload[k] for k in ("n", "calib", "hiCut", "loCut", "levels", "metrics")}, ensure_ascii=False, indent=1) + "\n```\n")


def crowd_analysis(R, now):
    """2026-10-22(사용자: 입찰자가 보통 5명 이하인데 유독 몰리는 물건이 있다 - 지역 평균이 아니라 '몰릴 만한 물건'을 과거 사례로 골라낼 수 있나)
    목표: 응찰자 8명 이상(몰림). 입찰 전에 알 수 있는 정보만 사용 - 기존 경쟁 예상 요인(최저가÷시세·유찰·지역·인기 등급·계절·층·평형·시세 근거 거래 수·감정가 비율)에
    + 새 요인(최저가 금액·준공 연차·단지 거래량·특수조건 문구(유치권·지분·선순위 임차인 등)·토지 종류)을 더해 얼마나 더 잘 맞히는지(AUC·상위 10% 적중률) 비교하고,
    무엇이 몰림을 부르는지(요인별 몰림 비율)와 간단한 규칙(결정나무)을 뽑음. 시험 = 최근 12개월(학습에 안 씀). 결과: leader_follower_cache 'signal|__crowd__'"""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    from sklearn.tree import DecisionTreeClassifier, export_text
    from sklearn.inspection import permutation_importance
    D = R[R["bidders"].notna() & (R["bidders"] > 0) & R["est"].notna() & (R["est"] > 0) & R["minbid"].notna() & (R["minbid"] > 0) & (R["sale"] >= 20230101)].copy()
    if len(D) < 3000:
        print("  몰림 분석: 사례 부족"); return
    D["crowd"] = (D["bidders"] >= 8).astype(int)
    dist = {"n": int(len(D)), "median": float(D["bidders"].median()), "mean": round(float(D["bidders"].mean()), 2), "ge6Pct": round(float((D["bidders"] >= 6).mean()) * 100, 1), "ge8Pct": round(float((D["bidders"] >= 8).mean()) * 100, 1), "ge10Pct": round(float((D["bidders"] >= 10).mean()) * 100, 1), "le5Pct": round(float((D["bidders"] <= 5).mean()) * 100, 1)}
    print("  응찰자 분포:", dist)
    notes = D["notes"].fillna("").astype(str)
    KW = {"유치권": "유치권", "지분": "지분|공유", "선순위임차인": "선순위|대항력|임차인", "법정지상권": "지상권", "위반건축물": "위반", "재매각": "재매각", "대지권": "대지권", "농지": "농지|취득자격", "허가": "토지거래|허가"}
    for k, pat in KW.items():
        D["kw_" + k] = notes.str.contains(pat, regex=True).astype(int)
    D["kw_cnt"] = D[[c for c in D.columns if c.startswith("kw_") and c != "kw_cnt"]].sum(axis=1)
    D["lb"] = np.log(D["minbid"] / D["est"])  # 감정가(lab)는 쓰지 않음(2026-11-04)
    D["fails_n"] = D["fails"].map(lambda f: np.nan if f is None or pd.isna(f) else min(int(f), 4))
    D["logmin"] = np.log(D["minbid"].astype(float))
    D["season"] = ((D["sale"] // 100) % 100).astype(int)
    D["fl"] = pd.to_numeric(D["floor"], errors="coerce"); D["area_n"] = pd.to_numeric(D["area"], errors="coerce")
    D["age_n"] = pd.to_numeric(D["age"], errors="coerce"); D["cx3y_n"] = pd.to_numeric(D["cx3y"], errors="coerce"); D["dong3y_n"] = pd.to_numeric(D["dong3y"], errors="coerce"); D["own_n"] = pd.to_numeric(D["own"], errors="coerce")
    D["land_c"] = D["land"].fillna("").astype(str).str[:6]
    D["tier_c"] = D["tier"].fillna("없음").astype(str)
    D["region_c"] = D["region"].fillna("?").astype(str)
    cats = ["region_c", "tier_c", "land_c"]
    for c in cats:
        D[c + "_i"] = D[c].astype("category").cat.codes
    base_f = ["lb", "fails_n", "region_c_i", "tier_c_i", "season", "fl", "area_n", "own_n"]
    ext_f = base_f + ["logmin", "age_n", "cx3y_n", "dong3y_n", "land_c_i"] + [c for c in D.columns if c.startswith("kw_")]
    last = pd.to_datetime(str(int(D["sale"].max())), format="%Y%m%d"); cut = int((last - pd.DateOffset(months=12)).strftime("%Y%m%d"))
    tr, te = D[D["sale"] < cut], D[D["sale"] >= cut]
    out = {"generatedAt": now, "dist": dist, "test": {"n": int(len(te)), "crowdPct": round(float(te["crowd"].mean()) * 100, 1)}, "models": {}}
    def fit(fs):
        cat_mask = [f in ("region_c_i", "tier_c_i", "land_c_i") for f in fs]
        m = HistGradientBoostingClassifier(max_depth=5, learning_rate=0.06, max_iter=250, categorical_features=cat_mask, random_state=0)
        m.fit(tr[fs], tr["crowd"]); return m
    for nm, fs in (("기존 요인", base_f), ("기존+새 요인", ext_f)):
        m = fit(fs); pr = m.predict_proba(te[fs])[:, 1]
        res = {"auc": round(float(roc_auc_score(te["crowd"], pr)), 3)}
        for top in (0.05, 0.10, 0.20):
            thr = np.quantile(pr, 1 - top); sel = te[pr >= thr]
            res[f"top{int(top*100)}"] = {"n": int(len(sel)), "crowdPct": round(float(sel["crowd"].mean()) * 100, 1), "lift": round(float(sel["crowd"].mean() / te["crowd"].mean()), 2), "biddersMed": float(sel["bidders"].median())}
        out["models"][nm] = res; print("  ", nm, res)
        if nm == "기존+새 요인":
            mfin = m; pr_f = pr
    # 요인 중요도(시험 구간, 순열)
    try:
        smp = te.sample(min(4000, len(te)), random_state=1)
        pi = permutation_importance(mfin, smp[ext_f], smp["crowd"], scoring="roc_auc", n_repeats=3, random_state=0)
        imp = sorted(zip(ext_f, pi.importances_mean), key=lambda x: -x[1])[:12]
        NAME = {"lb": "최저가÷시세", "fails_n": "유찰 횟수", "region_c_i": "지역", "tier_c_i": "인기 등급", "season": "입찰 월", "fl": "층", "area_n": "면적", "own_n": "시세 근거 거래 수", "lab": "감정가÷시세", "logmin": "최저가 금액", "age_n": "준공 연차", "cx3y_n": "단지 3년 거래량", "dong3y_n": "동 3년 거래량", "land_c_i": "토지 종류"}
        out["importance"] = [{"feature": NAME.get(f, f.replace("kw_", "특수조건: ")), "auc_drop": round(float(v), 4)} for f, v in imp]
        print("  중요도:", out["importance"])
    except Exception as e:
        print("  중요도 건너뜀:", e)
    # 요인별 몰림 비율(전체 사례)
    base = D["crowd"].mean()
    def rate(G): return {"n": int(len(G)), "crowdPct": round(float(G["crowd"].mean()) * 100, 1), "biddersMed": float(G["bidders"].median())}
    tab = {"all": rate(D)}
    for lab, mask in (("최저가÷시세 0.5 미만", D["lb"] < np.log(0.5)), ("0.5~0.6", D["lb"].between(np.log(0.5), np.log(0.6), inclusive="left")), ("0.6~0.7", D["lb"].between(np.log(0.6), np.log(0.7), inclusive="left")), ("0.7~0.8", D["lb"].between(np.log(0.7), np.log(0.8), inclusive="left")), ("0.8 이상", D["lb"] >= np.log(0.8)),
                      ("신건", D["fails_n"] == 0), ("1회 유찰", D["fails_n"] == 1), ("2회+ 유찰", D["fails_n"] >= 2),
                      ("최저가 1억 미만", D["minbid"] < 10000), ("1~2억", D["minbid"].between(10000, 20000, inclusive="left")), ("2~4억", D["minbid"].between(20000, 40000, inclusive="left")), ("4억 이상", D["minbid"] >= 40000),
                      ("준공 10년 이하", D["age_n"] <= 10), ("11~25년", D["age_n"].between(11, 25)), ("26년 이상", D["age_n"] >= 26),
                      ("단지 3년 거래 100건+", D["cx3y_n"] >= 100), ("30건 미만", D["cx3y_n"] < 30),
                      ("특수조건 문구 없음", D["kw_cnt"] == 0), ("특수조건 문구 있음", D["kw_cnt"] >= 1)):
        G = D[mask]
        if len(G) >= 100: tab[lab] = rate(G)
    for k in KW:
        G = D[D["kw_" + k] == 1]
        if len(G) >= 80: tab["특수조건: " + k] = rate(G)
    out["byFactor"] = tab
    # 간단한 규칙(결정나무) - 앱에서 필터로 쓸 후보
    try:
        rf = ["lb", "fails_n", "logmin", "age_n", "cx3y_n", "kw_cnt", "own_n"]
        dt = DecisionTreeClassifier(max_depth=3, min_samples_leaf=250, random_state=0).fit(tr[rf].fillna(-1), tr["crowd"])
        out["tree"] = export_text(dt, feature_names=rf, show_weights=True)[:3000]
        leaves = dt.apply(te[rf].fillna(-1)); L = []
        for lf in np.unique(leaves):
            G = te[leaves == lf]
            L.append({"leaf": int(lf), "n": int(len(G)), "crowdPct": round(float(G["crowd"].mean()) * 100, 1)})
        out["treeLeavesTest"] = sorted(L, key=lambda x: -x["crowdPct"])
        print("  규칙(시험 구간 잎별 몰림):", out["treeLeavesTest"]); print(out["tree"])
    except Exception as e:
        print("  규칙 건너뜀:", e)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("### 입찰자 몰림 분석\n```json\n" + json.dumps(out, ensure_ascii=False, indent=1)[:9000] + "\n```\n")
    cyc.upsert_rows([{"id": "signal|__crowd__", "payload": cyc.clean_json(out), "fetched_at": now}])


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


# ════ 🎲 예상 낙찰가 모델 (2026-10, 사용자: "실제로 낙찰받을 수 있는 가격을 알고 싶다" → 검증 후 "넣어줘")
# 낙찰가 ÷ 입찰 30일 전 시세(같은 단지·평형 실거래 40% 지점)를 덧셈형 표로 예측: 최저가÷시세 구간(0.05 단위)·유찰 횟수·지역·인기 등급·계절·층·평형대·시세 근거 거래 수.
# 검증(2025-07 이후 6,781건, 학습엔 안 씀): 보통 오차 5.6%(지역 평균만 쓸 때 7.5%). 이길 확률은 "최근 1년을 빼고 만든 모델의 최근 1년 오차 분포"로 계산(시장 변화 반영).
# 앱(입찰후보·상세 창)이 같은 방식으로 시세를 구해 이 표로 예상 낙찰가와 "이 가격이면 낙찰 가능성"을 보여줌. 최저가는 낙찰가 예측에만 쓰고 예상매도가엔 안 씀.
# 2026-10-08 비중(축소 k) 조정 + 감정가 요인 추가(사용자: "예측과 차이나는 오차를 찾아 점수 반영 비율을 맞춰줘"): 3개 시험 구간(2025상·하반기·2026) 평균
#  보통 오차 5.46% → 5.22%, ±10% 77.1% → 78.6%, 예측 쏠림 −0.93% → 0%(예측가로 쓸 때 낙찰 45% → 50%).
#  k는 클수록 그 요인의 영향을 줄임(표본 적은 칸을 전체 평균 쪽으로 당김). 최근 사례 가중·지역 시장 분위기·준공연도 등은 시험했으나 효과 없거나 미미해 제외.
#  lab = 감정가÷시세 구간, lbl = 최저가×감정가 교호, labf = 감정가×유찰 교호(감정가는 최저가가 어떤 규칙으로 정해졌는지 알려 줌 - 낙찰가 예측에만 사용, 시세·예상매도가에는 안 씀)
WB_FACTORS = [("lb", 10), ("fails", 120), ("region", 120), ("tier", 5), ("season", 300), ("floor", 5), ("size", 30), ("own", 120), ("dong", 40), ("flowM", 60), ("flowL", 60), ("flowS", 60)]
# 2026-11-04(사용자 원칙): 입찰가·낙찰가는 '시세 대비 비율'만 - 시세와 시장 흐름(지역·동·시기·인기·층·크기·거래 활발도·유찰 횟수)과 시세 대비 최저가(입찰자 수를 정하는 큰 요소)로만 예측. 감정가는 철저히 계산에서 제외(결과 측정·금액 입력 점검에만 씀).
# 시세 흐름 요인(flowM·flowL·flowS: 수도권 법정동·시군구, 지방 단지, 가격×거래량)은 검증 성적과 상관없이 항상 포함(사용자 2026-11-05: 모든 가격에는 반드시 부동산 흐름이 반영돼야 함). 각 요인의 비중(k: 클수록 전국 평균 쪽으로 당김)은 winbid_model이 매주 감정가 없이 시간순 검증으로 다시 조정(wb_tune)
WB_CANDS = [("lbf", 40), ("lbs", 40), ("lbo", 40), ("regf", 60)]
# 서버가 좌표·세대수로만 계산할 수 있는 요인 - 앱이 아직 값을 못 받으므로 이번 단계에선 "효과만 측정"하고 실제 모델에는 넣지 않음(넣으면 앱 예측이 어긋남). 효과가 크면 서버가 값을 미리 계산해 앱에 주는 단계를 만듦
WB_CANDS_SERVER = [("flowR2", 60), ("flowT", 60), ("afC", 60), ("afR1", 60), ("afR2", 60), ("afR3", 60), ("afD", 60), ("afS", 60), ("afT2", 60), ("afTC", 60)]
SERVER_ONLY = {k for k, _ in WB_CANDS_SERVER}  # 감정가 없는 교호항 후보 - 검증에서 좋아질 때만 추가
WB_JB_FACTOR = ("jb", 40)  # 최근 거래 점프 요인 - winbid_model이 검증(학습에 안 쓴 최근 12개월)에서 좋아질 때만 WB_FACTORS에 넣음


def wb_features(D):
    X = pd.DataFrame(index=D.index)
    lmin = np.log(D["minbid"] / D["est"])
    X["lb"] = np.clip(np.floor(lmin / 0.05), -24, 9).fillna(-99).astype(int).astype(str)
    X["fails"] = D["fails"].map(lambda v: "?" if v is None or (isinstance(v, float) and np.isnan(v)) else str(min(int(v), 3)))
    X["region"] = D["region"].fillna("?")
    X["dong"] = D["region"].fillna("?") + "|" + D["dk"].fillna("").astype(str)  # 2026-10-09 법정동 보정(백테스트 보통 오차 5.23→5.15%, 전국 평균 쪽으로 k=40만큼 당김)
    X["tier"] = D["tier"].fillna("없음")
    m = (D["sale"] // 100) % 100
    X["season"] = m.map(lambda v: "겨울" if v in (12, 1, 2) else ("봄" if v <= 5 else ("여름" if v <= 8 else "가을")))
    X["floor"] = D["floor"].map(lambda f: "1층" if f == 1 else ("2~3층" if f in (2, 3) else "4층+"))
    X["size"] = D["area"].map(lambda a: "소형" if a < 60 else ("중형" if a <= 85 else "대형"))
    X["own"] = D["own"].map(lambda n: "1~2" if n <= 2 else ("3~5" if n <= 5 else ("6~10" if n <= 10 else "11+")))
    # 2026-11-04(사용자 원칙): 감정가는 계산에 일절 쓰지 않음(감정가÷시세·교호항 계산 삭제). 시세 대비 최저가(lb)는 입찰자 수를 정하는 큰 요소라 유지하고, 교호항은 감정가 없이 최저가·유찰·지역·크기·거래 활발도로만 만듦
    # 🌊 시세 흐름 요인(2026-11-04) - 수도권(서울·경기·인천)과 지방을 따로 만듦. 값이 없으면(표본 부족) "-"라서 노이즈 없이 효과가 0 쪽으로 감
    def _b5(v):
        return "-" if v is None or not np.isfinite(v) else ("dn2" if v <= -0.04 else ("dn1" if v <= -0.01 else ("fl" if v <= 0.01 else ("up1" if v <= 0.04 else "up2"))))
    def _b3(v):
        return "-" if v is None or not np.isfinite(v) else ("dn" if v <= -0.03 else ("up" if v >= 0.03 else "fl"))
    def _bv(v):  # 거래량 흐름: 최근 3개월 거래가 앞 9개월 분기 평균보다 20% 넘게 줄었나/늘었나
        return "-" if v is None or not np.isfinite(v) else ("vd" if v <= -0.2 else ("vu" if v >= 0.2 else "vf"))
    def _col(n):
        return pd.to_numeric(D[n], errors="coerce") if n in D.columns else pd.Series(np.nan, index=D.index)
    fcls = D["flow_cls"].fillna("?") if "flow_cls" in D.columns else pd.Series("?", index=D.index)
    fd, fdv, fs, fsv, fc, fcv = _col("flow_dong"), _col("flow_dong_v"), _col("flow_sgg"), _col("flow_sgg_v"), _col("flow_cx"), _col("flow_cx_v")
    X["flowM"] = [("수도권|동|" + _b5(a) + "|" + _bv(av) if (c == "수도권" and (np.isfinite(a) or np.isfinite(av))) else ("수도권|시군구|" + _b5(b) + "|" + _bv(bv) if c == "수도권" else "-")) for c, a, av, b, bv in zip(fcls, fd, fdv, fs, fsv)]
    X["flowL"] = [("지방|단지|" + _b3(a) + "|" + _bv(av) if c == "지방" else "-") for c, a, av in zip(fcls, fc, fcv)]
    X["flowS"] = [str(c) + "|" + _b5(b) + "|" + _bv(bv) for c, b, bv in zip(fcls, fs, fsv)]
    def _bt(v):  # 회전율: 최근 3개월 거래 ÷ 세대수 × 100 (분기). 연 5% 안팎 = 1.2
        return "-" if v is None or not np.isfinite(v) else ("tl" if v < 0.7 else ("th" if v > 1.8 else "tm"))
    for _km in (1, 2, 3):
        _p_, _v_ = _col(f"flowR{_km}_p"), _col(f"flowR{_km}_v")
        X[f"flowR{_km}"] = [str(c) + "|" + _b5(a) + "|" + _bv(b) for c, a, b in zip(fcls, _p_, _v_)]
    _t2, _p2 = _col("flowR2_t"), _col("flowR2_p")
    X["flowT"] = [str(c) + "|" + _bt(t) + "|" + _b3(a) for c, t, a in zip(fcls, _t2, _p2)]
    _tc = _col("flow_cx_t")
    X["flowLT"] = [("지방|단지|" + _bt(t) + "|" + _bv(v)) if c == "지방" else "-" for c, t, v in zip(fcls, _tc, fcv)]
    for _n in ("C", "R1", "R2", "R3", "D", "S", "T2", "TC"):
        X[f"af{_n}"] = D[f"af{_n}_s"].fillna("-").values if f"af{_n}_s" in D.columns else "-"
    X["lbf"] = X["lb"] + "|" + X["fails"]
    X["lbs"] = X["lb"] + "|" + X["size"]
    X["lbo"] = X["lb"] + "|" + X["own"]
    X["regf"] = X["region"] + "|" + X["fails"]
    if "notes" in D.columns:  # 2026-10-29 경매현황 특이사항 태그(HUG 임차권 인수조건변경·임차권등기·대항력 있는 임차인) - 실험용 요인(WB_FACTORS에 넣을 때만 쓰임)
        nt = D["notes"].fillna("").astype(str)
        X["hug"] = np.where(nt.str.contains("HUG"), "HUG", np.where(nt.str.contains("임차권|대항력"), "임차", "없음"))
    jbv = pd.to_numeric(D["jb"], errors="coerce") if "jb" in D.columns else pd.Series(np.nan, index=D.index)
    X["jb"] = jbv.map(lambda v: "?" if v is None or not np.isfinite(v) else ("dn" if v <= -0.05 else ("fl" if v <= 0.05 else ("up1" if v <= 0.12 else ("up2" if v <= 0.20 else "up3")))))
    return X


def wb_fit(D, iters=6):
    return wb_fit_y(D, np.log(D["actual"] / D["est"]).values, iters)


def wb_fit_y(D, y, iters=6):
    X = wb_features(D)
    base = float(np.median(y))
    eff = {f: {} for f, _ in WB_FACTORS}
    pred = np.full(len(y), base)
    for _ in range(iters):
        for f, k in WB_FACTORS:
            cur = X[f].map(eff[f]).fillna(0).values
            r = y - (pred - cur)
            g = pd.DataFrame({"k": X[f].values, "r": r}).groupby("k")["r"].agg(["median", "count"])
            new = (g["median"] * g["count"] / (g["count"] + k)).to_dict()
            eff[f] = new
            pred = pred - cur + X[f].map(new).fillna(0).values
    return {"base": base, "eff": {f: {str(k): round(float(v), 4) for k, v in d.items()} for f, d in eff.items()}, "n": int(len(y))}


def wb_tune(tr, factors0, cands):
    """2026-11-04(사용자: 감정가는 무시하되 다른 요인들의 비중을 조절해 최고의 정확도를) - 학습 구간(tr)만 써서 시간순 2개 검증 구간(직전 12개월·그 앞 12개월)의 보통 오차(평균)가 가장 낮아지도록
    ① 요인별 비중(k)을 ×0.5·×2로 두 바퀴 조정 ② 교호항 후보를 하나씩 추가해 0.01%p 넘게 좋아질 때만 채택. 최종 검증(최근 12개월)은 여기에 쓰지 않아 숫자가 부풀지 않음."""
    global WB_FACTORS
    last = pd.to_datetime(str(int(tr["sale"].max())), format="%Y%m%d")
    folds = []
    for m_ in (12, 24):
        hi = int((last - pd.DateOffset(months=m_ - 12)).strftime("%Y%m%d")) if m_ > 12 else int(tr["sale"].max()) + 1
        lo = int((last - pd.DateOffset(months=m_)).strftime("%Y%m%d"))
        trn, tst = tr[tr["sale"] < lo], tr[(tr["sale"] >= lo) & (tr["sale"] < hi)]
        if len(trn) >= 3000 and len(tst) >= 500: folds.append((trn, tst))
    if not folds:
        return factors0, {"skipped": "검증 구간 부족"}
    def score(fl):
        global WB_FACTORS
        WB_FACTORS = fl; es = []
        for trn, tst in folds:
            p_ = wb_predict(wb_fit(trn), tst); es.append(float(np.median(np.abs(np.exp(p_) * tst["est"].values / tst["actual"].values - 1))))
        return float(np.mean(es))
    keep = WB_FACTORS
    try:
        cur = [tuple(f) for f in factors0]; best = score(cur); start = best
        for _pass in range(2):
            for i in range(len(cur)):
                for mult in (0.5, 2.0):
                    trial = list(cur); trial[i] = (cur[i][0], max(1, round(cur[i][1] * mult)))
                    sc = score(trial)
                    if sc < best - 0.00005: best, cur = sc, trial
        added = []
        for _round in range(5):
            pick = None
            for nm, k0 in cands:
                if any(f[0] == nm for f in cur): continue
                for k in ((k0,) if nm in SERVER_ONLY else (k0, k0 * 3)):
                    sc = score(cur + [(nm, k)])
                    if sc < best - 0.0001 and (pick is None or sc < pick[0]): pick = (sc, (nm, k))
            if not pick: break
            best = pick[0]; cur = cur + [pick[1]]; added.append(pick[1][0])
        info = {"folds": len(folds), "startErrPct": round(start * 100, 3), "tunedErrPct": round(best * 100, 3), "factors": [[f, k] for f, k in cur], "added": added}
        print("  🎛  요인 비중 조정(감정가 제외):", json.dumps(info, ensure_ascii=False))
        return cur, info
    finally:
        WB_FACTORS = keep


def wb_predict(model, D):
    X = wb_features(D)
    p = np.full(len(D), model["base"])
    for f, _ in WB_FACTORS:
        if f in model["eff"]:
            p = p + X[f].map(model["eff"][f]).fillna(0).values
    return p


def liquidity_curve(R, now_iso):
    """2026-10-11 환금성 곡선(사용자: 회전율·호가 매물을 활용) - 같은 평형 최근 1년 거래 수(n12)별로 낙찰 후 6/12개월 안 같은 동·층 되팔림 흔적 비율, 되판 기간, 손실률, 낙찰가÷예상매도가.
    보유 기간(이자 가정): 18개월 안 되팔림이 25% 미만이면 되판 기간 상위 25% 값, 아니면 평균(3~12개월로 제한). 낙찰 1년(18개월) 이상 지난 2023년~ 사례만 씀."""
    D = R[(R["sale"] >= 20230101) & R["n12"].notna() & R["est"].notna()].copy()
    if len(D) < 3000:
        print("  환금성 곡선: 사례 부족, 건너뜀"); return
    D["dt"] = pd.to_datetime(D["sale"].astype(int).astype(str), format="%Y%m%d", errors="coerce")
    now = pd.Timestamp(now_iso[:10])
    O12 = D[D["dt"] <= now - pd.Timedelta(days=365)]; O18 = D[D["dt"] <= now - pd.Timedelta(days=548)]
    bins = []
    for lo, hi, lab in ((0, 2, "2건 이하"), (3, 5, "3~5건"), (6, 10, "6~10건"), (11, 20, "11~20건"), (21, 10 ** 9, "21건 이상")):
        a = O12[(O12["n12"] >= lo) & (O12["n12"] <= hi)]; b = O18[(O18["n12"] >= lo) & (O18["n12"] <= hi)]
        if len(a) < 100 or len(b) < 100: continue
        w = b[(b["resale_conf"] == "dong") & (b["resale_m"] <= 18)]
        if len(w) < 30: continue
        p18 = len(w) / len(b); s = a[(a["resale_conf"] == "dong") & a["resale"].notna()]; allc = D[(D["n12"] >= lo) & (D["n12"] <= hi)]
        hold = round(float(w["resale_m"].quantile(.75))) if p18 < 0.25 else round(float(w["resale_m"].mean()))
        bins.append({"lo": lo, "hi": hi if hi < 10 ** 9 else None, "label": lab, "n": int(len(a)),
                     "p6": round(float(((a["resale_conf"] == "dong") & (a["resale_m"] <= 6)).mean()) * 100, 1), "p12": round(float(((a["resale_conf"] == "dong") & (a["resale_m"] <= 12)).mean()) * 100, 1),
                     "p18": round(p18 * 100, 1), "medMonths": round(float(w["resale_m"].median()), 1), "meanMonths": round(float(w["resale_m"].mean()), 1), "p75Months": round(float(w["resale_m"].quantile(.75)), 1),
                     "lossPct": round(float(s["loss"].mean()) * 100, 1) if len(s) else None, "bidRatio": round(float((allc["actual"] / allc["est"]).median()), 3), "holdMonths": int(max(3, min(12, hold)))})
    if len(bins) < 4: return
    payload = {"generatedAt": now_iso, "basis": "입찰 30일 전 기준 같은 단지·같은 평형(±3㎡) 최근 1년 중개거래 수(n12) - 낙찰사례 2023~", "note": "p6/p12 = 낙찰 후 6/12개월 안 같은 동·같은 층 되팔림 흔적(낙찰 1년 이상 지난 사례), p18·medMonths = 18개월+ 지난 사례", "bins": bins}
    print("  환금성 곡선:", json.dumps([(b["label"], b["p6"], b["holdMonths"]) for b in bins], ensure_ascii=False))
    cyc.upsert_rows([{"id": "signal|__liqcurve__", "payload": cyc.clean_json(payload), "fetched_at": now_iso}])


def ymd_ord(a):
    """yyyymmdd 정수(배열) → 1970-01-01부터 지난 날수(벡터 계산)"""
    a = np.asarray(a, dtype=np.int64); y = a // 10000; m = (a // 100) % 100; d = a % 100
    y = y - (m <= 2); era = y // 400; yoe = y - era * 400; mp = np.where(m > 2, m - 3, m + 9)
    doy = (153 * mp + 2) // 5 + d - 1; doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def adaptive_flow(dd, pp, cut_ymd, K, max_days):
    """🌊 적응형 흐름(2026-11-04, 사용자: 고정 건수·기간 기준은 수도권에만 맞음 - 지방은 거래가 적어 노이즈) -
    비교 기간 W = max(입찰 30일 전 이전 최근 K건이 걸린 기간, 90일): 거래가 적은 곳은 W가 자동으로 길어지고, 많은 곳도 90일보다 짧게 쓰지 않음(며칠치 가격에 흔들리지 않게).
    최근 W일(R)과 그 앞 W일(P)을 비교하고, P에도 K건 이상 있어야 하며 2W가 max_days를 넘으면 None.
    rate = 가격 변화(로그)를 W로 연율화, z = 변화 ÷ 불확실성(묶음 안 가격 흩어짐 MAD/√건수) - |z|<1이면 보합(불확실)로 취급, vol = 거래 수 변화(로그, +1 보정), dens = 최근 W의 하루 거래 수.
    dd=정렬된 거래일 yyyymmdd, pp=㎡당 가격"""
    if dd is None or len(dd) == 0: return None
    i = int(np.searchsorted(dd, int(cut_ymd)))
    if i < 2 * K: return None
    co = int(ymd_ord([int(cut_ymd)])[0]); oK = int(ymd_ord([int(dd[i - K])])[0]); W = max(co - oK, 90)
    if 2 * W > max_days: return None
    oall = ymd_ord(dd[max(0, i - 4000):i]); base = max(0, i - 4000)
    a1 = int(np.searchsorted(oall, co - W)); a0 = int(np.searchsorted(oall, co - 2 * W))
    nR, nP = (len(oall) - a1), (a1 - a0)
    if nR < K or nP < K: return None
    lr = np.log(np.asarray(pp[base + a1:i], dtype=float)); lp = np.log(np.asarray(pp[base + a0:base + a1], dtype=float))
    mR, mP = float(np.median(lr)), float(np.median(lp)); flow = mR - mP
    sR, sP = 1.4826 * float(np.median(np.abs(lr - mR))), 1.4826 * float(np.median(np.abs(lp - mP)))
    se = max(1.2533 * float(np.sqrt(sR ** 2 / nR + sP ** 2 / nP)), 0.005)
    return {"rate": flow / (W / 365.0), "z": flow / se, "vol": float(np.log((nR + 1) / (nP + 1))), "dens": nR / W}


def flow_pv(dd_p, pp, dd_v, cut_ymd, min_p, min_base):
    """🌊 시세 흐름 = 가격 + 거래량(2026-11-04, 사용자: 거래량이 줄어드는데 신고가면 하락 쪽, 거래량이 늘며 가격이 다져지면 상승기 쪽 - 가격만으로는 흐름을 못 봄) -
    입찰 30일 전(cut) 기준 ① 가격: 최근 3개월 ㎡당 가격 중위값 ÷ 그 앞 3개월 중위값(로그), 두 구간 모두 min_p건 이상이어야 함 ② 거래량: 최근 3개월 거래 수 ÷ 그 앞 9개월의 분기 평균 거래 수(로그, +1 보정),
    앞 9개월 거래가 min_base건 이상이어야 함. 모자라면 None(노이즈 방지: 값을 억지로 만들지 않음). dd_p·pp=가격용(날짜 yyyymmdd 정렬, ㎡당 가격), dd_v=거래량용 날짜(정렬)"""
    ref = int_to_date(int(cut_ymd)); price = None; vol = None
    lo1, lo2, lo3 = ymd_int(ref - timedelta(days=90)), ymd_int(ref - timedelta(days=180)), ymd_int(ref - timedelta(days=360))
    if dd_p is not None and len(dd_p):
        i2, i1, i0 = int(np.searchsorted(dd_p, lo2)), int(np.searchsorted(dd_p, lo1)), int(np.searchsorted(dd_p, int(cut_ymd)))
        R_, P_ = pp[i1:i0], pp[i2:i1]
        if len(R_) >= min_p and len(P_) >= min_p:
            a, b = float(np.median(R_)), float(np.median(P_))
            price = float(np.log(a / b)) if a > 0 and b > 0 else None
    if dd_v is not None and len(dd_v):
        a0, a1, a2 = int(np.searchsorted(dd_v, lo3)), int(np.searchsorted(dd_v, lo1)), int(np.searchsorted(dd_v, int(cut_ymd)))
        nR, nB = a2 - a1, a1 - a0
        if nB >= min_base:
            vol = float(np.log((nR + 1) / (nB / 3.0 + 1)))
    return price, vol


def _wmed(v, w):
    o = np.argsort(v); v = np.asarray(v, dtype=float)[o]; w = np.asarray(w, dtype=float)[o]
    c = (np.cumsum(w) - 0.5 * w) / w.sum()
    return float(np.interp(0.5, c, v))


FLOW_COEF = 1.5   # 흐름 반영 계수 기본값(2026-11-05 점검: 1.5~3에서 오차 최소·평탄, 0.6은 얻을 개선의 일부만)
FLOW_COEF_CLS = {"수도권": FLOW_COEF, "지방": FLOW_COEF}   # 지역등급별 계수 - 매주 흐름 실험(analyze-flow-lab)이 고른 값으로 갱신(load_flow_coef), 못 읽으면 기본값


RISK_DISP = {}   # 거래 활발 단지의 흩어짐별 하방 표(흐름 연구실, 경계 포함)
RISK_BY_TRADES = {}   # 흐름 연구실이 실거래로 만든 근거 두께별 하방 표(낙찰 사례 없는 서울·경기·인천 칸 보충)


def load_flow_coef():
    try:
        d = requests.get(f"{SITE_URL}/api/data-coverage?mode=flowLab&nocache=1&x={int(time.time())}", timeout=120).json()
        auto = ((d.get("coeff") or {}).get("coefAuto")) or {}
        for k_ in ("수도권", "지방"):
            v_ = auto.get(k_)
            if isinstance(v_, (int, float)) and 0.3 <= v_ <= 5: FLOW_COEF_CLS[k_] = float(v_)
        print("  🔁 흐름 계수(주간 자동 선택):", FLOW_COEF_CLS)
        rdp = (d.get("coeff") or {}).get("riskDisp")
        if isinstance(rdp, dict) and rdp.get("칸"): RISK_DISP.update(rdp); print("  📉 흩어짐별 하방 표:", {k_: v_["n"] for k_, v_ in RISK_DISP["칸"].items()})
        rbt = (d.get("coeff") or {}).get("riskByTrades")
        if isinstance(rbt, dict) and "error" not in rbt: RISK_BY_TRADES.update(rbt); print("  📉 실거래 기반 하방 표:", {k_: v_["n"] for k_, v_ in RISK_BY_TRADES.items()})
    except Exception as e:
        print("  흐름 계수 자동 선택 못 읽음(기본값 사용):", e)


def flow_gate_g(rate, vol):
    """거래량으로 가격 흐름 믿음을 조절하던 값 - 2026-11-05 점검에서 시세 보정에는 도움이 안 돼 쓰지 않음(항상 1)"""
    return 1.0


def pick_flow(cls2, d_res, s_res, c_res):
    """시세에 반영할 흐름 하나 고르기: 수도권=법정동→시군구, 지방=시군구. 가격 변화가 불확실(|z|<1)하면 건너뜀(노이즈 방지). 없으면 None"""
    for r_ in ((d_res, s_res) if cls2 == "수도권" else (s_res,)):   # 지방도 시군구(2026-11-05 점검: 같은 단지 흐름은 노이즈로 오히려 나빴음)
        if r_ is not None and np.isfinite(r_["z"]) and abs(r_["z"]) >= 1.0:
            return {"rate": float(r_["rate"]), "vol": float(r_["vol"])}
    return None


def thin_variants(g, c, cut, cut_ym, idx_at, dg, rg):
    """2026-11-06 근거가 얇을 때(6개월 같은 평형 0~2건) 시세 후보들(시험용, 입찰 30일 전까지 정보만 사용):
    tv_prem = 단지 프리미엄 × 지금 주변 시세 - 같은 단지 같은 평형 최근 36개월 거래마다 '그때 같은 법정동(없으면 시군구) 비슷한 평형 ㎡당 중위값 대비 비율'을 구해 가중 중위(반감 6개월)로 모으고, 지금(최근 4개월) 주변 ㎡당 중위값에 곱함 - 오래된 거래를 그 시점의 동네 시세로 정확히 옮김
    tv_flow = 오래된 거래(36개월 안)를 시군구 최근 흐름×나이로 옮긴 가중 중위(반감 3개월)
    tv_idx = 시군구 월별 지수로 36개월 안 거래를 지금 수준에 맞춘 가중 중위(반감 3개월, 지수 없으면 원값)
    tv_oth = 같은 단지 다른 평형 24개월 ㎡당 가격(지수 보정) 환산(탄력 -0.285)"""
    out = {}; area = float(c.area); cut_d = int_to_date(int(cut)); co = int(ymd_ord([int(cut)])[0])
    h = g[(g["deal_date"] < cut) & ((g["size"] - area).abs() <= 3)]
    h = h[h["deal_date"] >= ymd_int(cut_d - timedelta(days=1095))]
    base = idx_at(c.region, cut_ym)
    if len(h):
        hd = ymd_ord(h["deal_date"].values.astype(np.int64)); age = (co - hd) / 30.4; ph = h["price"].values.astype(float); pm = h["ppm"].values.astype(float); ym = h["ym"].values
        # 지수 보정
        v, w = [], []
        for pr, ag, y_ in zip(ph, age, ym):
            b0 = idx_at(c.region, int(y_)); f = max(0.6, min(1.6, base / b0)) if (base and b0) else 1.0
            v.append(pr * f); w.append(0.5 ** (ag / 3.0))
        out["tv_idx"] = float(_wmed(v, w))
        # 흐름 보정
        _sres = adaptive_flow(rg[0], rg[1], cut, 40, 365) if rg else None
        rate = float(_sres["rate"]) if (_sres is not None and np.isfinite(_sres["z"]) and abs(_sres["z"]) >= 1.0) else 0.0
        out["tv_flow"] = float(_wmed(ph * np.clip(np.exp(FLOW_COEF * rate * age / 12.0), 0.8, 1.25), 0.5 ** (age / 3.0)))
        # 단지 프리미엄 × 지금 주변 시세
        def ctrl(c_lo, c_hi, use_size=True):
            for src in (0, 1):
                if src == 0 and dg is not None:
                    dd, sz, pp = dg[0], dg[1], dg[2]
                    a, b = int(np.searchsorted(dd, c_lo)), int(np.searchsorted(dd, c_hi)); x = pp[a:b]; s_ = sz[a:b]
                    x = x[np.abs(s_ - area) <= 15]
                elif src == 1 and rg is not None:
                    dd, pp = rg[0], rg[1]; a, b = int(np.searchsorted(dd, c_lo)), int(np.searchsorted(dd, c_hi)); x = pp[a:b]
                else:
                    continue
                if len(x) >= 8: return float(np.median(x)), src
            return None, None
        L0, s0 = ctrl(ymd_int(cut_d - timedelta(days=120)), int(cut))
        if L0:
            rat, rw = [], []
            for d_, p_, ag in zip(h["deal_date"].values, pm, age):
                dt = int_to_date(int(d_)); hi = min(int(cut), ymd_int(dt + timedelta(days=90)))
                Lc, _ = ctrl(ymd_int(dt - timedelta(days=90)), hi)
                if Lc: rat.append(p_ / Lc); rw.append(0.5 ** (ag / 6.0))
            if rat:
                out["tv_prem"] = float(_wmed(rat, rw)) * L0 * area; out["tv_prem_src"] = s0
    # 같은 단지 다른 평형
    o = g[(g["deal_date"] < cut) & ((g["size"] - area).abs() > 3) & (g["deal_date"] >= ymd_int(cut_d - timedelta(days=730)))]
    if len(o) and base:
        pp_, sz_ = [], []
        for ppm, y_, z in zip(o["ppm"].values, o["ym"].values, o["size"].values):
            b0 = idx_at(c.region, int(y_))
            if b0: pp_.append(ppm * max(0.6, min(1.6, base / b0))); sz_.append(z)
        if pp_:
            r = area / float(np.median(sz_))
            if 0.6 <= r <= 1.6: out["tv_oth"] = float(np.median(pp_)) * area * float(np.exp(-0.285 * np.log(r)))
    return out


def est_rule_asof(g, c, sale_d, cut, cut_ym, idx_at, flow=None):
    """2026-10-20 앱의 새 예상매도가 규칙을 '입찰 30일 전 시점'으로 재현(사용자: 낙찰가 모델의 시세 기준을 새 규칙으로 바꾸면 오차가 줄까)
    6개월 같은 평형(±3㎡) 3건+ → 서울 최근3건 중위 / 경기·인천 반감1개월 / 지방 반감2개월 가중 중위. 부족하면 같은 평형 36개월(6개월 밖은 시군구 지수 보정, 반감3개월; 지방 최근 1건+는 12개월 원값),
    없으면 같은 단지 다른 평형 12개월 ㎡당 가격 환산. 같은 평형 이전 값과 다른 평형 값이 둘 다 있고 6개월 안 거래가 없으면 6:4. (층·회전율·전세 보정은 제외)"""
    area = float(c.area)
    cut_d = int_to_date(int(cut))
    h = g[(g["deal_date"] < cut) & ((g["size"] - area).abs() <= 3)]
    if len(h):
        age = np.array([(cut_d - int_to_date(int(x))).days / 30.4 for x in h["deal_date"].values])
    else:
        age = np.array([])
    price = h["price"].values.astype(float) if len(h) else np.array([])
    # 📈 지역 가격 흐름 반영(2026-11-05, 사용자: 모든 가격에 부동산 흐름 반영): 12개월 안 원값 거래를 거래 나이(년)×연율 흐름×계수(FLOW_COEF)로 지금 시점에 맞춤(-5%~+8%). flow=None이면 예전 값 그대로
    pf = price
    if flow is not None and len(price):
        _g = flow_gate_g(flow["rate"], flow.get("vol"))
        pf = price * np.where(age <= 12, np.clip(np.exp(FLOW_COEF_CLS["수도권" if str(c.region).split(" ")[0][:2] in ("서울", "경기", "인천") else "지방"] * flow["rate"] * _g * age / 12.0), 0.95, 1.08), 1.0)
    sido = str(c.region).split(" ")[0]
    cls = "서울" if sido.startswith("서울") else ("경기·인천" if sido[:2] in ("경기", "인천") else "지방")
    m6 = age <= 6; n6 = int(m6.sum())
    if n6 >= 3:
        p6, a6 = pf[m6], age[m6]
        if cls == "서울": return float(np.median(p6[np.argsort(a6)[:3]]))
        return _wmed(p6, 0.5 ** (a6 / (1.0 if cls == "경기·인천" else 2.0)))
    base = idx_at(c.region, cut_ym)
    t2 = None
    m36 = age <= 36
    if m36.any():
        if cls == "지방" and n6 >= 1:
            m12 = age <= 12
            t2 = _wmed(pf[m12], 0.5 ** (age[m12] / 3.0))
        else:
            vals, ws = [], []
            for pr, ag, ym, pfv in zip(price[m36], age[m36], h["ym"].values[m36], pf[m36]):
                v = pfv
                if ag > 6:
                    v = pr
                    b0 = idx_at(c.region, int(ym))
                    if not (base and b0): continue
                    v = pr * max(0.7, min(1.4, base / b0))
                vals.append(v); ws.append(0.5 ** (ag / 3.0))
            if vals: t2 = _wmed(vals, ws)
    o = g[(g["deal_date"] < cut) & ((g["size"] - area).abs() > 3)]
    t3 = None
    if len(o) and base:
        oa = np.array([(cut_d - int_to_date(int(x))).days / 30.4 for x in o["deal_date"].values]); k12 = oa <= 12
        if k12.sum() >= 2:
            pp, sz = [], []
            for ppm, ym, z in zip(o["ppm"].values[k12], o["ym"].values[k12], o["size"].values[k12]):
                b0 = idx_at(c.region, int(ym))
                if b0: pp.append(ppm * max(0.7, min(1.4, base / b0))); sz.append(z)
            if len(pp) >= 2:
                ms = float(np.median(sz)); r = area / ms
                if 0.6 <= r <= 1.6: t3 = float(np.median(pp)) * area * float(np.exp(-0.285 * np.log(r)))
    if t2 and t3 and abs(t3 / t2 - 1) > 0.20: t3 = None
    if t2 and t3 and n6 == 0: return 0.6 * t2 + 0.4 * t3
    return t2 or t3


def est_rule_experiment(R, wb_fit, wb_predict, now, cands=(("기존", "est"), ("새규칙", "est_rule")), title="낙찰가 모델 시세 기준 비교"):
    """낙찰가 모델의 시세 기준(est)을 새 규칙(est_rule)으로 바꾸면 예상 낙찰가 오차가 줄어드나 - 같은 사례·같은 검증 구간에서 비교"""
    print(f"  새 규칙 시세 계산됨: {int(R['est_rule'].notna().sum()):,}/{len(R):,}건")
    D = R[R["actual"].notna() & R["minbid"].notna() & (R["minbid"] > 0) & (R["sale"] >= 20200101)].copy()
    for _, col in cands:
        D = D[D[col].notna() & (D[col] > 0)]
        D = D[np.log(D["actual"] / D[col]).between(np.log(0.4), np.log(1.6))]
    if len(D) < 3000:
        print("  새 시세 기준 실험: 사례 부족"); return
    last = pd.to_datetime(str(int(D["sale"].max())), format="%Y%m%d")
    out = {"n": int(len(D)), "folds": []}
    lines = []
    for months in (12, 6):
        cut = int((last - pd.DateOffset(months=months)).strftime("%Y%m%d")); tr, te = D[D["sale"] < cut], D[D["sale"] >= cut]
        if len(te) < 300: continue
        res = {}
        for nm, col in cands:
            T, E = tr.copy(), te.copy(); T["est_o"] = T["est"]; E["est_o"] = E["est"]
            T["est"] = T[col]; E["est"] = E[col]
            m = wb_fit(T); pr = np.exp(wb_predict(m, E)) * E["est"]
            r = pr / E["actual"] - 1
            res[nm] = (r.values, E["region"].values)
        for nm, (r, rg) in res.items():
            for cls, mk in (("전체", np.ones(len(r), bool)), ("서울", np.array([str(x).startswith("서울") for x in rg])), ("경기·인천", np.array([str(x)[:2] in ("경기", "인천") for x in rg])), ("지방", np.array([not (str(x).startswith("서울") or str(x)[:2] in ("경기", "인천")) for x in rg]))):
                if mk.sum() < 100: continue
                a = np.abs(r[mk])
                lines.append({"검증": f"최근 {months}개월", "시세기준": nm, "구분": cls, "n": int(mk.sum()), "보통오차": round(float(np.median(a)) * 100, 2), "방향": round(float(np.median(r[mk])) * 100, 2), "10안": round(float((a <= .1).mean()) * 100, 1), "p90": round(float(np.quantile(a, .9)) * 100, 1)})
    for l in lines: print("  ", json.dumps(l, ensure_ascii=False))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("### " + title + "\n```json\n" + json.dumps(lines, ensure_ascii=False, indent=1) + "\n```\n")


def resale_gap_report(R, now):
    """2026-10-20 예상매도가(새 규칙, 입찰 30일 전 시점) ÷ 실제 되판 가격 - 낙찰 후 되판 사례(같은 동·층 확인)에서 보유 기간·지역·거래 수별 간극과 시장 변화 몫
    gap = 되판가 ÷ 예상매도가 - 1 (양수면 예상보다 비싸게 팔림). mkt 보정 gap = 시장 지수 변화를 뺀 나머지(상태·협상·층/호수 차이 등)"""
    D = R[(R["resale_conf"] == "dong") & R["resale"].notna() & R["est_rule"].notna() & (R["est_rule"] > 0) & R["resale_m"].between(0.45, 12) & (R["sale"] >= 20230101)].copy()
    if len(D) < 300:
        print("  되팔기 간극: 사례 부족"); return
    D["gap"] = D["resale"] / D["est_rule"] - 1
    D["gap_old"] = D["resale"] / D["est"] - 1
    D["gap_mkt"] = D["resale"] / (D["est_rule"] * D["mkt"].clip(0.8, 1.25).fillna(1.0)) - 1
    D["cls"] = D["region"].map(lambda r: "서울" if str(r).startswith("서울") else ("경기·인천" if str(r)[:2] in ("경기", "인천") else "지방"))
    D["hold"] = pd.cut(D["resale_m"], [0, 3, 6, 9, 12], labels=["3개월 이내", "3~6개월", "6~9개월", "9~12개월"])
    D["nb"] = D["n12"].map(lambda n: "1년 거래 0~2건" if n <= 2 else ("3~5건" if n <= 5 else ("6~11건" if n <= 11 else "12건+")))
    def st(G):
        g = G["gap"]
        return {"n": int(len(G)), "중앙": round(float(g.median()) * 100, 1), "보통오차": round(float(g.abs().median()) * 100, 1), "하방10": round(float(g.quantile(.1)) * 100, 1), "하방25": round(float(g.quantile(.25)) * 100, 1),
                "상방75": round(float(g.quantile(.75)) * 100, 1), "10넘게낮음": round(float((g < -0.10).mean()) * 100, 1), "시장변화중앙": round(float((G["mkt"].clip(0.8, 1.25).fillna(1.0) - 1).median()) * 100, 1), "시장뺀중앙": round(float(G["gap_mkt"].median()) * 100, 1)}
    out = {"generatedAt": now, "n": int(len(D)), "from": 20230101, "전체": st(D), "예전시세기준_전체": {"중앙": round(float(D["gap_old"].median()) * 100, 1), "보통오차": round(float(D["gap_old"].abs().median()) * 100, 1)}}
    for key, col in (("지역", "cls"), ("보유기간", "hold"), ("거래수", "nb")):
        out[key] = {str(k): st(G) for k, G in D.groupby(col, observed=True) if len(G) >= 40}
    try:
        import accuracy_ledger as _led
        for nm, col, lb in (("sise", "gap_old", "시세(같은 단지 40% 지점) vs 되판 가격"), ("sale_resold", "gap", "예상매도가 vs 되판 가격")):
            g = D[col].dropna()
            _led.record(cyc, nm, {"n": int(len(g)), "err": round(float(g.abs().median()) * 100, 2), "bias": round(float(g.median()) * 100, 2),
                                  "hi10": round(float((g < -0.10).mean()) * 100, 1), "hit10": round(float((g.abs() <= 0.10).mean()) * 100, 1)}, lb)
    except Exception as e:
        print("  원장 기록 건너뜀(시세·예상매도가):", e)
    out["지역×보유기간"] = {f"{k[0]}|{k[1]}": st(G) for k, G in D.groupby(["cls", "hold"], observed=True) if len(G) >= 60}
    print("  되팔기 간극:", json.dumps({k: out[k] for k in ("n", "전체", "예전시세기준_전체", "지역", "보유기간", "거래수")}, ensure_ascii=False))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("### 예상매도가 vs 실제 되판 가격\n```json\n" + json.dumps(out, ensure_ascii=False, indent=1) + "\n```\n")
    cyc.upsert_rows([{"id": "signal|__resale_gap__", "payload": cyc.clean_json(out), "fetched_at": now}])


def jibang_scorecard(te, p, R0, now):
    """2026-11-05 지방 아파트 성적표(사용자: 지방 아파트 입찰이 내 조건에 가장 적합 - 예상낙찰가·추천입찰가·예상매도가 정확도가 가장 중요)
    대상: 비규제 지방(서울·경기·인천 제외, 토지거래허가구역 시군구 제외) - 광역시/시·군을 나눠 표시. 학습에 안 쓴 최근 12개월(te)과 낙찰 후 사례로 채점. 구간 = 6개월 같은 평형 거래 수(없으면 1년), 모든 지표에 신뢰 범위(95%)
    ① 예상낙찰가 ② 추천입찰가: (a)앱이 입찰 전 저장한 추천가가 있는 사건 (b)저장분이 없는 과거는 '기대수익 최대' 규칙(앱과 같은 원리)으로 다시 계산해 채점, 실제 되판/시장 가격으로 비용 뺀 순이익
    ③ 예상매도가: 입찰 30일 전 시세(est_rule_f) vs (a)되판 가격(동·층 확인) (b)낙찰 뒤 6개월 안 같은 단지·평형 시장 실거래 중위값"""
    rng_ = np.random.default_rng(5)
    isjb = lambda rg: not (str(rg).startswith("서울") or str(rg)[:2] in ("경기", "인천"))
    zones = set()
    try:
        _pz = requests.get(f"{SITE_URL}/api/data-coverage?mode=permit", timeout=120).json()
        zones = {region_norm(v[3]) for v in (_pz.get("flagged") or {}).values() if len(v) > 3 and v[3]}; zones.discard(None)
    except Exception as e:
        print("  허가구역 목록 불러오기 실패(구분 없이 진행):", e)
    METRO = ("부산", "대구", "광주", "대전", "울산", "세종")
    sub = lambda rg: "광역시" if str(rg)[:2] in METRO else "시·군"
    use_n6 = "n6" in R0.columns and R0["n6"].notna().mean() >= 0.5
    def bins_for(df):
        out = [("전체", np.ones(len(df), bool))]
        if use_n6 and "n6" in df.columns:
            n = df["n6"].fillna(-1).values
            out += [("6개월 같은 평형 0건", n == 0), ("1~2건", (n >= 1) & (n <= 2)), ("3건 이상", n >= 3)]
        else:
            n = df["n12"].fillna(-1).values
            out += [("1년 같은 평형 0~2건", (n >= 0) & (n <= 2)), ("3~5건", (n >= 3) & (n <= 5)), ("6~11건", (n >= 6) & (n <= 11)), ("12건 이상", n >= 12)]
        return out
    def ci_med(x, f=np.median):
        x = np.asarray(x, float)
        if len(x) < 10: return None
        bs = [f(x[rng_.integers(0, len(x), len(x))]) for _ in range(300)]
        return [round(float(np.quantile(bs, .025)) * 100, 1), round(float(np.quantile(bs, .975)) * 100, 1)]
    def ci_prop(k, n):
        if n == 0: return None
        ph = k / n; z = 1.96; den = 1 + z * z / n; c = (ph + z * z / (2 * n)) / den; h = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
        return [round(float(c - h) * 100, 1), round(float(c + h) * 100, 1)]
    def prop(mask):
        mask = np.asarray(mask, bool); n = len(mask); k = int(mask.sum())
        return {"%": round(k / n * 100, 1) if n else None, "범위": ci_prop(k, n)}
    res = {"generatedAt": now, "기준": "비규제 지방 아파트(서울·경기·인천·토지거래허가구역 제외), 오차 = (예상−실제)/실제, 범위 = 95% 신뢰 범위", "구간기준": "6개월 같은 평형 거래 수" if use_n6 else "1년 같은 평형 거래 수(6개월 값은 다음 구동부터)", "허가구역시군구수": len(zones)}
    def split(df, fn):
        out = {}
        views = [("전체", np.ones(len(df), bool))] + [(k, (df["region"].map(sub) == k).values) for k in ("광역시", "시·군")]
        for vn, vm in views:
            d1 = df[vm]
            for bn, bm in bins_for(d1):
                if bm.sum() >= 30: out[f"{vn}|{bn}"] = fn(d1[bm])
        return out
    # ── ① 예상낙찰가
    T = te.copy(); T["pred"] = np.exp(p) * T["est"].values
    T = T[T["region"].map(isjb) & ~T["region"].isin(zones)]
    def st_win(G):
        e = ((G["pred"] - G["actual"]) / G["actual"]).values; a = np.abs(e)
        return {"n": int(len(G)), "보통오차": round(float(np.median(a)) * 100, 1), "오차범위": ci_med(a), "방향": round(float(np.median(e)) * 100, 1), "10안": prop(a <= .10), "10넘게높음": prop(e > .10), "10넘게낮음": prop(e < -.10), "p90": round(float(np.quantile(a, .9)) * 100, 1)}
    res["예상낙찰가"] = split(T, st_win)
    # ── ② 추천입찰가
    # (b) 기대수익 최대 규칙 재계산: 시세 S, 예상 낙찰가 분포 = 모델 예상 × 잔차 분위(반대편 절반에서 추정 - 교차)
    T = T.sort_values("sale"); half = len(T) // 2
    T["resid"] = np.log(T["actual"].values / T["pred"].values)
    sell = np.where(T["resale"].notna() & (T["resale_conf"] == "dong") & T["resale_m"].between(0.45, 12), T["resale"], np.where(T["mkt_after"].notna(), T["mkt_after"], np.nan)) if "mkt_after" in T.columns else np.where(T["resale"].notna() & (T["resale_conf"] == "dong"), T["resale"], np.nan)
    T["sell"] = sell
    MIN_M = 1000
    def replay(G, qs):
        """각 사건: 후보 입찰가 격자에서 기대수익 P(낙찰)·(S−1.05b−400) 최대, 최소순익 1천만 이상만"""
        recs = []
        for pr, S in zip(G["pred"].values, G["est"].values):
            bmax = (S - FIXED_COST - MIN_M) / COST_RATIO
            if bmax <= 0: recs.append(np.nan); continue
            bs = np.linspace(bmax * 0.6, bmax, 41)
            pw = np.searchsorted(qs[0], np.log(bs / pr), side="right") / len(qs[0])      # P(실제 ≤ b) = P(잔차 ≤ log(b/예상))
            ev = pw * (S - COST_RATIO * bs - FIXED_COST)
            recs.append(float(bs[int(np.argmax(ev))]) if ev.max() > 0 else np.nan)
        return np.array(recs)
    try:
        parts = []
        for tr_, ts_ in ((T.iloc[:half], T.iloc[half:]), (T.iloc[half:], T.iloc[:half])):
            if len(tr_) < 50 or len(ts_) < 30: continue
            ts_ = ts_.copy(); ts_["recR"] = replay(ts_, (np.sort(tr_["resid"].values),)); parts.append(ts_)
        RP = pd.concat(parts) if parts else T.iloc[0:0].assign(recR=np.nan)
        RP = RP[RP["recR"].notna()]
    except Exception as e:
        print("  추천가 재계산 건너뜀:", e); RP = T.iloc[0:0].assign(recR=np.nan)
    def st_rec(G):
        won = (G["actual"].values <= G["recR"].values); out = {"n": int(len(G)), "추천가이하낙찰": prop(won), "실제÷추천가중앙": round(float(np.median(G["actual"].values / G["recR"].values)), 3), "10넘게비쌈": prop(G["actual"].values / G["recR"].values > 1.10)}
        W = G[won & G["sell"].notna().values]
        if len(W) >= 15:
            pf = (W["sell"].values - COST_RATIO * W["actual"].values - FIXED_COST)
            out["낙찰시_순이익(만원)"] = {"n": int(len(W)), "중앙": round(float(np.median(pf))), "범위": [round(float(np.quantile([np.median(pf[rng_.integers(0, len(pf), len(pf))]) for _ in range(300)], q))) for q in (.025, .975)], "손실비율": prop(pf < 0), "1천만미만": prop(pf < 1000)}
        return out
    res["추천입찰가_재계산"] = split(RP, st_rec) if len(RP) else {}
    # (a) 앱이 입찰 전 저장한 추천가
    try:
        au = requests.get(f"{SITE_URL}/api/auction", timeout=180).json()
        amap = {(norm_case(x.get("caseNo")), region_norm(x.get("addr"))): x for x in au if isinstance(x, dict) and x.get("caseNo") and not x.get("isBacktest")}
        rows = []
        for r in T.itertuples():
            x = amap.get((norm_case(r.caseNo), r.region))
            if not x or not amt_ok(x, getattr(r, "appraisal", None)): continue
            sn = pick_snap(x, r.sale)
            if sn and sn.get("recBid"): rows.append({"actual": float(r.actual), "rec": float(sn["recBid"]), "minb": float(r.minbid), "snapMin": sn.get("minBid"), "win": sn.get("win"), "go": sn.get("go"), "at": sn.get("at"), "sell": getattr(r, "sell", np.nan)})
        X = pd.DataFrame(rows)
        sv = {"n": int(len(X))}
        if len(X) >= 15:
            X["ok"] = X["snapMin"].notna() & ((X["snapMin"].astype(float) - X["minb"]).abs() / X["minb"] <= 0.02)   # 저장한 최저가가 실제와 2% 안
            X["feas"] = X["rec"] >= X["minb"]                                                                      # 추천가가 최저가 이상(입찰 가능한 값)
            def sv_st(G):
                if len(G) < 10: return {"n": int(len(G))}
                rr = G["actual"].values / G["rec"].values; o = {"n": int(len(G)), "추천가이하낙찰": prop(rr <= 1), "실제÷추천가중앙": round(float(np.median(rr)), 3), "실제÷추천가_25~75": [round(float(np.quantile(rr, .25)), 3), round(float(np.quantile(rr, .75)), 3)], "추천가÷저장예상낙찰가중앙": None}
                W = G[G["win"].notna() & (G["win"] > 0)]
                if len(W) >= 10:
                    o["추천가÷저장예상낙찰가중앙"] = round(float(np.median(W["rec"].values / W["win"].values)), 3); o["저장예상낙찰가_방향"] = round(float(np.median(W["win"].values / W["actual"].values - 1)) * 100, 1)
                return o
            sv["전체"] = sv_st(X); sv["추천가<최저가(입찰 불가한 값) 비율%"] = round(float((~X["feas"]).mean()) * 100, 1)
            sv["금액일치"] = sv_st(X[X["ok"]]); sv["금액일치·입찰가능"] = sv_st(X[X["ok"] & X["feas"]]); sv["입찰후보(go)만"] = sv_st(X[X["ok"] & X["feas"] & (X["go"] == True)])
            sv["저장 기간"] = [str(X["at"].min()), str(X["at"].max())]
        else:
            sv["note"] = "저장분이 15건 미만"
        res["추천입찰가_저장분"] = sv
    except Exception as e:
        print("  저장 추천가 채점 건너뜀:", e)
    # ── ③ 예상매도가
    col = "est_rule_f" if "est_rule_f" in R0.columns else "est_rule"
    D0 = R0[R0["region"].map(isjb) & ~R0["region"].isin(zones) & R0[col].notna() & (R0[col] > 0) & (R0["sale"] >= 20230101)].copy()
    def st_sale(df, tgt):
        def f(G):
            g = (G[tgt] / G[col] - 1).values; a = np.abs(g)
            return {"n": int(len(G)), "보통오차": round(float(np.median(a)) * 100, 1), "오차범위": ci_med(a), "방향(실제÷예상-1)": round(float(np.median(g)) * 100, 1), "10안": prop(a <= .10), "10넘게낮게팔림": prop(g < -.10), "하방10분위": round(float(np.quantile(g, .1)) * 100, 1)}
        return split(df, f)
    Dr = D0[(D0["resale_conf"] == "dong") & D0["resale"].notna() & D0["resale_m"].between(0.45, 12)]
    res["예상매도가_vs_되판가"] = st_sale(Dr, "resale")
    if "mkt_after" in D0.columns:
        Dm = D0[D0["mkt_after"].notna()]; res["예상매도가_vs_시장실거래(낙찰뒤6개월)"] = st_sale(Dm, "mkt_after")
    for lab, m in (("3개월 이내", Dr["resale_m"] <= 3), ("3~6개월", (Dr["resale_m"] > 3) & (Dr["resale_m"] <= 6)), ("6~12개월", Dr["resale_m"] > 6)):
        if m.sum() >= 30:
            g = (Dr[m]["resale"] / Dr[m][col] - 1).values; res.setdefault("되판가_보유기간별", {})[lab] = {"n": int(m.sum()), "보통오차": round(float(np.median(np.abs(g))) * 100, 1), "방향": round(float(np.median(g)) * 100, 1)}
    print("  🧾 지방 성적표:", json.dumps(res, ensure_ascii=False))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("### 지방 아파트 성적표\n```json\n" + json.dumps(res, ensure_ascii=False, indent=1) + "\n```\n")
    cyc.upsert_rows([{"id": "signal|__jibang_score__", "payload": cyc.clean_json(res), "fetched_at": now}])


def thin_correction(R0, now):
    """2026-11-05 시세 근거가 얇을 때(6개월 같은 평형 0~2건) 지방 예상매도가의 체계적 과대평가를 어떻게 고치는 게 최선인지 찾는 실험(사용자: 한 가지 규칙을 모든 곳에 고정할 수 없음).
    목표 = log(낙찰 뒤 6개월 같은 단지·평형 시장 실거래 중위값 ÷ 입찰 30일 전 시세 est_rule_f). 후보: 보정 없음 / 상수 / 근거 형태별 표(가장 최근 거래 나이·36개월 거래 수·다른 평형 유무·광역시/시군) / 특징 회귀(릿지).
    시간순 검증(최근 12개월 따로), 되판 가격으로 교차 확인. 결과를 signal|__thin_est__에 저장(앱 적용은 승인 뒤)"""
    rng_ = np.random.default_rng(9)
    isjb = lambda rg: not (str(rg).startswith("서울") or str(rg)[:2] in ("경기", "인천"))
    zones = set()
    try:
        _pz = requests.get(f"{SITE_URL}/api/data-coverage?mode=permit", timeout=120).json()
        zones = {region_norm(v[3]) for v in (_pz.get("flagged") or {}).values() if len(v) > 3 and v[3]}; zones.discard(None)
    except Exception as e:
        print("  허가구역 목록 실패(구분 없이):", e)
    need = ["n6", "mkt_after", "t_n36", "t_last_age", "t_n_other12"]
    if any(c_ not in R0.columns for c_ in need):
        print("  얇은 근거 보정 실험: 필요한 열 없음, 건너뜀"); return
    col = "est_rule_f" if "est_rule_f" in R0.columns else "est_rule"
    now_ymd = int((datetime.strptime(now[:10], "%Y-%m-%d") - timedelta(days=190)).strftime("%Y%m%d"))
    D = R0[R0["region"].map(isjb) & ~R0["region"].isin(zones) & R0[col].notna() & (R0[col] > 0) & R0["n6"].notna() & (R0["n6"] <= 2) & (R0["sale"] >= 20230101) & (R0["sale"] <= now_ymd)].copy()
    D["y"] = np.log(D["mkt_after"] / D[col]); D["yr"] = np.where(D["resale"].notna() & (D["resale_conf"] == "dong") & D["resale_m"].between(0.45, 12), np.log(D["resale"] / D[col]), np.nan)
    D["sub"] = D["region"].map(lambda r: 1.0 if str(r)[:2] in ("부산", "대구", "광주", "대전", "울산", "세종") else 0.0)
    D["la"] = D["t_last_age"].fillna(40.0); D["n36"] = D["t_n36"].fillna(0)
    D["last_gap"] = np.where(D["t_last_price"].notna(), np.log(D["t_last_price"].fillna(1) / D[col]), 0.0)
    D["disp"] = D["t_disp"].fillna(0.0); D["oth"] = (D["t_n_other12"].fillna(0) > 0).astype(float); D["lest"] = np.log(D[col])
    D["flow"] = D["est_flow_rate"].fillna(0.0) if "est_flow_rate" in D.columns else 0.0
    D["n6g"] = D["n6"].astype(int)
    E = D[D["y"].notna() & np.isfinite(D["y"])].copy(); E = E[E["y"].between(-0.6, 0.6)]
    if len(E) < 400:
        print(f"  얇은 근거 보정 실험: 표본 부족({len(E)}), 건너뜀"); return
    cutd = int(E["sale"].quantile(0.75)); TR, TE = E[E["sale"] < cutd], E[E["sale"] >= cutd]
    def bucket(df):
        la = np.where(df["la"] <= 12, "A≤12개월", np.where(df["la"] <= 24, "B≤24개월", "C24개월+"))
        n3 = np.where(df["n36"] == 0, "0건", np.where(df["n36"] <= 2, "1~2건", "3건+"))
        return pd.Series([f"{a}|{b}|{'다른평형있음' if o else '없음'}" for a, b, o in zip(la, n3, df["oth"].values)], index=df.index)
    def bucket2(df):   # 더 단순한 표(칸이 적어 안정적): 최근 거래 나이 × 6개월 건수
        la = np.where(df["la"] <= 12, "A≤12개월", np.where(df["la"] <= 24, "B≤24개월", "C24개월+"))
        return pd.Series([f"{a}|6개월{int(n)}건" for a, n in zip(la, df["n6g"].values)], index=df.index)
    def fit_table(T, bf, k=30):
        glob = float(T["y"].median()); b = bf(T); out = {}
        for key, G in T.groupby(b): out[key] = glob + (float(G["y"].median()) - glob) * len(G) / (len(G) + k)
        return glob, out
    def apply_table(df, glob, tab, bf): return bf(df).map(lambda k_: tab.get(k_, glob)).values
    feats = ["la", "n36", "oth", "disp", "last_gap", "sub", "lest", "flow", "n6g"]
    def fit_ridge(T, lam=30.0):
        X = T[feats].values.astype(float); mu, sd = X.mean(0), X.std(0) + 1e-9; Z = (X - mu) / sd; y = T["y"].values; ym = y.mean()
        w = np.linalg.solve(Z.T @ Z + lam * np.eye(Z.shape[1]), Z.T @ (y - ym)); return mu, sd, w, ym
    def pred_ridge(m, df): mu, sd, w, ym = m; return ym + ((df[feats].values.astype(float) - mu) / sd) @ w
    def metrics(y, pr, sub=None):
        e = np.exp(y - pr) - 1 if False else (np.exp(y) / np.exp(pr) - 1)   # 보정 후 (실제/보정된 예상 - 1)
        a = np.abs(e)
        bs = [np.median(a[rng_.integers(0, len(a), len(a))]) for _ in range(200)]
        return {"n": int(len(y)), "보통오차": round(float(np.median(a)) * 100, 1), "오차범위": [round(float(np.quantile(bs, .025)) * 100, 1), round(float(np.quantile(bs, .975)) * 100, 1)], "방향": round(float(np.median(e)) * 100, 1),
                "10안": round(float((a <= .10).mean()) * 100, 1), "10넘게낮게팔림": round(float((e < -.10).mean()) * 100, 1), "10넘게높게팔림": round(float((e > .10).mean()) * 100, 1)}
    cands = {}
    cands["보정 없음"] = (lambda df: np.zeros(len(df)), None)
    g0 = float(TR["y"].median()); cands["상수(한 가지 규칙)"] = (lambda df, g0=g0: np.full(len(df), g0), {"값%": round(g0 * 100, 1)})
    gl, tb = fit_table(TR, bucket2); cands["표: 최근 거래 나이×6개월 건수"] = (lambda df, gl=gl, tb=tb: apply_table(df, gl, tb, bucket2), {"기본%": round(gl * 100, 1), "칸%": {k_: round(v * 100, 1) for k_, v in tb.items()}})
    gl3, tb3 = fit_table(TR, bucket); cands["표: 나이×36개월 건수×다른 평형"] = (lambda df, gl=gl3, tb=tb3: apply_table(df, gl, tb, bucket), {"기본%": round(gl3 * 100, 1), "칸%": {k_: round(v * 100, 1) for k_, v in tb3.items()}})
    mr = fit_ridge(TR); cands["특징 회귀(릿지)"] = (lambda df, mr=mr: pred_ridge(mr, df), {"특징": feats, "가중": [round(float(x), 4) for x in mr[2]]})
    res = {"generatedAt": now, "기준": "비규제 지방, 6개월 같은 평형 0~2건, 목표 = 낙찰 뒤 6개월 시장 실거래 중위값 ÷ 시세 - 1(오차 = 실제÷보정된 예상 - 1)", "학습": {"n": int(len(TR)), "까지": cutd}, "검증": {"n": int(len(TE)), "부터": cutd}, "후보": {}}
    for nm, (fn, info) in cands.items():
        pr = fn(TE); r = {"전체": metrics(TE["y"].values, pr), "정보": info}
        for gname, mk in (("6개월0건", TE["n6g"] == 0), ("6개월1~2건", TE["n6g"] >= 1), ("광역시", TE["sub"] == 1), ("시·군", TE["sub"] == 0)):
            if mk.sum() >= 40: r[gname] = metrics(TE["y"].values[mk.values], pr[mk.values])
        TY = TE[TE["yr"].notna()]
        if len(TY) >= 40: r["되판가로 교차확인"] = metrics(TY["yr"].values, fn(TY))
        res["후보"][nm] = r
    try:  # 🧪 시세 후보 시험(2026-11-06): 가격을 옮기는 대신 근거를 보강한 시세로 바꿔 채점 - 같은 학습/검증 분할, 후보가 비는 사건은 기존 시세 그대로
        vres = {"설명": "tv_prem=단지 프리미엄×지금 주변 시세, tv_flow=흐름으로 옮긴 오래된 거래, tv_idx=시군구 지수로 옮긴 거래, tv_oth=다른 평형 환산. 섞기 비중은 학습 구간에서 6개월 건수별로 고름(0~1, 0.1 간격)", "후보": {}}
        base_ = E[col].values.astype(float)
        def lv(nm):
            if nm not in E.columns: return None
            v = pd.to_numeric(E[nm], errors="coerce").values.astype(float)
            return np.where(np.isfinite(v) & (v > 0) & (np.abs(np.log(np.where(v > 0, v, 1) / base_)) < 0.5), np.log(np.where(v > 0, v, 1) / base_), np.nan)   # 기존 시세와 ±50% 넘게 다르면 이상값으로 보고 제외
        shifts = {nm: lv(nm) for nm in ("tv_prem", "tv_flow", "tv_idx", "tv_oth")}
        shifts = {k_: v_ for k_, v_ in shifts.items() if v_ is not None}
        istr = (E["sale"] < cutd).values; iste = ~istr; n6a = E["n6g"].values
        def shift_for(arr, wmap):
            out = np.zeros(len(E))
            for nb in (0, 1):   # 6개월 0건 / 1~2건
                m = (n6a == 0) if nb == 0 else (n6a >= 1); wgt = wmap[nb]; ok = m & np.isfinite(arr); out[ok] = wgt * arr[ok]
            return out
        def best_w(arr):
            wm = {}
            for nb in (0, 1):
                m = istr & np.isfinite(arr) & ((n6a == 0) if nb == 0 else (n6a >= 1)); best = (9, 0.0)
                if m.sum() < 40: wm[nb] = 0.0; continue
                for wv in np.arange(0, 1.01, 0.1):
                    e_ = np.median(np.abs(np.exp(E["y"].values[m] - wv * arr[m]) - 1))
                    if e_ < best[0] - 1e-9: best = (e_, float(wv))
                wm[nb] = best[1]
            return wm
        allm = np.nanmean(np.vstack([np.where(np.isfinite(v_), v_, 0.0) for v_ in shifts.values()]), axis=0) if shifts else None
        def mt(sh):
            te_ = E.iloc[np.where(iste)[0]]; r = {"전체": metrics(te_["y"].values, sh[iste])}
            for gname, mk in (("6개월0건", te_["n6g"] == 0), ("6개월1~2건", te_["n6g"] >= 1), ("광역시", te_["sub"] == 1), ("시·군", te_["sub"] == 0)):
                if mk.sum() >= 40: r[gname] = metrics(te_["y"].values[mk.values], sh[iste][mk.values])
            return r
        vres["후보"]["기존 시세(보정 없음)"] = mt(np.zeros(len(E)))
        for nm, arr in shifts.items():
            cover = float(np.isfinite(arr[iste]).mean()) * 100; wm = best_w(arr)
            r_full = mt(shift_for(arr, {0: 1.0, 1: 1.0})); r_mix = mt(shift_for(arr, wm))
            vres["후보"][nm + " 그대로"] = {**r_full, "검증 중 후보 있는 비율%": round(cover, 1)}
            vres["후보"][nm + " 섞기"] = {**r_mix, "섞는 비중(0건,1~2건)": [wm[0], wm[1]], "검증 중 후보 있는 비율%": round(cover, 1)}
        if allm is not None:
            vres["후보"]["후보 평균(기존 포함 아님)"] = mt(allm)
            wmA = best_w(allm); vres["후보"]["후보 평균 섞기"] = {**mt(shift_for(allm, wmA)), "섞는 비중(0건,1~2건)": [wmA[0], wmA[1]]}
        # 좋은 후보에 특징 회귀(릿지)를 더 얹으면
        try:
            TRm = E[istr].copy(); best_nm = min((k_ for k_ in vres["후보"] if k_.endswith("섞기")), key=lambda k_: vres["후보"][k_]["전체"]["보통오차"])
            vres["최선(시세 후보)"] = best_nm
        except Exception: pass
        vres["표본"] = {"학습": int(istr.sum()), "검증": int(iste.sum())}
        print("  🧪 시세 후보 시험:", json.dumps({k_: v_["전체"] for k_, v_ in vres["후보"].items()}, ensure_ascii=False))
        res["시세후보시험"] = vres
    except Exception as e:
        print("  시세 후보 시험 실패:", e)
    # 🔬 편향 원인 진단(2026-11-06): 근거가 얇을 때 예상이 실제보다 높게 나오는 이유 - 특징별로 쪼개 편향(중앙값 %)을 비교. 원인이 한 곳에 몰려 있으면 그곳이 원인
    try:
        def _b(m): 
            x = E.loc[m, "y"].values
            return {"n": int(len(x)), "편향%": round(float(np.median(x)) * 100, 1), "평균%": round(float(np.mean(x)) * 100, 1), "하락비율%": round(float((x < -0.03).mean()) * 100, 0)} if len(x) >= 30 else None
        dg = {"전체": _b(E["y"].notna())}
        dg["근거건수"] = {str(k_): _b(E["n6g"] == k_) for k_ in (0, 1, 2)}
        dg["가장 최근 거래 나이(개월)"] = {n_: _b(m_) for n_, m_ in (("3 이하", E["la"] <= 3), ("3~6", E["la"].between(3, 6, inclusive="right")), ("6~12", E["la"].between(6, 12, inclusive="right")), ("12~24", E["la"].between(12, 24, inclusive="right")), ("24 초과·없음", E["la"] > 24))}
        dg["36개월 같은 평형 거래수"] = {n_: _b(m_) for n_, m_ in (("0", E["n36"] == 0), ("1~2", E["n36"].between(1, 2)), ("3~5", E["n36"].between(3, 5)), ("6+", E["n36"] >= 6))}
        dg["낙찰 뒤 6개월 시장 거래수"] = {n_: _b(m_) for n_, m_ in (("1건", E["mkt_after_n"] == 1), ("2~3건", E["mkt_after_n"].between(2, 3)), ("4건+", E["mkt_after_n"] >= 4))} if "mkt_after_n" in E.columns else None
        dg["마지막 거래가 대비 시세(위로 쏠림)"] = {n_: _b(m_) for n_, m_ in (("시세가 마지막 거래보다 5%+ 낮음", E["last_gap"] < -0.05), ("±5%", E["last_gap"].between(-0.05, 0.05)), ("시세가 마지막 거래보다 5%+ 높음", E["last_gap"] > 0.05))}
        dg["다른 평형 거래 있음"] = {"있음": _b(E["oth"] > 0), "없음": _b(E["oth"] == 0)}
        dg["광역시/시군"] = {"광역시": _b(E["sub"] == 1), "시군": _b(E["sub"] == 0)}
        dg["낙찰 연도"] = {str(y_): _b(E["sale"] // 10000 == y_) for y_ in sorted(E["sale"].astype(int).floordiv(10000).unique())}
        dg["낙찰 월"] = {f"{m_}월": _b((E["sale"] // 100 % 100) == m_) for m_ in range(1, 13)}
        if "floor" in E.columns: dg["층"] = {n_: _b(m_) for n_, m_ in (("1~2층", E["floor"] <= 2), ("3~5층", E["floor"].between(3, 5)), ("6층+", E["floor"] >= 6))}
        if "flow" in E.columns: dg["지역 가격 흐름(연율)"] = {n_: _b(m_) for n_, m_ in (("하락 -3%↓", E["flow"] < -0.03), ("보합", E["flow"].between(-0.03, 0.03)), ("상승 +3%↑", E["flow"] > 0.03))}
        # 같은 지역의 근거 충분(5건+) 물건 편향 - 비교 기준
        isjb2 = R0["region"].map(isjb) & ~R0["region"].isin(zones) & R0[col].notna() & (R0[col] > 0) & R0["mkt_after"].notna() & (R0["sale"] >= 20230101) & (R0["sale"] <= now_ymd)
        for n_, m_ in (("5건+", R0["n6"] >= 5), ("3~4건", R0["n6"].between(3, 4))):
            xx = np.log(R0.loc[isjb2 & m_, "mkt_after"] / R0.loc[isjb2 & m_, col]); xx = xx[np.isfinite(xx) & xx.between(-0.6, 0.6)]
            dg.setdefault("비교: 같은 지역 근거 충분", {})[n_] = {"n": int(len(xx)), "편향%": round(float(np.median(xx)) * 100, 1)}
        res["편향진단"] = dg
        print("  🔬 편향 진단:", json.dumps(dg, ensure_ascii=False))
    except Exception as e:
        import traceback; traceback.print_exc(); print("  편향 진단 실패:", e)
    best = min(res["후보"].items(), key=lambda kv: (kv[1]["전체"]["보통오차"], kv[1]["전체"]["10넘게낮게팔림"]))
    res["최선"] = best[0]
    print("  🩹 얇은 근거 보정 실험:", json.dumps({k: {"전체": v["전체"], **({"6개월0건": v["6개월0건"]} if "6개월0건" in v else {})} for k, v in res["후보"].items()}, ensure_ascii=False), "→ 최선:", best[0])
    # 최종 학습(전체 표본)으로 표·상수 저장(앱 적용 시 사용)
    glF, tbF = fit_table(E, bucket2); res["표_전체학습"] = {"기본%": round(glF * 100, 1), "칸%": {k_: round(v * 100, 1) for k_, v in tbF.items()}, "표본": int(len(E))}
    gl3F, tb3F = fit_table(E, bucket); res["표2_전체학습"] = {"기본%": round(gl3F * 100, 1), "칸%": {k_: round(v * 100, 1) for k_, v in tb3F.items()}}
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("### 얇은 근거 보정 실험\n```json\n" + json.dumps(res, ensure_ascii=False, indent=1) + "\n```\n")
    cyc.upsert_rows([{"id": "signal|__thin_est__", "payload": cyc.clean_json(res), "fetched_at": now}])


def risk_table(R0, now):
    """2026-11-06 근거 두께별 '낙찰 뒤 실제 시장가 ÷ 입찰 30일 전 시세 - 1' 분포(하방 25%·중앙·하방 10%) - 추천가의 위험 여유가 고정 숫자 대신 최근 실측을 따르게 함.
    정답 = 낙찰 뒤 6개월 같은 단지·평형 시장 실거래 중위값. 낙찰 후 6개월이 지난 사건 중 최근 12개월분(그 뒤는 아직 정답이 없음). 칸 = 지역등급(서울/경기·인천/지방) × 근거(6개월 같은 평형 0건·가장 최근 거래 12개월 이내/초과, 1~2건, 3~4건, 5건+).
    칸 표본이 40건 미만이면 같은 근거의 전체 지역 칸으로 대체(표시 n 포함). 매주 모델 갱신 때 다시 계산됨"""
    need = ["n6", "mkt_after", "t_last_age"]
    if any(c_ not in R0.columns for c_ in need): return None
    col = "est_rule_f" if "est_rule_f" in R0.columns else "est_rule"
    hi = int((datetime.strptime(now[:10], "%Y-%m-%d") - timedelta(days=190)).strftime("%Y%m%d"))
    lo = int((datetime.strptime(now[:10], "%Y-%m-%d") - timedelta(days=190 + 365)).strftime("%Y%m%d"))
    D = R0[R0[col].notna() & (R0[col] > 0) & R0["mkt_after"].notna() & (R0["mkt_after"] > 0) & R0["n6"].notna() & (R0["sale"] >= lo) & (R0["sale"] <= hi)].copy()
    D["e"] = D["mkt_after"] / D[col] - 1; D = D[D["e"].between(-0.6, 0.9)]
    cls_f = lambda rg: "서울" if str(rg).startswith("서울") else ("경기·인천" if str(rg)[:2] in ("경기", "인천") else "지방")
    D["cls"] = D["region"].map(cls_f)
    def ev(n6, la):
        if n6 == 0: return "0건·최근" if (pd.notna(la) and la <= 12) else "0건·오래"
        return "1~2건" if n6 <= 2 else ("3~4건" if n6 <= 4 else "5건+")
    D["ev"] = [ev(int(n), la) for n, la in zip(D["n6"], D["t_last_age"])]
    st = lambda x: {"n": int(len(x)), "q10": round(float(np.quantile(x, .10)), 4), "q25": round(float(np.quantile(x, .25)), 4), "q50": round(float(np.quantile(x, .50)), 4)}
    allt = {k_: st(g_["e"].values) for k_, g_ in D.groupby("ev") if len(g_) >= 40}
    tab = {}
    for (cl, e_), g_ in D.groupby(["cls", "ev"]):
        if len(g_) >= 40: tab[f"{cl}|{e_}"] = st(g_["e"].values)
        elif f"{cl}|{e_}" in RISK_BY_TRADES: tab[f"{cl}|{e_}"] = {**RISK_BY_TRADES[f"{cl}|{e_}"], "대체": "실거래 기반"}
        elif e_ in allt: tab[f"{cl}|{e_}"] = {**allt[e_], "대체": "전체 지역"}
    for k_, v_ in RISK_BY_TRADES.items():
        if k_ not in tab: tab[k_] = {**v_, "대체": "실거래 기반"}
    # 흩어짐 칸은 시간순 검증(늦은 절반에서 하방 25% 아래 비율이 25%에 맞는지)이 좋아진 지역등급만 씀 - 2026-11-06 검증: 지방 33→25%로 개선, 서울·경기·인천은 흩어짐 차이가 작거나 개선 없음
    _dk = {k_: v_ for k_, v_ in (RISK_DISP.get("칸") or {}).items() if k_.startswith("지방|")}
    disp_extra = {"분산칸": _dk, "분산경계": {"지방": (RISK_DISP.get("경계") or {}).get("지방")}} if _dk else {}
    out = {**disp_extra, "기간": [lo, hi], "표본": int(len(D)), "칸": tab, "전체칸": allt, "정의": "e = 낙찰 뒤 6개월 시장 실거래 중위 ÷ 시세(est_rule_f) - 1"}
    print("  🧱 근거 두께별 하방 표:", json.dumps({k_: [v_["n"], v_["q25"], v_["q50"]] for k_, v_ in tab.items()}, ensure_ascii=False))
    return out


def winbid_model(R, now):
    # 🆕 시세 새 규칙(est_rule) 적용(2026-11-04, 사용자 결정): 모델이 보는 시세(est)를 새 규칙으로 - 앱도 같은 규칙으로 시세를 계산해야 함(모델 payload의 estRule 표시)
    R0 = R
    R = R0.copy(); R["est_q40"] = R["est"]
    _er = R["est_rule_f"] if "est_rule_f" in R.columns else R["est_rule"]   # 📈 흐름 반영 시세(est_rule_f)를 쓰되, 흐름 반영이 없으면(값 없음) 같은 규칙의 기본 값
    _er = _er.where(_er.notna() & (_er > 0), R["est_rule"])
    R["est"] = _er.where(_er.notna() & (_er > 0))
    D = R[R["est"].notna() & (R["est"] > 0) & R["actual"].notna() & R["minbid"].notna() & (R["minbid"] > 0) & (R["sale"] >= 20200101)].copy()
    D = D[np.log(D["actual"] / D["est"]).between(np.log(0.4), np.log(1.6))]
    if len(D) < 3000:
        print("  예상 낙찰가 모델: 사례 부족, 건너뜀"); return
    last = pd.to_datetime(str(int(D["sale"].max())), format="%Y%m%d")
    cut = int((last - pd.DateOffset(months=12)).strftime("%Y%m%d"))
    tr, te = D[D["sale"] < cut], D[D["sale"] >= cut]
    global WB_FACTORS
    WB_BASE0 = list(WB_FACTORS)
    try:  # 🎛 요인 비중 조정(감정가 없이) - 학습 구간만으로 시간순 검증해 비중·교호항을 고름(최종 검증 구간은 쓰지 않음)
        _tf, tune_info = wb_tune(tr, WB_BASE0, WB_CANDS + WB_CANDS_SERVER)
        tune_info["serverOnlyChosen"] = [f for f in _tf if f[0] in SERVER_ONLY]   # 채택됐을 서버 전용 요인(참고) - 모델에는 넣지 않음
        WB_FACTORS = [tuple(f) for f in _tf if f[0] not in SERVER_ONLY]
        tune_info["factors"] = [[f, k] for f, k in WB_FACTORS]
    except Exception as e:
        print("  요인 비중 조정 건너뜀:", e); tune_info = {"skipped": str(e)}; WB_FACTORS = list(WB_BASE0)
    f_base = [f for f in WB_FACTORS if f[0] != "jb"]; f_jb = f_base + [WB_JB_FACTOR]
    # 🕐 최근 가중(2026-11-04, 사용자 "개선안 적용"): 학습에서 최근 12개월 사례를 3배(원본 + 2번 더)로 셈. 리포트 12주 비교에서 보통 오차 5.49→5.41%(±10% 안 +0.8%p).
    # 같은 학습/검증 분할에서 가중 없는 모델과 비교해 좋아질 때만 씀(아니면 예전 방식 그대로)
    def _recent_w(df, ref_int):
        ref = pd.to_datetime(str(int(ref_int)), format="%Y%m%d"); since = int((ref - pd.DateOffset(months=12)).strftime("%Y%m%d"))
        rec = df[df["sale"] >= since]
        return pd.concat([df, rec, rec])
    trw = _recent_w(tr, cut)
    WB_FACTORS = f_base
    _ea = lambda pp: float(np.median(np.abs(np.exp(pp) * te["est"].values / te["actual"].values - 1)))
    _e_plain, _e_w = _ea(wb_predict(wb_fit(tr), te)), _ea(wb_predict(wb_fit(trw), te))
    use_rw = bool(_e_w < _e_plain - 0.0003)
    print(f"  🕐 최근 가중(최근 12개월 3배) 검증: 보통 오차 {_e_plain * 100:.3f}% → {_e_w * 100:.3f}% →", "사용" if use_rw else "사용 안 함(효과 없음)")
    TRF = trw if use_rw else tr
    # 📏 원칙 적용 비용 확인(2026-11-04): 같은 검증 구간에서 요인을 바꿔 가며 오차 비교 - 실제로 쓰는 모델은 맨 아래(감정가·최저가 없음)
    principle = {}
    try:  # 같은 최종 검증 구간에서 "기본 비중" ↔ "조정한 비중" 비교(기록용)
        _srv = [tuple(f) for f in tune_info.get("serverOnlyChosen", [])]
        _cmp = [("기본 비중", WB_BASE0), ("조정한 비중(사용)", f_base)] + ([("서버 전용 요인 포함(참고·앱 미적용)", f_base + _srv)] if _srv else [])
        for nm, fl in _cmp:
            WB_FACTORS = fl; _pp = wb_predict(wb_fit(TRF), te); _e = np.exp(_pp) * te["est"].values / te["actual"].values - 1
            principle[nm] = {"medAbsErrPct": round(float(np.median(np.abs(_e))) * 100, 2), "within10Pct": round(float((np.abs(_e) <= 0.10).mean()) * 100, 1), "biasPct": round(float(np.median(-_e / (1 + _e))) * 100, 2), "n": int(len(te))}
        print("  📏 비중 조정 효과(최종 검증 구간):", json.dumps(principle, ensure_ascii=False))
    except Exception as e:
        print("  비중 조정 효과 계산 건너뜀:", e)
    flow_diag = {}
    try:  # 🌊 흐름 요인 신호 확인: 최종 모델(흐름 없음)의 잔차(실제÷예상, 로그)를 흐름 상태별로 묶어 중앙값을 봄 - 상태마다 잔차가 일정하게 쏠리면 그 요인에 신호가 있다는 뜻
        WB_FACTORS = f_base; _m = wb_fit(TRF); _res = np.log(te["actual"].values / te["est"].values) - wb_predict(_m, te); _Xt = wb_features(te)
        for fn_ in ("flowM", "flowL", "flowS", "flowR2", "flowT", "afC", "afR1", "afR2", "afR3", "afD", "afS", "afT2", "afTC"):
            if fn_ not in _Xt.columns: continue
            _df = pd.DataFrame({"k": _Xt[fn_].values, "r": _res}); gg = _df.groupby("k")["r"].agg(["median", "count"]); gg = gg[(gg["count"] >= 40) & (gg.index != "-")]
            if len(gg):
                flow_diag[fn_] = {"채워진 비율%": round(float((_Xt[fn_].values != "-").mean()) * 100, 1), "상태별(40건+)": {k_: {"n": int(v_["count"]), "잔차중앙%": round(float(v_["median"]) * 100, 1)} for k_, v_ in gg.sort_values("median").iterrows()}}
        print("  🌊 흐름 상태별 잔차(최종 검증 구간):", json.dumps({k: {"채움": v["채워진 비율%"], "최대쏠림%": max(abs(x["잔차중앙%"]) for x in v["상태별(40건+)"].values())} for k, v in flow_diag.items()}, ensure_ascii=False))
    except Exception as e:
        print("  흐름 신호 확인 건너뜀:", e)
    WB_FACTORS = f_base
    WB_FACTORS = f_base; p0 = wb_predict(wb_fit(TRF), te)
    WB_FACTORS = f_jb; p1 = wb_predict(wb_fit(TRF), te)
    ea = lambda pp: np.abs(np.exp(pp) * te["est"].values / te["actual"].values - 1)
    e0, e1 = ea(p0), ea(p1); jm = (pd.to_numeric(te["jb"], errors="coerce").abs() > 0.12).values if "jb" in te.columns else np.zeros(len(te), bool)
    print(f"  🆕 최근 거래 점프 요인(jb) 검증(최근 12개월 {len(te):,}건): 보통 오차 {np.median(e0) * 100:.3f}% → {np.median(e1) * 100:.3f}% | 점프 큰 사례 {int(jm.sum())}건: {np.median(e0[jm]) * 100 if jm.sum() else float('nan'):.2f}% → {np.median(e1[jm]) * 100 if jm.sum() else float('nan'):.2f}%")
    use_jb = bool(np.median(e1) < np.median(e0) - 0.0002 or (jm.sum() >= 100 and np.median(e1[jm]) < np.median(e0[jm]) - 0.005 and np.median(e1) <= np.median(e0) + 0.0003))
    WB_FACTORS = f_jb if use_jb else f_base; p = p1 if use_jb else p0
    print("  → 최근 거래 점프 요인", "사용" if use_jb else "사용 안 함(효과 없음)")
    res = np.log(te["actual"] / te["est"]).values - p
    # 📍 법정동별 정확도(2026-11-03, 사용자 수정요청: "예상낙찰가·추천입찰가가 실제낙찰가와 잘 맞는 지역을 법정동 단위로") -
    # 학습에 안 쓴 최근 12개월(te) 사례를 시군구+법정동으로 묶어 ① 예상 낙찰가 ② 추천입찰가가 실제 낙찰가와 얼마나 맞았는지 계산.
    # ⚠️ ②의 추천입찰가는 앱이 입찰 전에 저장한 값이 아니라 "예상매도가(est)−고정비용−최소마진 1,000만"을 비율비용으로 나눠 다시 계산한 근사값(앱 추천가는 낙찰 확률·기대수익까지 보므로 다를 수 있음)
    try:
        MIN_MARGIN = 1000
        dd = te.copy(); dd["pred"] = np.exp(p) * dd["est"].values
        dd["rec"] = (dd["est"] - FIXED_COST - MIN_MARGIN) / COST_RATIO
        dd["e1"] = dd["actual"] / dd["pred"] - 1
        rows = []
        for (rg, dk), G in dd.groupby(["region", "dk"]):
            if not dk or len(G) < 12: continue
            e1 = G["e1"].values; row = {"region": rg, "dong": dk, "n": int(len(G)),
                "predErrPct": round(float(np.median(np.abs(e1))) * 100, 1), "predBiasPct": round(float(np.median(e1)) * 100, 1),
                "predIn5Pct": round(float((np.abs(e1) <= 0.05).mean()) * 100), "predIn10Pct": round(float((np.abs(e1) <= 0.10).mean()) * 100)}
            Gr = G[G["rec"] > 0]
            if len(Gr) >= 12:
                e2 = (Gr["actual"] / Gr["rec"] - 1).values
                row.update({"recN": int(len(Gr)), "recErrPct": round(float(np.median(np.abs(e2))) * 100, 1), "recGapPct": round(float(np.median(e2)) * 100, 1),
                            "recIn10Pct": round(float((np.abs(e2) <= 0.10).mean()) * 100), "winAtRecPct": round(float((Gr["actual"] <= Gr["rec"]).mean()) * 100)})
            rows.append(row)
        if rows:
            cyc.upsert_rows([{"id": "signal|__winbid_dong__", "payload": cyc.clean_json({"generatedAt": now, "from": cut, "to": int(D["sale"].max()), "minN": 12, "minMargin": MIN_MARGIN, "rows": rows}), "fetched_at": now}])
            print(f"  📍 법정동별 정확도: {len(rows)}곳 저장 (사례 12건 이상)")
    except Exception as e:
        print("  법정동별 정확도 건너뜀:", e)
    # 🧭 틈새 진단(2026-10-10, 사용자: "틈새라면 입찰가를 낮춰 수익을 키워야"): 틈새 시군구에서 낙찰가가 모델 예상보다 낮게 나오는지(잔차) 확인 - 최근 12개월 검증 표본
    try:
        NICHE = {"충남 당진시", "충남 서산시", "전북 군산시", "전북 남원시", "경남 창녕군", "경남 함안군"}
        tt = te.copy(); tt["res"] = res; tt["lowb"] = tt["bidders"].map(lambda b: np.nan if pd.isna(b) else float(b <= 3))
        def rs(G):
            return {"n": int(len(G)), "medResPct": round(float(np.median(G["res"])) * 100, 1), "q25": round(float(np.quantile(G["res"], .25)) * 100, 1), "q75": round(float(np.quantile(G["res"], .75)) * 100, 1)}
        tn = tt[tt["region"].isin(NICHE)]; to = tt[~tt["region"].isin(NICHE)]
        diag = {"전체": rs(tt), "틈새 시군구": rs(tn) if len(tn) >= 20 else {"n": int(len(tn))}, "그 외": rs(to)}
        for lowb, nm in ((1.0, "입찰 3명 이하"), (0.0, "입찰 4명+")):
            g1 = tt[tt["lowb"] == lowb]
            if len(g1) >= 30: diag[nm] = rs(g1)
        byr = {}
        for rg, G in tt.groupby("region"):
            if len(G) >= 25: byr[rg] = rs(G)
        diag["시군구별 잔차(실제÷예상-1, 음수=예상보다 싸게 낙찰)"] = dict(sorted(byr.items(), key=lambda kv: kv[1]["medResPct"])[:12])
        print("  🧭 틈새 진단:", json.dumps(diag, ensure_ascii=False))
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("### 틈새 진단\n```json\n" + json.dumps(diag, ensure_ascii=False, indent=1) + "\n```\n")
    except Exception as e:
        print("  틈새 진단 건너뜀:", e)
    try:
        jibang_scorecard(te, p, R0, now)
    except Exception as e:
        import traceback; traceback.print_exc(); print("  지방 성적표 건너뜀:", e)
    try:
        thin_correction(R0, now)
    except Exception as e:
        import traceback; traceback.print_exc(); print("  얇은 근거 보정 실험 건너뜀:", e)
    try:
        resale_gap_report(R0, now)
    except Exception as e:
        print("  되팔기 간극 건너뜀:", e)
    try:
        est_rule_experiment(R0, wb_fit, wb_predict, now)
    except Exception as e:
        print("  새 시세 기준 실험 건너뜀:", e)
    try:
        print("  ▶ 시세 기준 지점(40/50/60%) 비교")
        est_rule_experiment(R0, wb_fit, wb_predict, now, (("40%(현재)", "est"), ("50%", "est_q50"), ("60%", "est_q60")), "시세 기준 지점 40/50/60% 비교")
    except Exception as e:
        print("  시세 기준 지점 비교 건너뜀:", e)
    if os.environ.get("WB_EXP"):  # 2026-10-25 예상 낙찰가 개선 실험(수동 실행 때만) - 앱 계산은 바꾸지 않음
        try:
            import winbid_experiments as _we
            _pz = requests.get(f"{SITE_URL}/api/data-coverage?mode=permit", timeout=120).json()
            _zn = {region_norm(v[3]) for v in (_pz.get("flagged") or {}).values() if len(v) > 3 and v[3]}; _zn.discard(None)
            print("  R 열:", list(R.columns))
            _we.run(D, tr, te, wb_fit, wb_predict, _zn, est_rule_experiment, R, now)
        except Exception as e:
            import traceback; traceback.print_exc(); print("  개선 실험 건너뜀:", e)
    full = wb_fit(_recent_w(D, int(D["sale"].max())) if use_rw else D)
    full["recentWeight"] = bool(use_rw); full["n"] = int(len(D)); full["principle"] = principle; full["factors"] = [f for f, _ in WB_FACTORS]; full["tuned"] = tune_info;
    try:  # 🌊 흐름 값이 실제로 얼마나 채워졌나(수도권·지방 따로) - 표본 부족이면 비워 두므로 비율을 기록
        _fi = {}
        for _c in ("수도권", "지방"):
            _G = D[D["flow_cls"] == _c] if "flow_cls" in D.columns else D.iloc[0:0]
            if len(_G): _fi[_c] = {"n": int(len(_G)), "동": round(float(_G["flow_dong"].notna().mean()) * 100, 1), "시군구": round(float(_G["flow_sgg"].notna().mean()) * 100, 1), "단지": round(float(_G["flow_cx"].notna().mean()) * 100, 1), "동거래량": round(float(_G["flow_dong_v"].notna().mean()) * 100, 1), "단지거래량": round(float(_G["flow_cx_v"].notna().mean()) * 100, 1), "반경2km가격": round(float(_G["flowR2_p"].notna().mean()) * 100, 1) if "flowR2_p" in _G.columns else None, "반경2km회전율": round(float(_G["flowR2_t"].notna().mean()) * 100, 1) if "flowR2_t" in _G.columns else None}
        full["flowInfo"] = _fi
    except Exception as _e:
        print("  흐름 채움 비율 건너뜀:", _e)
    full["flowCoef"] = dict(FLOW_COEF_CLS)   # 앱이 같은 계수로 시세 흐름 반영(주간 자동 선택)
    try: full["riskTable"] = risk_table(R0, now)
    except Exception as e: print("  위험 표 계산 실패:", e)
    full["flowIsNew"] = True; full["flowDiag"] = flow_diag; full["estRule"] = True; full["estFlow"] = "est_rule_f" in R.columns; full["factorsK"] = [[f, k] for f, k in WB_FACTORS]
    # 경쟁 예상(2026-10-10): 같은 요인으로 로그 응찰자 수를 맞추는 모델 - 앱이 하위 25%(낮음)·상위 25%(높음)로 표시
    try:
        Db = D[D["bidders"].notna() & (D["bidders"] > 0) & (D["sale"] >= 20230101)].copy()
        if len(Db) >= 3000:
            yb = np.log(Db["bidders"].astype(float)).values
            mb = wb_fit_y(Db, yb)
            pbv = wb_predict(mb, Db)
            full["bid"] = {"base": mb["base"], "eff": mb["eff"], "q25": round(float(np.quantile(pbv, 0.25)), 4), "q75": round(float(np.quantile(pbv, 0.75)), 4), "n": int(len(Db)), "from": 20230101}
    except Exception as e:
        print("  경쟁 예상 모델 건너뜀:", e)
    # 🧭 경쟁 예상별 낙찰가 보정(2026-10-10, 사용자: "틈새라면 입찰가를 낮춰 수익을 확보") - 응찰자 수를 입찰 전 정보로 맞추는 모델(학습 구간 데이터만)로 검증 구간을 낮음/보통/높음으로 나눠,
    # 각 그룹에서 '실제 낙찰가 ÷ 가격 모델 예상'의 로그 잔차 중앙값을 구함 → 앱이 경쟁 예상이 낮음/높음이면 예상 낙찰가를 그만큼 조정
    try:
        Dtr = tr[tr["bidders"].notna() & (tr["bidders"] > 0) & (tr["sale"] >= 20230101)]
        tb = te[te["bidders"].notna() & (te["bidders"] > 0)]
        if len(Dtr) >= 3000 and len(tb) >= 300:
            mb2 = wb_fit_y(Dtr, np.log(Dtr["bidders"].astype(float)).values)
            ptr = wb_predict(mb2, Dtr); q25c, q75c = float(np.quantile(ptr, 0.25)), float(np.quantile(ptr, 0.75))
            pte = wb_predict(mb2, tb)
            rs = pd.Series(res, index=te.index).loc[tb.index].values
            ca = {}
            for nm, msk in (("낮음", pte <= q25c), ("보통", (pte > q25c) & (pte < q75c)), ("높음", pte >= q75c)):
                if msk.sum() >= 100: ca[nm] = {"adj": round(float(np.median(rs[msk])), 4), "n": int(msk.sum()), "q25": round(float(np.quantile(rs[msk], .25)), 4), "q75": round(float(np.quantile(rs[msk], .75)), 4)}
            full["compAdj"] = ca
            print("  🧭 경쟁 예상별 낙찰가 잔차:", json.dumps(ca, ensure_ascii=False))
    except Exception as e:
        print("  경쟁 예상별 보정 건너뜀:", e)
    full["resQ"] = [round(float(np.quantile(res, q / 100)), 4) for q in range(1, 100)]
    # 📐 구간별 오차 분포(2026-11-03, 사용자: "낙찰 가능성은 예상 낙찰가에서 나오는데 모든 물건에 같은 오차폭을 쓰니 깊은 할인 예측 구간에서 확률이 과신")
    # 예상 낙찰가÷시세(=exp(예측)) 구간별로 오차(실제÷예상의 로그) 분포를 따로 만들어 앱이 낙찰 가능성을 구간 분포로 계산하게 함.
    # 학습에 안 쓴 최근 12개월(te)을 시간순 60/40으로 나눠 "앞 60%로 만든 표가 뒤 40%에서 얼마나 맞는지"(분위 적중률 오차)를 전체 단일 분포와 비교해 좋아질 때만 use=True
    try:
        ratio = np.exp(p); edges = [round(float(np.quantile(ratio, q)), 3) for q in (0.10, 0.25, 0.50, 0.75, 0.90)]
        bk = np.searchsorted(np.array(edges), ratio, side="right"); qs = np.arange(1, 100) / 100.0; TAU = (0.1, 0.25, 0.5, 0.75, 0.9)
        def qtab(idx):
            allq = np.quantile(res[idx], qs); out = []
            for b in range(len(edges) + 1):
                m = idx[bk[idx] == b]
                out.append(np.quantile(res[m], qs) if len(m) >= 150 else allq)
            return out
        order = np.argsort(te["sale"].values, kind="stable"); k = int(len(order) * 0.6); fi, vi = order[:k], order[k:]
        t60 = qtab(fi); g60 = np.quantile(res[fi], qs)
        def cover_err(tabs, idx):
            errs = []; per = {}
            for b in range(len(edges) + 1):
                m = idx[bk[idx] == b]
                if len(m) < 50: continue
                e_b = []
                for t in TAU:
                    qv = (tabs[b] if tabs is not None else g60)[int(round(t * 100)) - 1]
                    e_b.append(abs(float((res[m] <= qv).mean()) - t))
                per[b] = round(float(np.mean(e_b)) * 100, 1); errs += e_b
            return (float(np.mean(errs)) if errs else 9.0), per
        eg, pg = cover_err(None, vi); eb, pb = cover_err(t60, vi)
        use_b = bool(eb < eg * 0.9)
        # 전체 깊은 구간 예시: 하위 10% 구간에서 "예상가로 입찰하면 낙찰" 비율이 이 표로 얼마나 정확한지(0.5에 가까울수록 좋음)
        full["resQB"] = {"edges": edges, "q": [[round(float(v), 4) for v in row] for row in qtab(np.arange(len(res)))], "use": use_b,
                         "check": {"전체분포 적중오차%": round(eg * 100, 2), "구간분포 적중오차%": round(eb * 100, 2), "구간별 전체분포 오차%": pg, "구간별 구간분포 오차%": pb, "검증 n": int(len(vi))},
                         "spread": [round(float(np.quantile(res[bk == b], 0.75) - np.quantile(res[bk == b], 0.25)), 4) for b in range(len(edges) + 1)], "n": int(len(res))}
        print("  📐 구간별 오차 분포:", json.dumps({k2: v2 for k2, v2 in full["resQB"].items() if k2 != "q"}, ensure_ascii=False))
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("### 구간별 오차 분포\n```json\n" + json.dumps({k2: v2 for k2, v2 in full["resQB"].items() if k2 != "q"}, ensure_ascii=False, indent=1) + "\n```\n")
    except Exception as e:
        print("  구간별 오차 분포 건너뜀:", e)
    full["oos"] = {"from": cut, "n": int(len(te)), "medAbsErrPct": round(float(np.median(np.abs(np.exp(p) * te["est"] / te["actual"] - 1))) * 100, 1)}
    try:
        import accuracy_ledger as _led
        _r = te["actual"].values / (np.exp(p) * te["est"].values) - 1  # 실제 ÷ 예상 - 1 (+면 실제가 더 높음)
        try:  # 2026-10-25 규제지역(토지거래허가구역 지정 시군구) 안/밖 정확도 - 앱의 규제지역 필터와 같은 자료(현재 지정 기준 근사: 낙찰 당시 지정 여부는 아님)
            _pz = requests.get(f"{SITE_URL}/api/data-coverage?mode=permit", timeout=120).json()
            _zones = {region_norm(v[3]) for v in (_pz.get("flagged") or {}).values() if len(v) > 3 and v[3]}
            _zones.discard(None)
            _inz = te["region"].map(lambda r: r in _zones).values
            _grp = {}
            for _nm, _mk in (("규제지역(허가구역) 안", _inz), ("비규제지역", ~_inz)):
                if _mk.sum() >= 100:
                    _x = _r[_mk]; _grp[_nm] = {"n": int(_mk.sum()), "err": round(float(np.median(np.abs(_x))) * 100, 2), "bias": round(float(np.median(_x)) * 100, 2), "hi10": round(float((_x < -0.10).mean()) * 100, 1), "hit10": round(float((np.abs(_x) <= 0.10).mean()) * 100, 1), "p90": round(float(np.quantile(np.abs(_x), .9)) * 100, 1)}
            print("  🚧 규제지역 안/밖 예상 낙찰가 정확도:", json.dumps(_grp, ensure_ascii=False), "| 허가구역 시군구", len(_zones))
            for _nm, _key in (("규제지역(허가구역) 안", "winbid_permit"), ("비규제지역", "winbid_nonpermit")):
                if _nm in _grp: _led.record(cyc, _key, {k2: v2 for k2, v2 in _grp[_nm].items() if k2 != "p90"}, "예상 낙찰가 - " + _nm)
        except Exception as _e:
            print("  규제지역 구분 정확도 건너뜀:", _e)
        _led.record(cyc, "winbid", {"n": int(len(_r)), "err": round(float(np.median(np.abs(_r))) * 100, 2), "bias": round(float(np.median(_r)) * 100, 2),
                                    "hi10": round(float((_r < -0.10).mean()) * 100, 1), "hit10": round(float((np.abs(_r) <= 0.10).mean()) * 100, 1)}, "예상 낙찰가(학습 제외 최근 1년)")
    except Exception as e:
        print("  원장 기록 건너뜀(예상낙찰가):", e)
    full["generatedAt"] = now; full["dataTo"] = int(D["sale"].max())
    print(f"  예상 낙찰가 모델: 사례 {len(D):,}건, 최근 1년 검증 {full['oos']}")
    cyc.upsert_rows([{"id": "signal|__winbid__", "payload": cyc.clean_json(full), "fetched_at": now}])


# ════ 📊 주간 리포트 (2026-10, 사용자: "매주 낙찰사례·경매사례를 올릴 건데 지난 1주일 사이 낙찰된 사례의 예상 입찰가·낙찰가·매칭 리포트를 보여줘") ════
# 최근 낙찰 사례(분석일 기준 9일 이내, 20건 미만이면 16일)를 "그 주 이전 사례만으로 만든 예상 낙찰가 모델"에 넣어 실제 낙찰가와 비교 - 학습에 안 쓴 사례라 진짜 시험.
# + 시장 분위기(낙찰가÷시세·응찰자 수가 평소보다 센지) + 가장 크게 빗나간 사례 + 입찰후보로 추적하던 물건(사건번호 일치, 앱이 입찰 전에 저장한 예측 predSnap 있으면 비교)
# + 6개월 전 낙찰 사례의 "같은 동·층 거래 흔적"(되팔기 매칭) 현황. 결과: leader_follower_cache 'signal|__weekly_report__'
def norm_case(s):
    return re.sub(r"\(\d+\)$", "", str(s or "").replace(" ", "")).replace("타경", "-")


def amt_ok(x, appraisal_manwon):
    """2026-10-25 같은 사건번호의 다른 물건이 섞이지 않았나 - 저장된 경매물건의 감정가와 낙찰사례의 감정가(만원)가 5% 안이면 같은 물건으로 봄(한쪽이 비어 있으면 통과)"""
    try:
        a, b = float(x.get("appraisal")), float(appraisal_manwon)
    except (TypeError, ValueError):
        return True
    return a <= 0 or b <= 0 or abs(a / b - 1) <= 0.05


def pick_snap(x, sale_int):
    """낙찰일 이전에 저장된 예측 중 가장 늦은(=입찰에 가장 가까운) 것. 누적 이력(predHist)이 없으면 마지막 저장본(predSnap)"""
    hist = [h for h in (x.get("predHist") or []) if isinstance(h, dict) and h.get("at")]
    if not hist and x.get("predSnap"):
        hist = [x["predSnap"]]
    ok = [h for h in hist if str(h.get("at", "")).replace("-", "") <= str(int(sale_int))]
    return (sorted(ok, key=lambda h: h["at"])[-1] if ok else None)


def prob_calibration(P, won):
    """2026-10-25 낙찰 가능성 보정: 앱이 입찰 전 저장한 낙찰 가능성(prob)과 실제 낙찰 여부로 로지스틱 보정(logit(보정) = a + b·logit(원래)).
    높게 나온 구간이 실제보다 크게 높았던 문제(73% 예측 → 16% 실제)를 줄이되, 입찰가를 올리면 낙찰 가능성도 항상 올라가게(단조 증가) 함.
    (처음엔 구간 평균 방식(PAVA)이었는데 높은 구간이 한 값으로 납작해져 입찰가를 올려도 가능성이 같게 나와서 로지스틱으로 바꿈 - 2026-10-27)
    시간순 60/40 검증에서 Brier 점수가 2% 넘게 좋아질 때만 앱이 씀. 앱은 보정값이 원래보다 낮을 때만 깎아서 씀"""
    P = np.clip(np.asarray(P, float), 0.01, 0.99); Y = np.asarray(won, float)
    if len(P) < 150: return None
    lg = lambda p: np.log(p / (1 - p))
    def fit(x, y):
        w = np.zeros(2); X = np.c_[np.ones(len(x)), x]
        for _ in range(60):
            p = 1 / (1 + np.exp(-X @ w)); g = X.T @ (p - y); H = X.T @ (X * (p * (1 - p))[:, None]) + 1e-6 * np.eye(2)
            w = w - np.linalg.solve(H, g)
        return w
    ap = lambda w, p: 1 / (1 + np.exp(-(w[0] + w[1] * lg(p))))
    k = int(len(P) * 0.6); w1 = fit(lg(P[:k]), Y[:k]); te = slice(k, None)
    pc = np.minimum(P[te], ap(w1, P[te]))
    b0 = float(np.mean((P[te] - Y[te]) ** 2)); b1 = float(np.mean((pc - Y[te]) ** 2))
    w = fit(lg(P), Y)
    res = {"n": int(len(P)), "brierBefore": round(b0, 4), "brierAfter": round(b1, 4), "lr": [round(float(w[0]), 4), round(float(w[1]), 4)], "use": bool(b1 < b0 * 0.98 and w[1] > 0)}
    print("  🎯 낙찰 가능성 보정(시험 구간):", res, "| 예: 원래 50%→", round(float(ap(w, 0.5)), 3), " 90%→", round(float(ap(w, 0.9)), 3), " 99%→", round(float(ap(w, 0.99)), 3))
    return res


def scorecard(D, amap):
    """2026-10-09 추천가 성적표 - 지금까지 저장된 예측(입찰 전) 전체를 실제 낙찰 결과와 비교(주 단위가 아니라 누적).
    낙찰 가능성 구간별 '예측 vs 실제 낙찰 비율', 추천가 대비 실제 낙찰가, 낙찰가 예측 오차"""
    rows = []
    for r in D.itertuples():
        x = amap.get((norm_case(r.caseNo), r.region))
        if not x or not amt_ok(x, getattr(r, "appraisal", None)):
            continue
        sn = pick_snap(x, r.sale)
        if not sn or not sn.get("recBid"):
            continue
        rows.append({"case": r.caseNo, "name": (r.bname if isinstance(r.bname, str) and r.bname.strip() and r.bname != "nan" else None) or x.get("name") or "", "region": r.region, "sale": int(r.sale), "actual": float(r.actual), "rec": float(sn["recBid"]),
                     "prob": sn.get("prob"), "win": sn.get("win"), "minbid": float(r.minbid), "at": sn.get("at"), "snapMin": sn.get("minBid")})
    out = {"n": len(rows)}
    if not rows:
        return out
    X = pd.DataFrame(rows)
    X["won"] = X["actual"] <= X["rec"]
    X["ratio"] = X["actual"] / X["rec"]
    out["recWon"] = int(X["won"].sum()); out["recWonPct"] = round(float(X["won"].mean()) * 100, 1)
    out["actualOverRecMed"] = round(float(X["ratio"].median()), 3)
    W = X[X["win"].notna() & (X["win"] > 0)]
    if len(W):
        e = (W["win"] - W["actual"]) / W["actual"]
        out["winPredN"] = int(len(W)); out["winPredMedAbsErrPct"] = round(float(e.abs().median()) * 100, 1); out["winPredBiasPct"] = round(float(e.median()) * 100, 1)
    P = X[X["prob"].notna()]
    bins = [(0, 0.10, "10% 미만"), (0.10, 0.25, "10~25%"), (0.25, 0.50, "25~50%"), (0.50, 1.01, "50% 이상")]
    cal = []
    for lo, hi, lab in bins:
        G = P[(P["prob"] >= lo) & (P["prob"] < hi)]
        if len(G):
            cal.append({"label": lab, "n": int(len(G)), "predPct": round(float(G["prob"].mean()) * 100, 1), "actualPct": round(float(G["won"].mean()) * 100, 1)})
    out["calibration"] = cal
    # 조정 필요 신호: 구간 합계가 30건 이상이고 예측 평균과 실제 비율이 15%p 넘게 다르면
    tot = int(P["won"].count())
    gap = (float(P["won"].mean()) - float(P["prob"].mean())) * 100 if tot else 0
    out["probGapPct"] = round(gap, 1)
    out["needAdjust"] = bool(tot >= 30 and abs(gap) >= 15)
    try:
        Xs = P.sort_values("sale")
        out["probCal"] = prob_calibration(Xs["prob"].values, Xs["won"].values)
    except Exception as e:
        print("  낙찰 가능성 보정 건너뜀:", e); out["probCal"] = None
    # 🧼 깨끗한 예측만(2026-11-03, 사용자: "새로 쌓이는 예측만으로 성적표를 다시 보기") - ① 금액 일치: 입찰 전 저장한 최저가가 실제 최저가와 2% 안 ② 새 예측: 금액 점검(탱크옥션 대조·금액 미확인 보류)이 들어간 뒤(FRESH_FROM) 저장된 것
    def _view(V):
        if not len(V): return {"n": 0}
        v = {"n": int(len(V)), "recWonPct": round(float(V["won"].mean()) * 100, 1), "actualOverRecMed": round(float(V["ratio"].median()), 3)}
        PV = V[V["prob"].notna()]
        if len(PV):
            v["probPredPct"] = round(float(PV["prob"].mean()) * 100, 1); v["probActualPct"] = round(float(PV["won"].mean()) * 100, 1)
            v["calibration"] = [{"label": lab, "n": int(len(G)), "predPct": round(float(G["prob"].mean()) * 100, 1), "actualPct": round(float(G["won"].mean()) * 100, 1)}
                                for lo, hi, lab in bins for G in [PV[(PV["prob"] >= lo) & (PV["prob"] < hi)]] if len(G)]
        return v
    try:
        okm = X["snapMin"].notna() & (np.abs(X["snapMin"].astype(float) - X["minbid"]) / X["minbid"] <= 0.02)
        FRESH_FROM = "2026-11-01"
        out["clean"] = {"금액일치": _view(X[okm]), "금액불일치": _view(X[X["snapMin"].notna() & ~okm]), "새예측": {"from": FRESH_FROM, **_view(X[okm & (X["at"].astype(str) >= FRESH_FROM)])}, "기준": "저장한 최저가가 실제와 2% 안인 예측만 / 새예측은 FRESH_FROM 이후 저장분"}
    except Exception as e:
        print("  깨끗한 예측 성적표 건너뜀:", e)
    out["items"] = [{"case": r["case"], "name": r["name"], "region": r["region"], "sale": int(r["sale"]), "rec": round(r["rec"]), "actual": round(r["actual"]), "won": bool(r["won"]),
                     "prob": None if pd.isna(r["prob"]) else r["prob"], "win": None if pd.isna(r["win"]) else r["win"]} for _, r in X.sort_values("sale", ascending=False).head(60).iterrows()]
    return out


def is_go(sn):
    """임장 후보 여부 - 앱이 저장한 go 값(2026-10-19~)이 있으면 그것, 없으면 추정(추천가 있고 낙찰 가능성 20% 이상: 앱의 후보 기준과 같지만 권리·시세근거 제외 조건은 몰라 약간 넉넉함)"""
    if "go" in sn:
        return bool(sn["go"]), "saved"
    return bool(sn.get("recBid") and (sn.get("prob") or 0) >= 0.20), "estimated"


def cand_review(W, tr, amap, start, end, now_dt):
    from collections import Counter
    won_keys = {(norm_case(r.caseNo), r.region) for r in W.itertuples()}
    wrow = {(norm_case(r.caseNo), r.region): r for r in W.itertuples()}
    d_iso = lambda i: f"{str(i)[:4]}-{str(i)[4:6]}-{str(i)[6:]}"
    lo, hi = d_iso(start), d_iso(end)
    goWon, nonWon, goNot, nonNot = [], [], [], []
    basis = Counter()
    for (cn, rg), x in amap.items():
        bd = str(x.get("bidDate") or "")[:10]
        if not (lo <= bd <= hi):
            continue
        sn = pick_snap(x, int(bd.replace("-", "")))
        if not sn:
            continue
        go, bs = is_go(sn); basis[bs] += 1
        item = {"caseNo": x.get("caseNo"), "name": x.get("name") or "", "region": rg, "bidDate": bd, "minbid": sn.get("minBid"), "rec": sn.get("recBid"), "prob": sn.get("prob"), "win": sn.get("win"), "sale": sn.get("sale"), "fails": sn.get("fails"), "why": sn.get("why")}
        if (cn, rg) in won_keys and amt_ok(x, getattr(wrow[(cn, rg)], "appraisal", None)):
            r = wrow[(cn, rg)]
            item["actual"] = round(float(r.actual)); item["bidders"] = None if pd.isna(r.bidders) else int(r.bidders)
            item["why2"] = won_reason(item, go)
            (goWon if go else nonWon).append(item)
        else:
            item["why2"] = unsold_reason(x, bd, item, go)
            (goNot if go else nonNot).append(item)
    def rc(L):
        return [{"label": k, "n": v} for k, v in Counter(i["why2"] for i in L).most_common(8)]
    return {"from": lo, "to": hi, "basis": dict(basis), "goWon": len(goWon), "nonWon": len(nonWon), "goNot": len(goNot), "nonNot": len(nonNot),
            "goWonReasons": rc(goWon), "nonWonReasons": rc(nonWon), "goNotReasons": rc(goNot), "nonNotReasons": rc(nonNot),
            "items": {"goNot": sorted(goNot, key=lambda i: -(i.get("prob") or 0))[:25], "nonWon": sorted(nonWon, key=lambda i: -((i.get("rec") or 0) and i["actual"] / i["rec"] or 0))[:25], "goWon": goWon[:25]}}


def won_reason(it, go):
    rec, act, prob = it.get("rec"), it.get("actual"), it.get("prob")
    if go:
        return "추천가 이하로 낙찰(후보 적중)" if rec and act <= rec else "후보였지만 낙찰가가 추천가보다 높았음"
    if it.get("why"):
        return "후보 제외: " + str(it["why"])[:40]
    if not rec:
        return "추천가 없음(남는 마진이 없다고 계산)"
    if prob is not None and prob < 0.20:
        return ("낙찰 가능성 %d%%라 제외됐지만 추천가 근처에서 낙찰" % round(prob * 100)) if act <= rec * 1.1 else ("낙찰 가능성 %d%%라 제외, 낙찰가는 추천가보다 %d%% 높음" % (round(prob * 100), round((act / rec - 1) * 100)))
    return "그 밖의 제외 조건(시세 근거 부족·의심·대량경매 등)"


def unsold_reason(x, bd, it, go):
    for h in (x.get("bidHistory") or []):
        if str(h.get("date", ""))[:10] == bd:
            return "입찰일 결과: " + str(h.get("result") or "기록 있음")
    if str(x.get("courtResult") or "") == "매각":
        return "매각 기록은 있으나 낙찰사례 미등록"
    return "결과 미확인(취하·연기·변경 또는 낙찰사례 미등록)"


def winscore_improved(D, now_dt):
    """2026-10-25(사용자: 3가지 개선을 이번 주 리포트에만 적용해 리포트에서 확인) - 최근 12주 성적표와 같은 방식(28일 구간마다 그 이전 사례로 학습)으로 현재 방식과 개선안을 같은 사례에서 비교.
    개선안 = ① 시세를 새 규칙(est_rule)으로 ② 학습에서 최근 12개월 3배 가중 ③ 낙찰 가능성의 오차 폭을 유찰 횟수별로. 앱의 실제 계산은 바꾸지 않음(리포트 숫자만)."""
    ymd = lambda d: int(d.strftime("%Y%m%d"))
    DELTAS = (-0.08, -0.04, 0.0, 0.04, 0.08, 0.12)
    def cdf(res):
        q = np.sort(res); return lambda d: np.searchsorted(q, d, side="right") / max(len(q), 1)
    def fb(df): return df["fails"].map(lambda f: "?" if f is None or pd.isna(f) else str(min(int(f), 2)))
    acc = {"현재": [], "시세 새 규칙": [], "최근 가중": [], "개선안(둘 다)": []}; br = {"현재(오차 폭 하나)": [], "유찰별 오차 폭": []}; ns = 0; case_err = {}
    for b in range(3):
        b_to = now_dt - timedelta(days=28 * b); b_from = b_to - timedelta(days=28)
        lo_i, hi_i = ymd(b_from), ymd(b_to)
        has = D["est_rule"].notna() & (D["est_rule"] > 0) & np.log(D["actual"] / D["est_rule"].where(D["est_rule"] > 0)).between(np.log(0.4), np.log(1.6))
        Dv = D[has]
        T = Dv[(Dv["sale"] >= lo_i) & (Dv["sale"] < hi_i)].copy(); Tr = Dv[Dv["sale"] < lo_i]
        if len(T) < 30 or len(Tr) < 3000: continue
        ns += len(T)
        since12 = ymd(b_from - pd.DateOffset(months=12))
        Tr2 = Tr.copy(); Tr2["est"] = Tr2["est_rule"]; T2 = T.copy(); T2["est"] = T2["est_rule"]
        Trw = pd.concat([Tr, Tr[Tr["sale"] >= since12], Tr[Tr["sale"] >= since12]]); Trw2 = pd.concat([Tr2, Tr2[Tr2["sale"] >= since12], Tr2[Tr2["sale"] >= since12]])
        variants = {"현재": (wb_fit(Tr), T, "est"), "시세 새 규칙": (wb_fit(Tr2), T2, "est"), "최근 가중": (wb_fit(Trw), T, "est"), "개선안(둘 다)": (wb_fit(Trw2), T2, "est")}
        for nm, (m, TT, col) in variants.items():
            pr = np.exp(wb_predict(m, TT)) * TT[col]; X = TT.copy(); X["pred"] = pr; X["actual_"] = TT["actual"]
            X["base_est"] = T["est"].values  # 비교용: 같은 사례
            acc[nm].append(X[["pred", "actual", "region"]])
            for cn_, rg_, sl_, pr_, ac_ in zip(TT["caseNo"].values, TT["region"].values, TT["sale"].values, pr.values, TT["actual"].values):  # 사례별 오차(누적 비교용, 같은 사례는 한 번만 기록)
                case_err.setdefault(f"{cn_}|{rg_}|{int(sl_)}", {"sale": int(sl_)})[nm] = round(float((pr_ / ac_ - 1) * 100), 1)
        # 낙찰 가능성: 개선안 모델의 시험 잔차를 전체 하나 / 유찰별 분포로 평가(학습 잔차는 4분할)
        Ts = Trw2.sort_values("sale"); fo = np.array_split(np.arange(len(Ts)), 4); oof = np.zeros(len(Ts))
        for k in range(4):
            idx = fo[k]; rest = np.setdiff1d(np.arange(len(Ts)), idx)
            oof[idx] = wb_predict(wb_fit(Ts.iloc[rest]), Ts.iloc[idx])
        res_tr = np.log(Ts["actual"].values / Ts["est"].values) - oof
        res_te = np.log(T2["actual"].values / T2["est"].values) - wb_predict(variants["개선안(둘 다)"][0], T2)
        glob = cdf(res_tr); g_tr = fb(Ts).values; g_te = fb(T2).values
        cd = {k: cdf(res_tr[g_tr == k]) for k in set(g_tr) if (g_tr == k).sum() >= 150}
        for d in DELTAS:
            ev = (res_te <= d).astype(float)
            br["현재(오차 폭 하나)"].append(((np.full(len(res_te), glob(d)) - ev) ** 2).tolist())
            br["유찰별 오차 폭"].append(((np.array([cd[k](d) if k in cd else glob(d) for k in g_te]) - ev) ** 2).tolist())
    if not acc["현재"]: return None
    def st(parts):
        A = pd.concat(parts); e = (A["pred"] - A["actual"]) / A["actual"]; a = e.abs()
        return {"n": int(len(A)), "medAbsErrPct": round(float(a.median()) * 100, 2), "within10Pct": round(float((a <= 0.10).mean()) * 100, 1), "biasPct": round(float(e.median()) * 100, 2),
                "overPct": round(float((e > 0.10).mean()) * 100, 1), "p90AbsPct": round(float(a.quantile(.9)) * 100, 1)}
    out = {"n": ns, "variants": {nm: st(v) for nm, v in acc.items()}, "brier": {nm: round(float(np.mean(np.concatenate([np.array(x) for x in v]))), 5) for nm, v in br.items()},
           "components": ["시세 새 규칙(est_rule)", "최근 12개월 3배 가중", "낙찰 가능성 오차 폭을 유찰 횟수별로"]}
    out["_cases"] = case_err   # 호출한 쪽이 누적 저장에 쓰고 리포트 본문에는 넣지 않음
    return out


def update_compare_history(case_err, now_iso):
    """2026-11-04(사용자: 새 시세 규칙을 매주 비교 리포트에 두 값으로 표기하고 누적해서 비교) - 낙찰 사례마다 '현재/시세 새 규칙/최근 가중/둘 다' 예측 오차(%)를 한 번만 기록해
    주마다 겹치지 않게 쌓음(리포트 창이 9일·12주라 같은 사례가 여러 주 나오므로 사례 키로 중복 제거, 처음 기록한 값 유지). 앱이 누적 표를 이걸로 그림."""
    if not case_err:
        return
    NAMES = ["현재", "시세 새 규칙", "최근 가중", "개선안(둘 다)"]
    VER = "2026-11-04b"   # 모델 요인 구성이 바뀌면(감정가 제외·최저가 유지·새 시세 규칙) 이전 누적은 다른 모델의 값이라 버리고 새로 쌓음
    try:
        _pj = requests.get(f"{SITE_URL}/api/data-coverage?mode=winbidCompare&nocache={int(time.time())}", timeout=60).json() or {}
        old = (_pj.get("items") or []) if _pj.get("ver") == VER else []
    except Exception:
        old = []
    have = {it[0] for it in old if isinstance(it, list) and it}
    new = [[k, v["sale"]] + [v.get(nm) for nm in NAMES] for k, v in case_err.items() if k not in have and all(v.get(nm) is not None for nm in NAMES)]
    items = (old + new)
    items.sort(key=lambda it: it[1])
    items = items[-8000:]
    cyc.upsert_rows([{"id": "signal|__winbid_compare__", "payload": cyc.clean_json({"names": NAMES, "items": items, "generatedAt": now_iso, "ver": VER}), "fetched_at": now_iso}])
    print(f"  🧪 시세 규칙 비교 누적: 새로 {len(new)}건 → 총 {len(items)}건")


def weekly_report(R, now_dt, now_iso):
    D = R[R["est"].notna() & (R["est"] > 0) & R["actual"].notna() & R["minbid"].notna() & (R["minbid"] > 0) & (R["sale"] >= 20200101)].copy()
    D = D[np.log(D["actual"] / D["est"]).between(np.log(0.4), np.log(1.6))]
    if len(D) < 3000:
        print("  주간 리포트: 사례 부족, 건너뜀"); return
    ymd = lambda d: int(d.strftime("%Y%m%d"))
    start = ymd(now_dt - timedelta(days=9))
    W = D[D["sale"] >= start]
    if len(W) < 20:
        start = ymd(now_dt - timedelta(days=16)); W = D[D["sale"] >= start]
    train = D[D["sale"] < start]
    model = wb_fit(train)
    out = {"generatedAt": now_iso, "windowFrom": int(start), "windowTo": int(W["sale"].max()) if len(W) else None, "n": int(len(W))}
    if len(W):
        W = W.copy()
        W["pred"] = np.exp(wb_predict(model, W)) * W["est"]
        W["err"] = (W["pred"] - W["actual"]) / W["actual"]
        a = W["err"].abs()
        out["accuracy"] = {"medAbsErrPct": round(float(a.median()) * 100, 1), "within10Pct": round(float((a <= 0.10).mean()) * 100, 1), "biasPct": round(float(W["err"].median()) * 100, 1),
                           "winAtPredPct": round(float((W["actual"] <= W["pred"]).mean()) * 100, 1), "winAtPlus5Pct": round(float((W["actual"] <= W["pred"] * 1.05).mean()) * 100, 1)}
        out["benchmark"] = {"medAbsErrPct": 5.7, "note": "학습에 안 쓴 최근 1년 검증 기준"}
        base = D[(D["sale"] < start) & (D["sale"] >= ymd(now_dt - timedelta(days=380)))]
        out["market"] = {"actualOverEstMed": round(float((W["actual"] / W["est"]).median()), 3), "baseActualOverEstMed": round(float((base["actual"] / base["est"]).median()), 3),
                         "biddersMed": float(W["bidders"].median()) if W["bidders"].notna().any() else None, "baseBiddersMed": float(base["bidders"].median()) if base["bidders"].notna().any() else None,
                         "oneBidderPct": round(float((W["bidders"] == 1).mean()) * 100, 1), "baseOneBidderPct": round(float((base["bidders"] == 1).mean()) * 100, 1)}
        reg = []
        for rg, G in W.groupby("region"):
            if len(G) >= 3:
                reg.append({"region": rg, "n": int(len(G)), "medAbsErrPct": round(float(G["err"].abs().median()) * 100, 1), "biasPct": round(float(G["err"].median()) * 100, 1),
                            "actualOverEst": round(float((G["actual"] / G["est"]).median()), 3), "bidders": float(G["bidders"].median()) if G["bidders"].notna().any() else None})
        out["byRegion"] = sorted(reg, key=lambda x: -x["n"])[:15]
        top = W.reindex(W["err"].abs().sort_values(ascending=False).index).head(6)
        out["misses"] = [{"region": r.region, "name": r.bname, "caseNo": r.caseNo, "fails": None if pd.isna(r.fails) else int(r.fails), "minbid": round(float(r.minbid)), "pred": round(float(r.pred)), "actual": round(float(r.actual)),
                          "errPct": round(float(r.err) * 100, 1), "bidders": None if pd.isna(r.bidders) else int(r.bidders)} for r in top.itertuples()]
        # 입찰후보로 추적하던 물건(사건번호 일치) - 앱이 입찰 전에 저장한 예측(predSnap)과 비교
        try:
            au = requests.get(f"{SITE_URL}/api/auction", timeout=180).json()
            # 2026-10-09 정정: 사건번호는 법원마다 따로 매겨져(예: 2025-577이 군산·김해에 모두 있음) 사건번호만으로 맞추면 엉뚱한 물건끼리 비교됐음
            # (장유경동리인하이스트 ↔ 군산 소룡동제이파크) → (사건번호, 시군구)가 모두 같을 때만 같은 물건으로 봄
            amap = {(norm_case(x.get("caseNo")), region_norm(x.get("addr"))): x for x in au if isinstance(x, dict) and x.get("caseNo") and not x.get("isBacktest")}
        except Exception as e:
            print("  경매 목록 불러오기 실패(건너뜀):", e); amap = {}
        tr = []
        for r in W.itertuples():
            x = amap.get((norm_case(r.caseNo), r.region))
            if not x or not amt_ok(x, getattr(r, "appraisal", None)):
                continue
            sn = pick_snap(x, r.sale) or {}
            row = {"caseNo": r.caseNo, "name": r.bname or x.get("name") or "", "region": r.region, "actual": round(float(r.actual)), "bidders": None if pd.isna(r.bidders) else int(r.bidders),
                   "second": None if pd.isna(r.second) else round(float(r.second)), "minbid": round(float(r.minbid)), "modelPred": round(float(r.pred))}
            if sn:
                row["snap"] = {"at": sn.get("at"), "rec": sn.get("recBid"), "aggr": sn.get("aggr"), "win": sn.get("win"), "prob": sn.get("prob"), "sale": sn.get("sale")}
                if sn.get("recBid"):
                    row["recWon"] = bool(r.actual <= sn["recBid"]); row["actualOverRec"] = round(float(r.actual) / sn["recBid"], 3)
                if sn.get("win"):
                    row["snapErrPct"] = round((sn["win"] - float(r.actual)) / float(r.actual) * 100, 1)
            tr.append(row)
        out["tracked"] = {"n": len(tr), "withSnap": sum(1 for t in tr if t.get("snap")), "items": tr[:30],
                          "recWon": sum(1 for t in tr if t.get("recWon")), "recKnown": sum(1 for t in tr if "recWon" in t)}
        # 2026-10-19(사용자: 후보인데 안 낙찰·후보 아닌데 낙찰된 이유를 알아 후보군 정확도를 높이고 싶다) - 후보/비후보 × 낙찰/미낙찰 4칸 + 이유
        try:
            out["candReview"] = cand_review(W, tr, amap, int(start), int(W["sale"].max()), now_dt)
            cr_ = out["candReview"]; print("  후보 검토:", {k: cr_[k] for k in ("goWon", "goNot", "nonWon", "nonNot")})
        except Exception as e:
            print("  후보 검토 건너뜀:", e)
    # 6개월 전(5.5~6.5개월) 낙찰 사례의 같은 동·층 거래 흔적 - 동 확인(동 번호 있는 사례) 기준
    lo, hi = ymd(now_dt - timedelta(days=200)), ymd(now_dt - timedelta(days=165))
    S = R[(R["sale"] >= lo) & (R["sale"] <= hi)]
    if len(S):
        has_dong = S["adong"].notna()
        conf = S["resale_conf"].fillna("")
        out["trace6m"] = {"from": int(lo), "to": int(hi), "n": int(len(S)), "dongKnown": int(has_dong.sum()),
                          "dongConfirmed": int(((conf == "dong") & (S["resale_m"] <= 6.2)).sum()), "floorOnly": int(((conf == "floor") & (S["resale_m"] <= 6.2)).sum()),
                          "note": "같은 동·층 거래가 6개월 안에 있었는지(참고 - 호수를 몰라 옆집 거래일 수 있음, 우연 수준 약 7%)"}
    # 2026-10-10(사용자: "낙찰자가 추천가 마진 구간보다 마진을 줄여서 낙찰받는 이유를 알아야") - 낙찰 후 6개월 안에 되팔린 사례(동 확인)에서 낙찰자가 실제로 남긴 비율
    # 되판가÷낙찰가를 낙찰가÷시세 구간별·응찰자 수별로 집계. 비용 전 단순 비율(취득세·등기·중개·수리·이자로 보통 6~10%가 나가므로 1.06 미만이면 손해 위험이 큼)
    try:
        Aw = D[(D["resale_conf"] == "dong") & D["resale"].notna() & D["resale_m"].between(0.45, 6.2) & (D["sale"] >= 20230101) & (D["actual"] > 0)].copy()
        Aw["rr"] = Aw["resale"] / Aw["actual"]; Aw["r_est"] = Aw["actual"] / Aw["est"]
        def wm(G):
            return {"n": int(len(G)), "medRatio": round(float(G["rr"].median()), 3), "p25": round(float(G["rr"].quantile(.25)), 3), "p75": round(float(G["rr"].quantile(.75)), 3),
                    "lt106Pct": round(float((G["rr"] < 1.06).mean()) * 100, 1), "lt110Pct": round(float((G["rr"] < 1.10).mean()) * 100, 1)}
        wmo = {"n": int(len(Aw)), "overall": wm(Aw) if len(Aw) else None, "byPrice": [], "byBidders": []}
        for lo, hi, lab in ((0, .7, "시세의 70% 미만"), (.7, .8, "70~80%"), (.8, .9, "80~90%"), (.9, 1.0, "90~100%"), (1.0, 9, "시세 이상")):
            G = Aw[(Aw["r_est"] >= lo) & (Aw["r_est"] < hi)]
            if len(G) >= 30: wmo["byPrice"].append(dict(label=lab, **wm(G)))
        for lo, hi, lab in ((1, 1, "1명"), (2, 3, "2~3명"), (4, 5, "4~5명"), (6, 8, "6~8명"), (9, 999, "9명 이상")):
            G = Aw[Aw["bidders"].between(lo, hi)]
            if len(G) >= 30: wmo["byBidders"].append(dict(label=lab, **wm(G)))
        out["winnerMargin"] = wmo
        print("  낙찰자 실제 비율:", wmo["overall"])
    except Exception as e:
        print("  낙찰자 마진 건너뜀:", e)
    try:
        out["scorecard"] = scorecard(D, amap)
        print("  추천가 성적표:", {k: v for k, v in out["scorecard"].items() if k != "items"})
        try:
            _pc = out["scorecard"].get("probCal")
            if False and _pc and _pc.get("use"):  # 2026-10-28 되돌림: 앱에 쓰지 않음(계산·기록만 유지) - 예상 낙찰가에 입찰해도 15%로 나와 모델 정의와 어긋남
                import requests as _rq
                _rr = _rq.get(f"{cyc.SUPABASE_URL}/rest/v1/leader_follower_cache?select=payload&id=eq.signal%7C__winbid__", headers=cyc.HEADERS, timeout=60)
                if _rr.ok and _rr.json():
                    _wb = _rr.json()[0].get("payload") or {}
                    _wb["probCal"] = {"lr": _pc["lr"], "n": _pc["n"], "generatedAt": now_iso}
                    cyc.upsert_rows([{"id": "signal|__winbid__", "payload": cyc.clean_json(_wb), "fetched_at": now_iso}])
                    print("  ✅ 낙찰 가능성 보정표를 예상 낙찰가 모델에 저장")
        except Exception as e:
            print("  보정표 저장 건너뜀:", e)
        try:
            import accuracy_ledger as _led
            _sc = out["scorecard"]
            if _sc.get("n"):
                _led.record(cyc, "recbid", {"n": _sc["n"], "recWonPct": _sc.get("recWonPct"), "actualOverRec": _sc.get("actualOverRecMed"), "winPredErr": _sc.get("winPredMedAbsErrPct"), "probGapPct": _sc.get("probGapPct")}, "추천가 성적표(입찰 전 저장분)")
        except Exception as e:
            print("  원장 기록 건너뜀(추천가):", e)
    except Exception as e:
        print("  성적표 건너뜀:", e)
    # 2026-10-19(사용자: "리포트에 예상낙찰가 성적표도") - 최근 12주를 4주 단위로 끊어, 각 구간 이전 사례만으로 만든 모델이 그 구간 낙찰가를 얼마나 맞혔는지(주별·지역별·유찰별)
    try:
        ws = {"weeks": [], "byClass": [], "byFails": [], "blocks": 0}
        cls_f = lambda rg: "서울" if str(rg).startswith("서울") else ("경기·인천" if str(rg)[:2] in ("경기", "인천") else "지방")
        parts = []
        for b in range(3):
            b_to = now_dt - timedelta(days=28 * b); b_from = b_to - timedelta(days=28)
            lo_i, hi_i = ymd(b_from), ymd(b_to)
            T = D[(D["sale"] >= lo_i) & (D["sale"] < hi_i)].copy()
            Tr = D[D["sale"] < lo_i]
            if len(T) < 30 or len(Tr) < 3000: continue
            m = wb_fit(Tr); T["pred"] = np.exp(wb_predict(m, T)) * T["est"]; parts.append(T); ws["blocks"] += 1
        if parts:
            A = pd.concat(parts); A["err"] = (A["pred"] - A["actual"]) / A["actual"]
            A["dt"] = pd.to_datetime(A["sale"].astype(int).astype(str), format="%Y%m%d", errors="coerce")
            A["wk"] = (A["dt"] - pd.to_timedelta(A["dt"].dt.weekday, unit="D")).dt.strftime("%Y%m%d")
            def sc_stat(G):
                a = G["err"].abs()
                return {"n": int(len(G)), "medAbsErrPct": round(float(a.median()) * 100, 1), "within10Pct": round(float((a <= 0.10).mean()) * 100, 1), "biasPct": round(float(G["err"].median()) * 100, 1),
                        "winAtPredPct": round(float((G["actual"] <= G["pred"]).mean()) * 100, 1), "winAtPlus5Pct": round(float((G["actual"] <= G["pred"] * 1.05).mean()) * 100, 1),
                        "p75AbsPct": round(float(a.quantile(.75)) * 100, 1), "p90AbsPct": round(float(a.quantile(.90)) * 100, 1), "within5Pct": round(float((a <= 0.05).mean()) * 100, 1),
                        "overPct": round(float((G["err"] > 0.10).mean()) * 100, 1), "underPct": round(float((G["err"] < -0.10).mean()) * 100, 1),
                        "medAbsAmt": round(float((G["pred"] - G["actual"]).abs().median())), "p90AbsAmt": round(float((G["pred"] - G["actual"]).abs().quantile(.9))), "medActual": round(float(G["actual"].median()))}
            ws["all"] = sc_stat(A)
            for wk, G in A.groupby("wk"):
                if len(G) >= 10: ws["weeks"].append(dict(week=wk, **sc_stat(G)))
            ws["weeks"].sort(key=lambda x: x["week"])
            A["cls"] = A["region"].map(cls_f)
            for c in ("서울", "경기·인천", "지방"):
                G = A[A["cls"] == c]
                if len(G) >= 30: ws["byClass"].append(dict(label=c, **sc_stat(G)))
            A["fb"] = A["fails"].map(lambda f: None if f is None or pd.isna(f) else ("신건" if f == 0 else ("1회 유찰" if f == 1 else "2회+ 유찰")))
            for lab in ("신건", "1회 유찰", "2회+ 유찰"):
                G = A[A["fb"] == lab]
                if len(G) >= 30: ws["byFails"].append(dict(label=lab, **sc_stat(G)))
            ws["from"] = int(A["sale"].min()); ws["to"] = int(A["sale"].max())
        try:
            ws["improved"] = winscore_improved(D, now_dt)
            try:
                update_compare_history((ws["improved"] or {}).pop("_cases", None) or {}, now_iso)
            except Exception as e:
                print("  비교 누적 저장 건너뜀:", e)
            print("  🆕 예상 낙찰가 개선안 비교:", json.dumps(ws["improved"], ensure_ascii=False))
            if ws["improved"]:
                import accuracy_ledger as _led
                _v = ws["improved"]["variants"]["개선안(둘 다)"]
                _led.record(cyc, "winbid_v2", {"n": _v["n"], "err": _v["medAbsErrPct"], "bias": _v["biasPct"], "hi10": _v["overPct"], "hit10": _v["within10Pct"]}, "예상 낙찰가 개선안(리포트용, 앱 미적용)")
        except Exception as e:
            print("  개선안 비교 건너뜀:", e)
        out["winScore"] = ws
        print("  예상 낙찰가 성적표:", ws.get("all"), "주", len(ws["weeks"]))
    except Exception as e:
        print("  예상 낙찰가 성적표 건너뜀:", e)
    # 2026-10-22(사용자: 예상 낙찰가로 현재 로직을 맞춰 가는 방향 - 아파트·빌라 모두 매주 확인) 구간별 자동 보정이 다음 구간 오차를 줄였나 과거로 검증
    try:
        _sp = importlib.util.spec_from_file_location("wbc", os.path.join(HERE, "winbid_corr.py")); wbc = importlib.util.module_from_spec(_sp); _sp.loader.exec_module(wbc)
        C = D.copy()
        C["cls"] = C["region"].map(lambda rg: "서울" if str(rg).startswith("서울") else ("경기·인천" if str(rg)[:2] in ("경기", "인천") else "지방"))
        C["fb"] = C["fails"].map(lambda f: None if f is None or pd.isna(f) else ("신건" if f == 0 else ("1회 유찰" if f == 1 else "2회+ 유찰")))
        C = C[C["fb"].notna()]
        cc = wbc.walk_forward(C, lambda tr: wb_fit(tr), lambda m, te: wb_predict(m, te))
        cc["segment"] = "아파트"; cc["generatedAt"] = now_iso
        cyc.upsert_rows([{"id": "signal|__winbid_corr__", "payload": cyc.clean_json(cc), "fetched_at": now_iso}])
        print("  낙찰가 자동 보정 검증(아파트):", {k: cc.get(k) for k in ("ok", "blocks", "best", "bestGainPct", "recommend")})
    except Exception as e:
        print("  낙찰가 자동 보정 검증 건너뜀:", e)
    print(f"  주간 리포트: 기간 {start}~, 사례 {len(W)}건, 정확도 {out.get('accuracy')}")
    cyc.upsert_rows([{"id": "signal|__weekly_report__", "payload": cyc.clean_json(out), "fetched_at": now_iso}])
    # 지난 리포트 누적(사용자: 알림에서 확인한 뒤에도 계속 볼 수 있게 누적 목록) - 주마다 따로 저장 + 목록 갱신
    try:
        wk = str(out.get("windowTo") or ymd(now_dt))
        cyc.upsert_rows([{"id": f"signal|__weekly_report__|{wk}", "payload": cyc.clean_json(out), "fetched_at": now_iso}])
        try:
            hist = (requests.get(f"{SITE_URL}/api/data-coverage?mode=weeklyHistory&nocache={int(now_dt.timestamp())}", timeout=60).json() or {}).get("items") or []
        except Exception:
            hist = []
        acc, tk, sc = out.get("accuracy") or {}, out.get("tracked") or {}, out.get("scorecard") or {}
        item = {"week": wk, "windowFrom": out.get("windowFrom"), "windowTo": out.get("windowTo"), "n": out.get("n"), "generatedAt": now_iso,
                "medAbsErrPct": acc.get("medAbsErrPct"), "within10Pct": acc.get("within10Pct"), "biasPct": acc.get("biasPct"), "winAtPredPct": acc.get("winAtPredPct"),
                "trackedN": tk.get("n"), "recWon": tk.get("recWon"), "recKnown": tk.get("recKnown"), "scoreN": sc.get("n"), "scoreRecWonPct": sc.get("recWonPct")}
        hist = [h for h in hist if h.get("week") != wk] + [item]
        hist.sort(key=lambda h: h.get("week") or "")
        cyc.upsert_rows([{"id": "signal|__weekly_history__", "payload": cyc.clean_json({"items": hist[-120:]}), "fetched_at": now_iso}])
        print(f"  지난 리포트 목록 {len(hist)}건")
    except Exception as e:
        print("  지난 리포트 누적 저장 실패(건너뜀):", e)


if __name__ == "__main__":
    main()
