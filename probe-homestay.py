"""도시민박업 API 응답 형식 확인 (2026-10-09) - 키는 출력하지 않음"""
import os, json, requests
K = os.environ["PUBLIC_DATA_API_KEY"]
EP = "https://apis.data.go.kr/1741000/foreigner_city_homestays/info"
for params in ({"pageNo": 1, "numOfRows": 3, "returnType": "json"}, {"pageNo": 1, "numOfRows": 3}):
    try:
        r = requests.get(EP, params={"serviceKey": K, **params}, timeout=60)
        print("status", r.status_code, "params", list(params))
        print(r.text[:2500].replace(K, "***"))
    except Exception as e:
        print("ERR", str(e).replace(K, "***")[:300])
