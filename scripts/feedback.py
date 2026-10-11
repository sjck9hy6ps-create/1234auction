"""앱 안 '🛠 수정 요청'으로 접수된 요청을 읽고 처리 상태를 남김(키 필요 없음).
  python3 scripts/feedback.py list            접수·처리 중인 요청 보기(상황 정보 포함)
  python3 scripts/feedback.py list all        완료된 것까지 전부
  python3 scripts/feedback.py set <id> doing|done|hold ["답변 글"]   상태·답변 남김(앱의 '내 요청'에 보임)
"""
import sys, os, json, urllib.request
SITE = os.environ.get("SITE_URL", "https://1234auction.vercel.app")
U = f"{SITE}/api/auction?kind=feedback"
def load():
    return json.load(urllib.request.urlopen(urllib.request.Request(U, headers={"Cache-Control": "no-store"}), timeout=60))
KN = {"bug": "오류·멈춤", "slow": "느림", "wrong": "숫자·표시 이상", "feature": "기능 요청", "etc": "기타"}
cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
if cmd == "list":
    allf = len(sys.argv) > 2 and sys.argv[2] == "all"
    L = [x for x in load() if allf or x.get("status") in ("new", "doing", "hold")]
    L.sort(key=lambda x: x.get("at", ""))
    if not L: print("처리할 요청이 없어요."); sys.exit(0)
    for x in L:
        c = x.get("ctx") or {}; r = c.get("row") or {}
        print(f"── {x['id']} · {x.get('at','')[:16]} · {KN.get(x.get('kind'), x.get('kind'))} · 상태 {x.get('status')}")
        print("   " + str(x.get("text", "")).replace("\n", "\n   "))
        print(f"   [화면] {c.get('device','?')} {c.get('w')}x{c.get('h')} · 탭 {c.get('tab')} · 지역 {c.get('region') or '-'} · 보드 {'열림' if c.get('boardOpen') else '닫힘'}" + (f" · 물건 {r.get('caseNo')} {r.get('addr')} (추천가 {r.get('recBid')}, 시세 {r.get('sale')})" if r else ""))
        if c.get("errors"): print("   [최근 오류] " + " | ".join(c["errors"][-4:]))
        if x.get("reply"): print("   [답변] " + x["reply"])
elif cmd == "set":
    i, st = sys.argv[2], sys.argv[3]; reply = sys.argv[4] if len(sys.argv) > 4 else None
    it = [x for x in load() if x.get("id") == i]
    if not it: print("그 id가 없어요."); sys.exit(1)
    it = it[0]; it["status"] = st
    if reply: it["reply"] = reply
    it["updatedAt"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
    req = urllib.request.Request(U, data=json.dumps(it).encode(), headers={"Content-Type": "application/json"}, method="POST")
    print(urllib.request.urlopen(req, timeout=60).read().decode())
else:
    print(__doc__)
