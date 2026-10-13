"""VWorld 허가구역 레이어 점검(2026-10-14): LT_C_UQ141이 돌려주는 구역 종류(uname)·지정 정보를 알려진 지점에서 전부 확인 - 허가구역 외 구역(지구단위 등)이 섞이는지."""
import os, json, requests
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app"); SEC = os.environ["COLLECT_PROXY_SECRET"].strip()
def vw(kind, **params):
    r = requests.get(SITE + "/api/get-house", params={"action": "vworldProxy", "secret": SEC, "kind": kind, **params}, timeout=60).json()
    return json.loads(r.get("body", "{}"))
pts = {"강남 대치": (127.0576, 37.4946), "용산 한남": (127.0035, 37.5340), "안산 고잔": (126.8309, 37.3170), "부천 중동": (126.7767, 37.5049), "성남 분당 정자": (127.1086, 37.3670),
       "고양 일산 주엽": (126.7640, 37.6710), "인천 미추홀 주안": (126.6800, 37.4640), "인천 계양": (126.7377, 37.5371), "수원 영통": (127.0715, 37.2470), "대전 둔산": (127.3855, 36.3518), "부산 해운대": (129.1604, 35.1631), "화성 동탄": (127.0736, 37.2011)}
for nm, (x, y) in pts.items():
    j = vw("data", service="data", request="GetFeature", data="LT_C_UQ141", format="json", size="10", geomFilter=f"POINT({x} {y})", geometry="false", attribute="true", crs="EPSG:4326")
    fs = ((((j.get("response") or {}).get("result") or {}).get("featureCollection") or {}).get("features")) or []
    print("==", nm, "구역 수", len(fs))
    for f in fs: print("   ", json.dumps(f.get("properties"), ensure_ascii=False)[:300])
