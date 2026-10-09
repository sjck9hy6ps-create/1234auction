"""
🏠 공간대여(외국인관광 도시민박업) 밀집 지역 집계 (2026-10-09)
사용자: 빌라 낙찰 후 에어비앤비 같은 공간대여업을 직접 운영하거나 전대차 하는 경우가 많아, 공간대여업이 많은 지역 위주로 입찰하려 함.
행안부 '외국인관광 도시민박업 조회서비스'(인허가 전국 데이터, 2일 전 기준)를 전부 받아 법정동·시군구별로 집계
 - 영업중 업소 수, 객실 수(있으면), 최근 1년·2년 신규 허가, 최근 1년 폐업, 허가 연도별 영업 건수(증가 추세)
※ 합법 등록분만 잡혀 실제보다 적음(미등록 영업이 많다는 보도). 지역 간 상대 비교용.
결과: leader_follower_cache 'signal|__homestay__' (앱 표시용) + 로그에 상위 지역 출력
"""
import os, re, json, time, importlib.util
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import requests
from pyproj import Transformer

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py"))
cyc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cyc)
K = os.environ["PUBLIC_DATA_API_KEY"]
EP = "https://apis.data.go.kr/1741000/foreigner_city_homestays/info"


def fetch_all():
    rows, page, total = [], 1, None
    while True:
        for attempt in range(10):  # 공공 API는 가끔 연결이 끊김 - 오래 기다리며 재시도(키 값은 로그에 안 찍음)
            try:
                r = requests.get(EP, params={"serviceKey": K, "pageNo": page, "numOfRows": 1000, "returnType": "json"}, timeout=(30, 120))
                b = r.json()["response"]["body"]
                break
            except Exception as e:
                print(f"  재시도 {attempt + 1}/10 ({type(e).__name__})", flush=True)
                time.sleep(min(60, 5 * (attempt + 1)))
                if attempt == 9:
                    raise
        total = int(b.get("totalCount") or total or 0)
        items = (b.get("items") or {}).get("item") or []
        if isinstance(items, dict):
            items = [items]
        rows += items
        print(f"  {page}쪽 {len(items)}건 (누적 {len(rows):,} / 전체 {total:,})", flush=True)
        if not items or len(rows) >= total:
            break
        page += 1
    return rows


def sido_norm(s):
    for k, v in (("전남광주", "전남광주"), ("광주", "전남광주"), ("전라남", "전남광주"), ("전남", "전남광주"), ("전북", "전북"), ("전라북", "전북"), ("경상남", "경남"), ("경남", "경남"),
                 ("경상북", "경북"), ("경북", "경북"), ("충청남", "충남"), ("충남", "충남"), ("충청북", "충북"), ("충북", "충북"), ("강원", "강원"), ("제주", "제주"), ("세종", "세종")):
        if s.startswith(k):
            return v
    return s[:2]


def parse_addr(a):
    """'부산광역시 남구 대연동 372-6' → ('부산 남구', '대연동')"""
    t = str(a or "").split()
    if len(t) < 3:
        return None, None
    sido = sido_norm(t[0])
    city = t[1]
    if len(t) >= 4 and city.endswith("시") and t[2].endswith("구"):
        city = city[:-1]; rest = t[3:]
    else:
        rest = t[2:]
    dong = next((x for x in rest if re.search(r"(동|가|읍|면|리)$", x) and not re.match(r"^\d", x)), None)
    return f"{sido} {city}", dong


def upsert_retry(rows):
    """Supabase가 다른 작업으로 바쁠 때 statement timeout(500)이 나므로 몇 번 다시 시도"""
    for attempt in range(6):
        try:
            cyc.upsert_rows(rows)
            return
        except Exception as e:
            print(f"  저장 재시도 {attempt + 1}/6 ({type(e).__name__})", flush=True)
            time.sleep(20 * (attempt + 1))
    raise RuntimeError("저장 실패")


