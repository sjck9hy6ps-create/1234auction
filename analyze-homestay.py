"""
🏠 공간대여(외국인관광 도시민박업) 밀집 지역 집계 (2026-10-09)
사용자: 빌라 낙찰 후 에어비앤비 같은 공간대여업을 직접 운영하거나 전대차 하는 경우가 많아, 공간대여업이 많은 지역 위주로 입찰하려 함.
행안부 '외국인관광 도시민박업 조회서비스'(인허가 전국 데이터, 2일 전 기준)를 전부 받아 법정동·시군구별로 집계
 - 영업중 업소 수, 객실 수(있으면), 최근 1년·2년 신규 허가, 최근 1년 폐업, 허가 연도별 영업 건수(증가 추세)
※ 합법 등록분만 잡혀 실제보다 적음(미등록 영업이 많다는 보도). 지역 간 상대 비교용.
결과: leader_follower_cache 'signal|__homestay__' (앱 표시용) + 로그에 상위 지역 출력
"""
import os, re, json, importlib.util
from datetime import datetime, timezone, timedelta
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("cyc", os.path.join(HERE, "analyze-cycle.py"))
cyc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cyc)
K = os.environ["PUBLIC_DATA_API_KEY"]
EP = "https://apis.data.go.kr/1741000/foreigner_city_homestays/info"


def fetch_all():
    rows, page, total = [], 1, None
    while True:
        for attempt in range(4):
            try:
                r = requests.get(EP, params={"serviceKey": K, "pageNo": page, "numOfRows": 1000, "returnType": "json"}, timeout=120)
                b = r.json()["response"]["body"]
                break
            except Exception as e:
                if attempt == 3:
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

    def agg(G):
        o = G[G["open"]]
        return {"open": int(len(o)), "rooms": int(o["rooms"].sum()) if o["rooms"].notna().any() else None, "total": int(len(G)),
                "new1y": int((G["lic"] >= y1).sum()), "new2y": int(((G["lic"] >= y2) & (G["lic"] < y1)).sum()), "closed1y": int((G["clo"] >= y1).sum())}
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
    print("== 영업중 상위 시군구 25 ==")
    for k, v in sorted(by_region.items(), key=lambda kv: -kv[1]["open"])[:25]:
        print(f"  {k}: 영업 {v['open']} · 신규1년 {v['new1y']} · 폐업1년 {v['closed1y']}")
    payload = {"generatedAt": now.isoformat(), "n": int(len(df)), "open": int(df["open"].sum()), "trend": trend, "byRegion": by_region, "byDong": by_dong}
    cyc.upsert_rows([{"id": "signal|__homestay__", "payload": cyc.clean_json(payload), "fetched_at": now.isoformat()}])
    print("✅ 저장 완료")


if __name__ == "__main__":
    main()
