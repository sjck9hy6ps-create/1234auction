"""남은 공시가격 결측 심화 조사(읽기만 함): 접두 PNU 조회 가능 여부 · 인천 영종/여수 옛 코드 탐색 · 소형 건물 본번 조회."""
import os, json, requests
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app"); SEC = os.environ["COLLECT_PROXY_SECRET"].strip()
def vw(pnu, yr=2026, rows=3, kind="apt", extra=None):
    p = {"action": "vworldProxy", "secret": SEC, "kind": kind, "pnu": pnu, "stdrYear": str(yr), "format": "json", "numOfRows": str(rows), "pageNo": "1"}
    if extra: p.update(extra)
    try: r = requests.get(SITE + "/api/get-house", params=p, timeout=60).json(); j = json.loads(r.get("body", "{}"))
    except Exception as e: return [], None, str(e)[:80]
    f = None; tot = None
    for v in j.values():
        if isinstance(v, dict):
            if "field" in v: f = v["field"]
            if "totalCount" in v: tot = v["totalCount"]
    return ((f if isinstance(f, list) else [f]) if f else []), tot, ""
def show(tag, pnu, **k):
    f, tot, err = vw(pnu, **k); print(tag, pnu, "건수", len(f), "총", tot, err, json.dumps([(x.get("ldCodeNm"), x.get("aphusNm"), x.get("dongNm"), x.get("hoNm")) for x in f[:2]], ensure_ascii=False)[:260], flush=True)
print("== 접두 PNU(법정동·본번까지) 조회가 되는지 - 부산 반여동 1405-33 / 성북 정릉동 508-123 / 거제 옥포동 555-6")
for base in ["2635010300114050033", "1129013300105080123", "4831010600105550006"]:
    for n in (10, 11, 15, 17): show("접두%d" % n, base[:n])
    show("부번0", base[:15] + "0000")
print("== 영종힐스테이트 중산동 1887-2: 시군구×법정동 탐색(응답 법정동명이 중산동인 것)")
for sg in ["28155", "28110", "28140", "28200", "28710", "28720", "28245"]:
    for bj in range(10100, 15100, 100):
        f, tot, err = vw(sg + str(bj) + "1" + "1887" + "0002", rows=1)
        if f: print("  발견", sg, bj, f[0].get("ldCodeNm"), f[0].get("aphusNm"), flush=True)
print("== 여수 봉계동 16 아주타운: 시군구×법정동 탐색")
for sg in ["46130", "12130", "29110", "46110"]:
    for bj in range(10100, 16100, 100):
        f, tot, err = vw(sg + str(bj) + "1" + "0016" + "0000", rows=1)
        if f: print("  발견", sg, bj, f[0].get("ldCodeNm"), f[0].get("aphusNm"), flush=True)
print("== 건축·다세대 등 다른 종류(kind) 확인: 성북구 정릉동 508-123를 land/데이터로")
show("land", "1129013300105080123", kind="land")
