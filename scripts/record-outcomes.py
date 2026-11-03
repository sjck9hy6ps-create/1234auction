#!/usr/bin/env python3
"""매주 입찰 결과 반영 (2026-11-03)

탱크옥션에서 받은 CSV(~/Downloads/탱크옥션 *.csv)를 읽어 낙찰사례(kind=bidCases)의 결과를 정리한다.
기본은 "미리보기"(앱 데이터를 바꾸지 않음). --apply 를 붙여야 저장하고, 저장 전에 바뀔 레코드의 원본을 backups/ 에 남긴다.

CSV 한 줄 = 사건 1건 (헤더: 사건번호,종별,주소(시군구동),외 건수,경매현황,감정가,최저가,매각가,차순위,입찰자수,진행상태,입찰일자)
  - 진행상태가 '매각…'            → 낙찰 (앱에 낙찰로 이미 있으면 건너뜀, 없으면 보고만 함 - 낙찰 추가는 앱 화면의 업로드로)
  - 변경/연기/취하/취소/기각/각하/정지/불허가/허가취소/이송/미진행/기타 등 → 입찰 안 열림·종료
        · 앱에 '결과 미확인'으로 있으면 상태를 CSV 값으로 고침(prevStatus·outcomeFromCsv 보관)
        · 앱에 낙찰로 있는데 불허가·허가취소·기각이면 courtDenied 표시(낙찰가·상태는 그대로)
  - 진행상태가 '신건'/'유찰 N회'  → 입찰예정 목록(다음 주 물건). 결과가 아니라 ① 유찰 추정이던 건의 확정(다음 기일로 다시 올라옴) 검증에만 씀

소거법(--estimate-failed): 입찰일 구간에서 낙찰도 종료도 아닌 아파트 기록을 outcomeEst='유찰(추정)'로 표시.
  ⚠️ 상태 파일이 하나라도 빠지면 그 상태의 사건이 유찰로 잘못 기록된다. 비율로 짐작하지 않고 "상태 이름과 건수"를 정확히 맞춘 뒤에만 저장한다
  (하나라도 맞지 않으면 유찰(추정)은 저장하지 않음. --force 로만 무시 가능·기록됨):
   G. 상태 이름: CSV의 진행상태가 아는 이름(신건·유찰 N회·매각…·변경·연기·취하·취소·기각·각하·정지·불허가·허가취소·이송·미진행·기타·종국·모사건종결·배당종결)이 아니면 중단(오타·새 상태)
   H. 상태별 건수: --tank-counts "매각전부=1218,변경/연기=162,취하=95,취소=0,기각=50,각하=0,정지=6,불허가/허가취소=22,이송=0,미진행=1,기타=0"
      처럼 탱크옥션 조회 화면의 총 건수(같은 입찰일 구간, 아파트)를 11개 상태 모두 적어야 하고, 읽은 고유 건수와 하나라도 다르면 중단
      (상태 이름 오타·빠진 상태·잘린 파일·중복 모두 여기서 걸림). 건수 표시가 없는 화면이면 --empty-states 로 0건인 상태 이름만 적는 대체 방법
   C. 100건 한도: 정확히 100건인 파일이 이어지는 파일 없이 끝나면 잘렸을 수 있음
   A. 날짜별 낙찰 파일: 결과 미확인 사건이 5건 이상인데 그 날 낙찰 행이 0건이면 낙찰 파일 누락
   F. 표본 점검표(backups/outcome-spotcheck-*.csv): 유찰(추정) 10건을 탱크옥션에서 직접 확인할 수 있게 뽑아 줌(--spotcheck-ok 를 주면 확인했다고 기록)
  매칭은 사건번호+동·번지+입찰일(+면적)에 감정가·최저가까지 같아야 인정(다른 법원의 같은 사건번호 오매칭 방지).
  저장하든 안 하든 사건마다 최종 상태·근거 파일을 backups/outcome-ledger-*.csv 에 남김.
  입찰일 이틀 이후에 받는 게 안전(결과 반영 지연).

사용 예
  python3 scripts/record-outcomes.py                       # 최근 3일 안에 받은 파일 미리보기
  python3 scripts/record-outcomes.py --apply               # 낙찰·종료·불허가·중복 반영
  python3 scripts/record-outcomes.py --apply --estimate-failed --tank-counts "매각전부=...,변경/연기=...,..." --spotcheck-ok   # + 유찰(추정) 표시
  python3 scripts/record-outcomes.py --dir ~/Downloads --hours 120 --from 2026-11-02 --to 2026-11-06
"""
import argparse, collections, csv, glob, json, os, re, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

