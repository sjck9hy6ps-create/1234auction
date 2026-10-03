"""K-apt 세대수 수집 진단(읽기 위주) - 2026-10. 수집 현황과 상세조회 원본 응답을 출력만 함."""
import os, json, importlib.util
spec = importlib.util.spec_from_file_location("sk", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sync-kapt.py"))
sk = importlib.util.module_from_spec(spec); spec.loader.exec_module(sk)
import requests
H = {**sk.SB_HEADERS, "Prefer": "count=exact"}
def cnt(q):
    r = requests.get(f"{sk.SUPABASE_URL}/rest/v1/kapt_complex_info?{q}&select=kapt_code&limit=1", headers=H, timeout=60)
    return r.headers.get("content-range")
print("전체 행:", cnt("kapt_code=not.is.null"))
print("세대수 있음:", cnt("households=not.is.null"))
print("세대수 없음:", cnt("households=is.null"))
for code in ["11680", "26350", "12140", "41117", "44200"]:
    print(code, "전체", cnt(f"sigungu_code=eq.{code}"), "세대수있음", cnt(f"sigungu_code=eq.{code}&households=not.is.null"))
rows = sk.sb_get("kapt_complex_info?households=is.null&select=kapt_code,kapt_name,sigungu_code,updated_at&limit=3")
print("세대수 없는 예:", rows)
for r in rows[:2]:
    try:
        body = sk.kapt_get(sk.KAPT_BASS_BASE, "getAphusBassInfoV5", {"kaptCode": r["kapt_code"]})
        print("상세 원본:", json.dumps(body, ensure_ascii=False)[:1500])
    except Exception as e:
        print("상세 실패:", e)
ok = sk.sb_get("kapt_complex_info?households=not.is.null&select=kapt_code,kapt_name,sigungu_code,as3,households&limit=3")
print("세대수 있는 예:", ok)
