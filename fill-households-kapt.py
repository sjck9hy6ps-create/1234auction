"""
🏢 건축물대장에서 세대수를 못 찾은 경매 아파트의 세대수를 K-apt 단지정보(kapt_complex_info)에서 채움 (2026-10-20)
- 대상: 경매물건 중 아파트이고 세대수가 비어 있는 것(건축물대장 조회가 한 번 실패하면 다시 묻지 않아 비어 있음 - 임장 후보 53건이 이 경우)
- 매칭: 같은 시군구(법정동코드 앞 5자리) + 단지명 정규화가 같은 K-apt 단지(세대수 있음). 같은 이름이 둘 이상이면 법정동으로 좁히고, 그래도 둘 이상이면 건너뜀(틀린 값 방지)
- 저장: households + householdsVer=2(단지 전체 기준) + householdsSource='K-apt' - 이미 있는 세대수는 건드리지 않음
- DRY=1 이면 저장 없이 매칭 결과만 출력
"""
import os, re, json, importlib.util
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("ab", os.path.join(HERE, "analyze-bidcases.py"))
ab = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ab)
avm = ab.avm
SITE = ab.SITE_URL
DRY = os.environ.get("DRY", "0") == "1"


def nm(x):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", avm.normalize_complex_name(x or "")).replace("아파트", "")


def main():
    kp = avm.fetch_all_rows("kapt_complex_info", cols="kapt_code,kapt_name,sigungu_code,as3,households", order_col="kapt_code", extra_filter="&households=gt.0")
    print(f"  K-apt 세대수 있는 단지 {len(kp):,}")
    idx = {}
    for r in kp.itertuples():
        idx.setdefault((str(r.sigungu_code), nm(r.kapt_name)), []).append((ab.dong_key(str(r.as3).strip().split()[-1] if r.as3 else ""), int(r.households), r.kapt_name))
    au = requests.get(f"{SITE}/api/auction", timeout=240).json()
    todo = [x for x in au if isinstance(x, dict) and x.get("propType") == "apt" and not (x.get("households") or 0) and x.get("bCode") and x.get("name")]
    print(f"  세대수 비어 있는 아파트 {len(todo):,}건")
    fixed, miss, amb = [], [], []
    for x in todo:
        key = (str(x["bCode"])[:5], nm(x["name"]))
        c = idx.get(key, [])
        if not c:
            miss.append(x); continue
        if len(c) > 1:
            dk = ab.dong_key(x.get("dong") or "")
            c2 = [t for t in c if t[0] == dk]
            if len(c2) == 1: c = c2
            else:
                amb.append(x); continue
        x2 = dict(x); x2["households"] = c[0][1]; x2["householdsVer"] = 2; x2["householdsSource"] = "K-apt"
        fixed.append(x2)
    print(f"  채울 수 있음 {len(fixed):,} / 이름 불일치 {len(miss):,} / 동명 여러 개 {len(amb):,}")
    for x in fixed[:15]: print("   ✔", x.get("name"), x.get("addr", "")[:30], "→", x["households"], "세대")
    for x in miss[:15]: print("   ✘ 못 찾음:", x.get("name"), "|", x.get("addr", "")[:30])
    summ = {"todo": len(todo), "fixed": len(fixed), "miss": len(miss), "ambiguous": len(amb)}
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write("### K-apt 세대수 채우기\n```json\n" + json.dumps(summ, ensure_ascii=False) + "\n```\n못 찾은 예: " + ", ".join(str(x.get("name")) for x in miss[:30]) + "\n")
    if DRY or not fixed:
        return
    ok = 0
    for i in range(0, len(fixed), 50):
        part = fixed[i:i + 50]
        for attempt in range(3):
            try:
                r = requests.post(f"{SITE}/api/auction", json=part, timeout=120)
                if r.status_code == 200:
                    ok += len(part); break
                print("   저장 실패", r.status_code, r.text[:200])
            except Exception as e:
                print("   저장 오류", e)
    print(f"  저장 {ok:,}/{len(fixed):,}건")


if __name__ == "__main__":
    main()
