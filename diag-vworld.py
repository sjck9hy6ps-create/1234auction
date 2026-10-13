"""VWorld 점검(2026-10-13): ① 개별공시지가 API가 우리 키로 되는지 ② 정비구역(재개발·재건축) 레이어가 어떤 이름인지 후보 레이어를 알려진 정비구역 좌표로 찔러 봄."""
import os, json, requests
KEY = os.environ["VWORLD_API_KEY"].strip(); DOM = os.environ.get("VWORLD_DOMAIN", "1234auction.vercel.app")
r = requests.get("https://api.vworld.kr/ned/data/getIndvdLandPriceAttr", params={"key": KEY, "domain": DOM, "pnu": "1117011900100050254", "stdrYear": "2025", "format": "json", "numOfRows": "5"}, timeout=30)
print("개별공시지가", r.status_code, r.text[:600])
pts = {"한남3구역": (127.0035, 37.5340), "성수전략": (127.0432, 37.5424), "증산5구역": (126.9115, 37.5835), "노량진": (126.9438, 37.5106)}
cand = [f"LT_C_UPISUQ{n}" for n in range(111, 200, 1)] + ["LT_C_UQ111", "LT_C_UQ112", "LT_C_UQ113", "LT_C_UQ114", "LT_C_UQ121", "LT_C_UQ122", "LT_C_UQ123", "LT_C_UQ124", "LT_C_UQ125", "LT_C_UQ126", "LT_C_UQ127", "LT_C_UQ128", "LT_C_UQ129", "LT_C_UQ130", "LT_C_UQ141", "LT_C_UD801", "LT_C_UD610", "LT_C_UD620", "LT_C_UPISUQ161"]
seen = set()
for L in cand:
    for nm, (x, y) in pts.items():
        try:
            r = requests.get("https://api.vworld.kr/req/data", params={"service": "data", "request": "GetFeature", "data": L, "key": KEY, "domain": DOM, "format": "json", "size": "3", "geomFilter": f"POINT({x} {y})", "geometry": "false", "attribute": "true", "crs": "EPSG:4326"}, timeout=30)
            j = r.json(); st = (j.get("response") or {}).get("status")
            fs = ((((j.get("response") or {}).get("result") or {}).get("featureCollection") or {}).get("features")) or []
            if st == "OK" and fs and L not in seen:
                seen.add(L); print("레이어", L, nm, json.dumps(fs[0].get("properties"), ensure_ascii=False)[:420])
            elif st not in ("OK", "NOT_FOUND") and L not in seen:
                seen.add(L); print("레이어", L, "상태", st, str(j)[:160])
        except Exception as e:
            pass
print("끝")
