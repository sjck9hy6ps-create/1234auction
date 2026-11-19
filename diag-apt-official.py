"""공시가격 결측 원인 점검(2026-11-20): VWorld 공동주택가격 응답의 필드(법정동명·단지명이 있는지)와, 인천 분구(2026-07) 지역의 옛 법정동코드를 찾는 방법을 확인. 읽기만 함."""
import os, json, requests
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app"); SEC = os.environ["COLLECT_PROXY_SECRET"].strip()
def vw(pnu, yr=2026, rows=2):
    r = requests.get(SITE + "/api/get-house", params={"action": "vworldProxy", "secret": SEC, "kind": "apt", "pnu": pnu, "stdrYear": str(yr), "format": "json", "numOfRows": str(rows), "pageNo": "1"}, timeout=60).json()
    j = json.loads(r.get("body", "{}")); f = None
    for v in j.values():
        if isinstance(v, dict) and "field" in v: f = v["field"]
    return (f if isinstance(f, list) else [f]) if f else []
print("== 정상 건물(일곡엘리체프라임 쪽 광주 북구 새 코드→옛 코드) 필드 확인")
for p in ["2917010800108350000", "1217010800108350000"]:
    f = vw(p); print(p, len(f), json.dumps(f[:1], ensure_ascii=False)[:700])
print("== 인천 연희동(알려진 매핑) 새 PNU / 옛 PNU")
for p in ["2827510400107120002", "2826010600107120002"]:
    f = vw(p); print(p, len(f), json.dumps(f[:1], ensure_ascii=False)[:700])
print("== 영종자이 2815510200115500000: 옛 시군구 후보 × 같은 법정동코드")
for sg in ["28110", "28140", "28200", "28260", "28710", "28720", "28155", "28125"]:
    p = sg + "10200" + "1" + "1550" + "0000"; f = vw(p); print(sg, len(f), json.dumps(f[:1], ensure_ascii=False)[:300] if f else "")
