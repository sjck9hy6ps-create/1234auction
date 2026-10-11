"""백업한 앱 자료(auctions.json 등)를 앱 저장소(Redis)에 다시 올림. 사용: python3 scripts/restore-app-data.py 백업폴더 [kind ...]
각 항목은 id로 덮어써요(없는 항목은 새로 추가, 백업에 없는 항목은 그대로). 200건씩 보냄."""
import sys, os, json, urllib.request
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
folder = sys.argv[1]; kinds = sys.argv[2:] or ["auctions", "bidCases", "siteNotes", "myAssets"]
for k in kinds:
    p = os.path.join(folder, k + ".json")
    if not os.path.exists(p): print(k, "파일 없음"); continue
    items = [x for x in json.load(open(p, encoding="utf-8")) if isinstance(x, dict) and x.get("id") is not None]
    for i in range(0, len(items), 200):
        req = urllib.request.Request(f"{SITE}/api/auction?kind={k}", data=json.dumps(items[i:i + 200]).encode(), headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=120).read()
    print(k, len(items), "건 올림")