def main():
    now = datetime.now(timezone.utc)
    items = fetch_all()
    df = pd.DataFrame(items)
    print(f"받은 업소 {len(df):,}건")
    df = df[df["CULTR_SPTS_TPBIZ_NM"].fillna("").str.contains("도시민박")].copy()
    addr = df["LOTNO_ADDR"].where(df["LOTNO_ADDR"].fillna("").str.len() > 0, df["ROAD_NM_ADDR"])
    p = addr.map(parse_addr)
    df["region"] = p.map(lambda x: x[0]); df["dong"] = p.map(lambda x: x[1])
    df = df.dropna(subset=["region", "dong"]).copy()
    df["open"] = df["SALS_STTS_CD"].astype(str).eq("01")
    df["lic"] = pd.to_datetime(df["LCPMT_YMD"].replace("", None), errors="coerce")
    df["clo"] = pd.to_datetime(df["CLSBIZ_YMD"].replace("", None), errors="coerce")
    df["rooms"] = pd.to_numeric(df["GSRM_CNT"], errors="coerce")
    today = pd.Timestamp(now.date())
    y1, y2 = today - pd.Timedelta(days=365), today - pd.Timedelta(days=730)
    print(f"  주소 해석 성공 {len(df):,}건, 영업중 {int(df['open'].sum()):,}건, 허가일 {df['lic'].min()} ~ {df['lic'].max()}")

    # 좌표: 인허가 좌표는 TM(EPSG:5174, 중부원점 구 Bessel) → WGS84. 부산 남구 대연동 샘플로 확인(35.13N 129.10E)
    tf = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)
    x = pd.to_numeric(df["CRD_INFO_X"], errors="coerce"); y = pd.to_numeric(df["CRD_INFO_Y"], errors="coerce")
    ok = x.notna() & y.notna() & (x > 0) & (y > 0)
    lon = pd.Series(np.nan, index=df.index); lat = pd.Series(np.nan, index=df.index)
    lo_, la_ = tf.transform(x[ok].values, y[ok].values)
    lon[ok] = lo_; lat[ok] = la_
    ok2 = lat.between(33, 39) & lon.between(124, 132)
    df["lat"] = lat.where(ok2); df["lon"] = lon.where(ok2)
    print(f"  좌표 변환 성공 {int(ok2.sum()):,}건 / {len(df):,}건")

    def activity(open_n, new1, new2, clo1, clo2):
        """증가/감소로 활성화 여부 판단(2026-10-09, 사용자: '증가와 감소를 측정해서 활성화되는지 여부 판단'):
        순증 = 최근 1년 신규 허가 − 최근 1년 폐업. 순증률 = 순증 ÷ 1년 전 영업 수.
         활성화: 순증 ≥3 이고 순증률 ≥10% (신규가 폐업을 크게 앞섬)
         위축: 순증 < 0, 또는 전년 신규가 6건 이상이었는데 올해 신규가 절반 이하
         그 외 안정, 업소 5곳 미만이고 신규 3건 미만이면 표본 적음"""
        net = new1 - clo1
        base = max(1, open_n - net)
        if open_n < 5 and new1 < 3:
            return "표본적음", net
        if net < 0 or (new2 >= 6 and new1 <= new2 * 0.5):
            return "위축", net
        if net >= 3 and net / base >= 0.10:
            return "활성화", net
        return "안정", net

    def agg(G):
        o = G[G["open"]]
        new1, new2 = int((G["lic"] >= y1).sum()), int(((G["lic"] >= y2) & (G["lic"] < y1)).sum())
        clo1, clo2 = int((G["clo"] >= y1).sum()), int(((G["clo"] >= y2) & (G["clo"] < y1)).sum())
        st, net = activity(int(len(o)), new1, new2, clo1, clo2)
        r = {"open": int(len(o)), "rooms": int(o["rooms"].sum()) if o["rooms"].notna().any() else None, "total": int(len(G)),
             "new1y": new1, "new2y": new2, "closed1y": clo1, "closed2y": clo2, "net1y": net, "state": st}
        oo = o.dropna(subset=["lat"])
        if len(oo):
            r["lat"] = round(float(oo["lat"].median()), 5); r["lon"] = round(float(oo["lon"].median()), 5)
        return r
    by_dong, by_region = {}, {}
    for (rg, dg), G in df.groupby(["region", "dong"]):
        by_dong[f"{rg}|{dg}"] = agg(G)
    for rg, G in df.groupby("region"):
        by_region[rg] = agg(G)
    # 허가 연도별 누적 영업 업소(연말 기준): 허가≤연말 & (폐업 없음 or 폐업>연말)
    trend = {}
    for y in range(2015, now.year + 1):
        end = pd.Timestamp(year=y, month=12, day=31) if y < now.year else today
        trend[str(y)] = int(((df["lic"] <= end) & (df["clo"].isna() | (df["clo"] > end))).sum())
    print("전국 연도별 영업 업소(대략):", trend)
    top = sorted(by_dong.items(), key=lambda kv: -kv[1]["open"])
    print("== 영업중 상위 법정동 40 ==")
    for k, v in top[:40]:
        print(f"  {k}: 영업 {v['open']} · 신규1년 {v['new1y']} · 신규전년 {v['new2y']} · 폐업1년 {v['closed1y']} · 객실 {v['rooms']}")
    from collections import Counter
    print("활성도 분포(동, 영업 5곳 이상):", dict(Counter(v["state"] for v in by_dong.values() if v["open"] >= 5)))
    print("== 활성화 판정 동(영업 많은 순 25) ==")
    for k, v in [kv for kv in top if kv[1]["state"] == "활성화"][:25]:
        print(f"  {k}: 영업 {v['open']} · 신규 {v['new1y']} · 폐업 {v['closed1y']} · 순증 {v['net1y']}")
    print("== 위축 판정 동(영업 많은 순 15) ==")
    for k, v in [kv for kv in top if kv[1]["state"] == "위축"][:15]:
        print(f"  {k}: 영업 {v['open']} · 신규 {v['new1y']}(전년 {v['new2y']}) · 폐업 {v['closed1y']} · 순증 {v['net1y']}")
    print("== 영업중 상위 시군구 25 ==")
    for k, v in sorted(by_region.items(), key=lambda kv: -kv[1]["open"])[:25]:
        print(f"  {k}: 영업 {v['open']} · 신규1년 {v['new1y']} · 폐업1년 {v['closed1y']}")
    payload = {"generatedAt": now.isoformat(), "n": int(len(df)), "open": int(df["open"].sum()), "trend": trend, "byRegion": by_region, "byDong": by_dong}
    upsert_retry([{"id": "signal|__homestay__", "payload": cyc.clean_json(payload), "fetched_at": now.isoformat()}])
    # 지도 배지용 점(영업중 + 좌표 있음): [위도, 경도, 업소명, 허가연도, 동키]
    pts = df[df["open"] & df["lat"].notna()]
    arr = [[round(float(a), 5), round(float(b), 5), str(n or "")[:16], (int(l.year) if pd.notna(l) else None), f"{rg}|{dg}"]
           for a, b, n, l, rg, dg in zip(pts["lat"], pts["lon"], pts["BPLC_NM"], pts["lic"], pts["region"], pts["dong"])]
    upsert_retry([{"id": "signal|__homestay_pts__", "payload": {"generatedAt": now.isoformat(), "pts": arr}, "fetched_at": now.isoformat()}])
    print(f"  지도용 점 {len(arr):,}건 저장")
    # 상세 패널용: 동별 업소 목록(영업중) - [업소명, 지번주소, 허가일(YYYYMMDD), 객실수, 위도, 경도, 도로명주소]
    lst = {}
    for _, r in df[df["open"]].iterrows():
        key = f"{r['region']}|{r['dong']}"
        lst.setdefault(key, []).append([str(r["BPLC_NM"] or "")[:30], str(r["LOTNO_ADDR"] or ""), (int(r["lic"].strftime("%Y%m%d")) if pd.notna(r["lic"]) else None),
                                        (int(r["rooms"]) if pd.notna(r["rooms"]) else None), (round(float(r["lat"]), 5) if pd.notna(r["lat"]) else None),
                                        (round(float(r["lon"]), 5) if pd.notna(r["lon"]) else None), str(r["ROAD_NM_ADDR"] or "")])
    upsert_retry([{"id": "signal|__homestay_list__", "payload": {"generatedAt": now.isoformat(), "byDong": lst}, "fetched_at": now.isoformat()}])
    print(f"  동별 업소 목록 저장 ({len(lst):,}개 동)")
    print("✅ 저장 완료")


if __name__ == "__main__":
    main()
