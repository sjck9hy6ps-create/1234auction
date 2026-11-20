"""과거에 올린 탱크옥션 CSV들에서 사건번호 → 동(예: 106동) 표를 만들어 data/csv-dong.json에 저장.
경매물건에는 동이 저장되지 않은 채 들어간 사건이 있어서(공시가격 호별 연결에 필요), CSV 주소에 적힌 동을 따로 모아 둔다.
사용: python3 tools/csv-dong-map.py [CSV들이 있는 폴더(기본 ~/Downloads)]"""
import csv, glob, json, os, re, sys
src = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Downloads")
out = {}
def dong(line):
    s = re.sub(r"^.*?\d[\d-]*", "", line, 1)   # 지번 뒤쪽에서만 찾음
    m = re.search(r"(?:^|[\s,(])제?(\d{1,4})\s*동(?![가-힣])", s)
    return m.group(1) if m else None
for f in sorted(glob.glob(os.path.join(src, "탱크옥션*.csv"))):
    for r in csv.reader(open(f, encoding="utf-8-sig", errors="replace").read().splitlines()):
        if len(r) >= 3 and re.match(r"\d{4}-\d+$", r[0]) and r[1] == "아파트":
            d = dong(r[2])
            if d: out[r[0]] = d
os.makedirs("data", exist_ok=True)
json.dump(out, open("data/csv-dong.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(f"사건 {len(out):,}건의 동을 저장")
