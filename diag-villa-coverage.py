"""수도권 빌라(villa_trades) vs 아파트(house_trades) 실거래 적재량 - 연도별 건수 (2026-10-09, 빌라 로직 준비)"""
import os, requests
URL = os.environ["SUPABASE_URL"].rstrip("/")
K = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact", "Range": "0-0"}
def cnt(table, sido, y):
    p = {"select": "id", "region": f"like.{sido}*", "deal_date": f"gte.{y}0101"}
    r = requests.get(f"{URL}/rest/v1/{table}?deal_date=lt.{y+1}0101", headers=H, params=p, timeout=120)
    cr = r.headers.get("Content-Range", "*/0")
    return int(cr.split("/")[-1]) if cr.split("/")[-1].isdigit() else -1
print("연도별 건수 (아파트 / 빌라)")
for sido in ("서울", "인천", "경기"):
    print("==", sido)
    for y in range(2017, 2027):
        a, v = cnt("house_trades", sido, y), cnt("villa_trades", sido, y)
        print(f"  {y}: 아파트 {a:,} / 빌라 {v:,}" + (f"  (빌라÷아파트 {v / a:.2f})" if a > 0 else ""))