SITE = (os.environ.get("SITE_URL") or "https://1234auction.vercel.app").rstrip("/")
CLOSED_RE = re.compile(r"^(변경|연기|취하|취소|기각|각하|정지|불허가|허가취소|이송|종국|모사건종결|미진행|기타|배당종결|결정변경)")
DENY_RE = re.compile(r"^(불허가|허가취소|기각)")
FAIL_RE = re.compile(r"유찰\s*(\d+)\s*회")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def norm_case(s):
    return str(s or "").replace("타경", "-").replace(" ", "")


def addr_key(addr):
    m = re.search(r"([가-힣0-9]+(?:동|리|가))\s+(산?\d+(?:-\d+)?)", str(addr or ""))
    return (m.group(1), m.group(2).replace("산", "")) if m else None


def area_of(r):
    m = re.search(r"건물\s*([\d.]+)㎡", r.get("경매현황", "") or "")
    return float(m.group(1)) if m else None


def fetch_json(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def fetch_bidcases():
    base = SITE + "/api/auction?withVer=1&kind=bidCases"
    cur, out, seen = "0", [], set()
    for _ in range(200):
        d = fetch_json(base + "&cursor=" + cur)
        for x in d["list"]:
            if x["id"] not in seen:
                seen.add(x["id"]); out.append(x)
        if not d.get("next"):
            break
        cur = d["next"]
    return out


def read_csvs(files):
    rows, per = [], []
    for f in sorted(files):
        raw = open(f, "rb").read()
        try:
            t = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            t = raw.decode("cp949")
        lines = t.splitlines()
        if len(lines) < 2 or "사건번호" not in lines[1]:
            continue
        rd = list(csv.DictReader(lines[1:]))
        per.append((os.path.basename(f), len(rd), collections.Counter(r.get("진행상태", "") for r in rd)))
        for r in rd:
            r["_f"] = os.path.basename(f); rows.append(r)
    uniq, changed = {}, []
    for r in rows:   # 파일 이름이 받은 시각 순이라 나중 파일이 최신 상태 → 같은 사건이 다시 나오면 최신으로 덮음
        k = (r.get("사건번호"), r.get("입찰일자"), r.get("주소(시군구동)"))   # 탱크옥션 한 줄 = 한 건(사건번호 표기 그대로 구분)
        if k in uniq and uniq[k]["진행상태"] != r["진행상태"]:
            changed.append((k[0], k[1], uniq[k]["진행상태"], r["진행상태"], uniq[k]["_f"], r["_f"]))
        uniq[k] = r
    read_csvs.changed = changed
    return list(uniq.values()), per


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=os.path.expanduser("~/Downloads"))
    ap.add_argument("--hours", type=float, default=72, help="이 시간 안에 받은 파일만 읽음(기본 72)")
    ap.add_argument("--from", dest="d_from"); ap.add_argument("--to", dest="d_to")
    ap.add_argument("--apply", action="store_true", help="실제로 저장(기본은 미리보기)")
    ap.add_argument("--estimate-failed", action="store_true", help="나머지를 유찰(추정)으로 표시(아래 점검을 통과해야 저장됨)")
    ap.add_argument("--tank-counts", default="", help='상태별 탱크옥션 조회 총 건수. 예: "매각전부=1218,변경/연기=162,취하=95,취소=0,..." (11개 상태 모두)')
    ap.add_argument("--empty-states", default="", help="(건수 표시가 없을 때 대체) 조회 결과가 0건이었던 상태 이름(쉼표). 예: 취소,각하,이송,기타")
    ap.add_argument("--spotcheck-ok", action="store_true", help="표본 점검표 10건을 탱크옥션에서 직접 확인했음")
    ap.add_argument("--dry-test-unmarked", action="store_true", help="(시험용·저장 안 함) 이미 표시된 기록도 미표시로 보고 점검만 돌려 봄")
    ap.add_argument("--force", action="store_true", help="점검 실패를 무시(기록됨) - 권장하지 않음")
    a = ap.parse_args()

    today = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")
    files = [f for f in glob.glob(os.path.join(a.dir, "탱크옥션 *.csv")) if os.path.getmtime(f) > time.time() - a.hours * 3600]
    if not files:
        print("읽을 CSV가 없어요 (최근 %g시간 안에 받은 '탱크옥션 *.csv')" % a.hours); return 1
    rows, per = read_csvs(files)
    print(f"📂 파일 {len(per)}개, 고유 {len(rows)}건")
    for n, c, st in per:
        print(f"   {n[-18:]}  {c:>4}건  {dict(st.most_common(4))}")
    for r in rows:
        r["_d"] = r.get("입찰일자", "")[:10]
    # 종류 구분
    sold_rows = [r for r in rows if r["진행상태"].startswith("매각")]
    closed_rows = [r for r in rows if CLOSED_RE.match(r["진행상태"])]
    upcoming = [r for r in rows if r["진행상태"].startswith("신건") or FAIL_RE.search(r["진행상태"])]
    other = [r for r in rows if r not in sold_rows and r not in closed_rows and r not in upcoming]
    print(f"   낙찰 {len(sold_rows)} · 종료(취하·변경 등) {len(closed_rows)} · 입찰예정 목록 {len(upcoming)} · 분류 못 한 상태 {len(other)}")
    if other:
        print("   ⚠️ 분류 못 한 상태:", dict(collections.Counter(r['진행상태'] for r in other)))
    if getattr(read_csvs, "changed", None):
        print(f"   🔁 받은 시점에 따라 상태가 달라진 사건 {len(read_csvs.changed)}건(최신 파일 기준 사용): " + "; ".join(f"{c[0]} {c[1]} {c[2]}→{c[3]}" for c in read_csvs.changed[:5]) + (" …" if len(read_csvs.changed) > 5 else ""))
        print("      → 건수 대조는 모든 파일을 같은 시점에 받았을 때 가장 정확해요(낙찰 직후 불허가로 바뀌는 건이 있어요)")
    out_rows = sold_rows + closed_rows
    if not out_rows and not upcoming:
        print("결과·예정 어느 쪽도 없어요"); return 1
    dates = sorted({r["_d"] for r in out_rows if r["_d"] and r["_d"] <= today})
    d_from = a.d_from or (dates[0] if dates else None)
    d_to = min(a.d_to or (dates[-1] if dates else today), (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"))
    if dates:
        print(f"📅 결과 구간(입찰일): {d_from} ~ {d_to}  (오늘 {today} 이전만)")

    B = fetch_bidcases()
    print(f"🗂  낙찰사례 {len(B):,}건 (낙찰 {sum(1 for b in B if b['status']=='매각'):,})")
    by_case = collections.defaultdict(list)
    for b in B:
        by_case[norm_case(b["caseNo"])].append(b)

    def find(r, same_date=True):
        k = addr_key(r.get("주소(시군구동)"))
        if not k:
            return None, "주소 해석 불가"
        c = [b for b in by_case.get(norm_case(r["사건번호"]), []) if b.get("dong") == k[0] and str(b.get("bunji", "")).replace(" ", "") == k[1]]
        if same_date:
            c = [b for b in c if b.get("saleDate") == r["_d"]]
        if len(c) > 1:  # 같은 건물 여러 호수 → 면적으로 좁힘
            ar = area_of(r)
            if ar:
                c2 = [b for b in c if b.get("areaM2") and abs(float(b["areaM2"]) - ar) < 0.5]
                if c2:
                    c = c2
        if len(c) == 1:
            b = c[0]
            def num(x):
                x = str(x or "").replace(",", "").strip(); return int(x) if x.isdigit() else None
            for ck, bk in (("감정가", "appraisalPrice"), ("최저가", "minBidPrice")):
                cv, bv = num(r.get(ck)), b.get(bk)
                if cv and bv and abs(cv - float(bv)) > 1 and ck == "감정가":   # 감정가는 회차가 바뀌어도 그대로 → 다르면 다른 사건(다른 법원 같은 번호)
                    return None, f"감정가 불일치(CSV {cv:,} / 앱 {int(bv):,}) - 다른 사건일 수 있어 매칭 안 함"
            return b, None
        return None, ("없음" if not c else f"{len(c)}건 모호")

    changes = {}      # id → 새 레코드
    originals = {}
    log = collections.defaultdict(list)

    def edit(b):
        if b["id"] not in changes:
            originals[b["id"]] = dict(b); changes[b["id"]] = dict(b)
        return changes[b["id"]]

    # ① 종료(취하·변경 등)
    for r in closed_rows:
        if r["_d"] > today:
            continue
        b, why = find(r)
        if not b:
            log["종료-앱에 없음/모호" + (":" + why if why not in ("없음",) else "")].append(r["사건번호"]); continue
        if b["status"] == "매각":
            if DENY_RE.match(r["진행상태"]) and not b.get("courtDenied"):
                n = edit(b); n["courtDenied"] = {"result": r["진행상태"], "csvSoldPrice": r.get("매각가"), "at": today}; log["낙찰 후 불허가·취소 표시"].append(r["사건번호"])
            else:
                log["낙찰로 있는데 CSV는 종료(이미 표시/해당 없음)"].append(r["사건번호"])
        elif b["status"] == r["진행상태"] or b.get("prevStatus"):
            log["이미 반영됨"].append(r["사건번호"])
        else:
            n = edit(b); n["prevStatus"] = b["status"]; n["status"] = r["진행상태"]
            n["outcomeFromCsv"] = {"status": r["진행상태"], "saleDate": r["_d"], "minBid": r.get("최저가"), "at": today}
            n.pop("outcomeEst", None); log["종료로 고침(" + r["진행상태"] + ")"].append(r["사건번호"])

    # ② 낙찰 확인(앱에 없거나 낙찰가 다른 것은 보고만)
    for r in sold_rows:
        b, why = find(r)
        if not b:
            log["낙찰-앱에 없음/모호(앱 화면의 낙찰사례 업로드로 추가)"].append(r["사건번호"]); continue
        if b["status"] != "매각":
            log["⚠️ 낙찰인데 앱 기록은 낙찰 아님(상태 확인 필요)"].append(r["사건번호"])
        elif r.get("매각가", "").isdigit() and b.get("finalBidPrice") and abs(int(r["매각가"]) - b["finalBidPrice"]) > 1:
            log["⚠️ 낙찰가 앱과 다름"].append(r["사건번호"])

    # ③ 소거법 유찰(추정) - 점검 A~F 통과 필요
    problems, notes = [], []
    if a.estimate_failed and d_from:
        sold_idx = collections.defaultdict(list)
        for b in B:
            if b["status"] == "매각":
                sold_idx[norm_case(b["caseNo"])].append(b)
        cand = []
        for b in B:
            if "아파트" not in str(b.get("propertyType")) or not (d_from <= (b.get("saleDate") or "") <= d_to):
                continue
            if b["status"] == "매각" or (not a.dry_test_unmarked and (CLOSED_RE.match(str(b["status"])) or b.get("prevStatus") or b.get("outcomeEst") or b.get("dupOfSold"))):
                continue
            if b["id"] in changes and changes[b["id"]].get("prevStatus"):
                continue
            cand.append(b)
        # --- 점검 ---
        sold_by_date = collections.Counter(r["_d"] for r in sold_rows if d_from <= r["_d"] <= d_to)
        cand_by_date = collections.Counter(b["saleDate"] for b in cand)
        for d, n in sorted(cand_by_date.items()):
            if n >= 5 and sold_by_date.get(d, 0) == 0:
                problems.append(f"A. {d}: 결과 미확인 {n}건인데 그 날 낙찰 행이 0건 → 그 날 '매각전부' 파일이 빠졌을 수 있어요")
        n_sold = sum(sold_by_date.values()); base = json.load(open(os.path.join(ROOT, "scripts", "outcome-baseline.json"), encoding="utf-8"))
        # G: 상태 이름 정확성 - 아는 이름만 허용
        known = re.compile(r"^(신건|유찰\s*\d+\s*회|매각|변경|연기|취하|취소|기각|각하|정지|불허가|허가취소|이송|미진행|기타|종국|모사건종결|배당종결|결정변경)")
        bad = collections.Counter(r["진행상태"] for r in rows if not known.match(r["진행상태"]))
        if bad:
            problems.append("G. 모르는 상태 이름(오타·새 상태): " + ", ".join(f"'{k}' {v}건" for k, v in bad.items()))
        # H: 상태별 건수 대조(구간 안 고유 사건)
        group = {"매각전부": lambda st: st.startswith("매각"), "변경/연기": lambda st: st.startswith(("변경", "연기")), "취하": lambda st: st.startswith("취하"),
                 "취소": lambda st: st.startswith("취소"), "기각": lambda st: st.startswith("기각"), "각하": lambda st: st.startswith("각하"), "정지": lambda st: st.startswith("정지"),
                 "불허가/허가취소": lambda st: st.startswith(("불허가", "허가취소")), "이송": lambda st: st.startswith("이송"), "미진행": lambda st: st.startswith("미진행"), "기타": lambda st: st.startswith("기타")}
        got = {k: sum(1 for r in rows if d_from <= r["_d"] <= d_to and f(r["진행상태"])) for k, f in group.items()}
        if a.tank_counts.strip():
            want = {}
            for part in a.tank_counts.split(","):
                if "=" not in part:
                    problems.append(f"H. --tank-counts 형식 오류: '{part}' (상태=건수)"); continue
                k, v = part.split("=", 1); k = k.strip()
                if k not in group:
                    problems.append(f"H. --tank-counts 의 상태 이름 '{k}' 이(가) 목록에 없어요(오타?). 사용 가능: " + ", ".join(group)); continue
                if not v.strip().isdigit():
                    problems.append(f"H. '{k}' 건수가 숫자가 아니에요: '{v}'"); continue
                want[k] = int(v)
            for k in group:
                if k not in want:
                    problems.append(f"H. 상태 '{k}' 의 탱크옥션 총 건수가 빠졌어요(0건이면 {k}=0)")
                elif want[k] != got[k]:
                    problems.append(f"H. 상태 '{k}': 탱크옥션 {want[k]}건 ↔ 읽은 {got[k]}건 (차이 {got[k]-want[k]:+d}) → 파일 누락·잘림·중복·상태 이름 확인")
        else:
            empty = {x.strip() for x in a.empty_states.split(",") if x.strip()}
            miss = [k for k in group if got[k] == 0 and not (empty & {k, k.split("/")[0], k.split("/")[-1]})]
            if miss:
                problems.append("H. 행이 없는 상태: " + ", ".join(miss) + " → 탱크옥션 화면의 총 건수를 --tank-counts 로 적거나(권장), 조회 결과가 0건이었으면 --empty-states 에 이름을 직접 적어 주세요")
            else:
                notes.append("H. (대체 방법) 건수 대조 없이 행이 있는 상태·선언한 0건 상태만 확인했어요 - --tank-counts 로 건수까지 맞추는 걸 권장")
        notes.append("   읽은 상태별 건수: " + ", ".join(f"{k} {v}" for k, v in got.items()))
        trunc = [(n, c) for n, c, st in per if c == 100]
        for n, c in trunc:
            f_rows = [r for r in rows if r["_f"] == n]
            ends = {min((r["_d"] for r in f_rows), default=""), max((r["_d"] for r in f_rows), default="")}  # 100건씩 쪽을 나눠 받으면 한쪽 끝 날짜가 다음 파일로 이어짐
            cont = any(r["_f"] != n and r["_d"] in ends for r in rows)
            if not cont:
                problems.append(f"C. {n[-18:]}: 정확히 100건이고 이어지는 파일이 없어요 → 100건 한도로 잘렸을 수 있어요(날짜를 나눠 다시 받으세요)")
        seen = set(re.sub(r"\s.*", "", r["진행상태"]) for r in closed_rows if d_from <= r["_d"] <= d_to)
        empty = {x.strip() for x in a.empty_states.split(",") if x.strip()}
        alias = {"매각전부": {"매각"}, "변경/연기": {"변경", "연기"}, "불허가/허가취소": {"불허가", "허가취소"}}
        miss = []
        for x in base["requiredStates"]:
            names = alias.get(x, {x})
            have = (n_sold > 0) if x == "매각전부" else bool(seen & names)
            if not have and not (empty & (names | {x, x.split("/")[0]})):
                miss.append(x)
        if miss:
            problems.append("D. 이번 구간에 행이 없는 상태: " + ", ".join(miss) + " → 탱크옥션에서 조회했을 때 0건이었으면 --empty-states " + ",".join(x.split('/')[0] for x in miss) + " 로 직접 적어 주세요(안 받은 거라면 먼저 받으세요)")
        # F 표본 점검표
        import random
        rnd = random.Random(d_to); pick = rnd.sample(cand, min(10, len(cand)))
        sc = os.path.join(ROOT, "backups", f"outcome-spotcheck-{today}.csv"); os.makedirs(os.path.dirname(sc), exist_ok=True)
        with open(sc, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh); w.writerow(["사건번호", "입찰일", "주소", "앱 최저가(원)", "탱크옥션에서 확인할 것: 이 입찰일에 유찰이 맞는지"])
            for b in pick:
                w.writerow([b["caseNo"], b["saleDate"], b.get("addrJibun"), b.get("minBidPrice"), ""])
        notes.append("F. 표본 점검표: " + os.path.relpath(sc, ROOT) + " (10건 - 탱크옥션 기일내역에서 유찰인지 확인 후 --spotcheck-ok)")
        if not a.spotcheck_ok:
            problems.append("F. 표본 점검표 10건을 확인하지 않았어요(확인했다면 --spotcheck-ok)")
        if problems and not a.force:
            print("\n⛔ 유찰(추정) 표시 점검 실패 - 이 부분은 저장하지 않아요:")
            for pr in problems: print("   ", pr)
            for nt in notes: print("   ", nt)
            cand = []
        elif not problems:
            print("\n✅ 유찰(추정) 저장 점검 통과")
            for nt in notes: print("   ", nt)
        elif problems and a.force:
            print("\n⚠️ --force: 아래 점검 실패를 무시하고 진행(기록에 남김)")
            for pr in problems: print("   ", pr)
        for b in cand:
            dup = [x for x in sold_idx.get(norm_case(b["caseNo"]), []) if x.get("dong") == b.get("dong") and str(x.get("bunji", "")).replace(" ", "") == str(b.get("bunji", "")).replace(" ", "") and x["saleDate"] == b["saleDate"]]
            n = edit(b)
            if dup:
                n["dupOfSold"] = {"ids": [x["id"] for x in dup][:5], "note": "같은 사건·동·번지·입찰일의 낙찰 기록이 따로 있어 유찰 추정에서 제외", "at": today}; log["중복(낙찰 기록 따로 있음)"].append(b["caseNo"])
            else:
                n["outcomeEst"] = {"result": "유찰(추정)", "basis": f"입찰일 {d_from}~{d_to} 낙찰·종료 CSV 어디에도 없음(소거법)", "at": today,
                                   "checks": ("force" if problems else "통과"), "spotChecked": bool(a.spotcheck_ok)}; log["유찰(추정) 표시"].append(b["caseNo"])
    elif not a.estimate_failed:
        log["(참고) 유찰(추정)은 --estimate-failed 를 줘야 표시"].append("-")

    # ④ 유찰(추정) → 확정: 다음 기일(더 늦은 입찰일)에 '유찰 N회'(N이 이전보다 큼)로 다시 올라온 건
    conf = 0
    if upcoming:
        up_idx = collections.defaultdict(list)
        for r in upcoming:
            k = addr_key(r.get("주소(시군구동)"))
            if k:
                up_idx[(norm_case(r["사건번호"]), k)].append(r)
        for b in B:
            e = b.get("outcomeEst")
            if not e or e.get("result") != "유찰(추정)":
                continue
            prev = FAIL_RE.search(str(b["status"])); pf = int(prev.group(1)) if prev else 0
            for r in up_idx.get((norm_case(b["caseNo"]), (b.get("dong"), str(b.get("bunji", "")).replace(" ", ""))), []):
                m = FAIL_RE.search(r["진행상태"])
                if r["_d"] > b["saleDate"] and m and int(m.group(1)) > pf:
                    n = edit(b); n["outcomeEst"] = dict(e, result="유찰(확정)", confirmedBy={"nextSaleDate": r["_d"], "status": r["진행상태"], "minBid": r.get("최저가"), "at": today}); conf += 1; break
        if conf:
            log["유찰(추정)→유찰(확정)"].append(f"{conf}건")

    os.makedirs(os.path.join(ROOT, "backups"), exist_ok=True)
    led = os.path.join(ROOT, "backups", f"outcome-ledger-{today}.csv")
    with open(led, "w", encoding="utf-8-sig", newline="") as fh:   # 사건마다 어떤 조치를 했는지(감사용)
        w = csv.writer(fh); w.writerow(["조치", "사건번호"])
        for k, v in log.items():
            if k.startswith("(참고)"):
                continue
            for cn in v:
                w.writerow([k, cn])
    print("\n📒 조치 내역:", os.path.relpath(led, ROOT))
    print("\n━━ 결과 ━━")
    for k, v in log.items():
        print(f"  {k}: {len(v) if v != ['-'] else ''}" + (f"  예) {', '.join(v[:3])}" if v and v != ['-'] and len(v) else ""))
    if a.dry_test_unmarked:
        print("(시험용 실행 - 저장하지 않아요)"); return 0
    print(f"\n바뀔 레코드: {len(changes)}건")
    if not changes:
        print("바꿀 게 없어요."); return 0
    if not a.apply:
        print("미리보기만 했어요. 저장하려면 --apply 를 붙이세요."); return 0

    os.makedirs(os.path.join(ROOT, "backups"), exist_ok=True)
    bk = os.path.join(ROOT, "backups", f"bidcases-record-outcomes-before-{today}-{int(time.time())}.json")
    json.dump(list(originals.values()), open(bk, "w", encoding="utf-8"), ensure_ascii=False)
    print("💾 백업:", os.path.relpath(bk, ROOT))
    arr = list(changes.values()); saved = 0
    for i in range(0, len(arr), 100):
        r = fetch_json(SITE + "/api/auction?kind=bidCases", json.dumps(arr[i:i + 100], ensure_ascii=False).encode())
        saved += int(r.get("saved", 0))
    print(f"✅ 저장 {saved}/{len(arr)}건")
    B2 = fetch_bidcases()
    ok = len(B2) == len(B) and sum(1 for b in B2 if b["status"] == "매각") == sum(1 for b in B if b["status"] == "매각")
    print(f"🔎 저장 후 확인: 전체 {len(B2):,}건(전 {len(B):,}) · 낙찰 {sum(1 for b in B2 if b['status']=='매각'):,}건 → " + ("건수 변동 없음 ✅" if ok else "⚠️ 건수가 달라졌어요 - 백업으로 확인 필요"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
