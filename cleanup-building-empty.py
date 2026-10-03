"""2026-10 1회성 정리: building_info(건축물대장 캐시) 중 title_json이 비어 있는 행 삭제.
API 일일 한도 초과 오류가 '건물 없음'으로 180일 캐시됐던 행들(약 6만 건) - 캐시라 지워도 데이터 손실 없음,
다음 조회/웜업 때 다시 건축HUB에 물어봄(진짜로 건물이 없는 주소는 다시 '없음'으로 캐시됨)."""
import os, requests
URL = os.environ["SUPABASE_URL"].rstrip("/"); KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Prefer": "count=exact"}
r = requests.get(f"{URL}/rest/v1/building_info?select=id&order=id.desc&limit=1", headers=H, timeout=60); max_id = r.json()[0]["id"]
before = requests.get(f"{URL}/rest/v1/building_info?select=id&title_json=is.null&limit=1", headers=H, timeout=60).headers.get("content-range")
print("삭제 전 정보없음 행:", before, "최대 id", max_id)
step, total = 20000, 0
for lo in range(0, max_id + 1, step):
    d = requests.delete(f"{URL}/rest/v1/building_info?title_json=is.null&id=gte.{lo}&id=lt.{lo + step}", headers=H, timeout=300)
    d.raise_for_status()
    n = int((d.headers.get("content-range") or "*/0").split("/")[-1] or 0); total += n
print("삭제:", total)
print("삭제 후 정보없음 행:", requests.get(f"{URL}/rest/v1/building_info?select=id&title_json=is.null&limit=1", headers=H, timeout=60).headers.get("content-range"))
print("남은 전체:", requests.get(f"{URL}/rest/v1/building_info?select=id&limit=1", headers=H, timeout=60).headers.get("content-range"))
