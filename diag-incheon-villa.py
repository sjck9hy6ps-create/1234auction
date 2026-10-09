"""인천 서해구 등 새 시군구의 빌라 매매 적재 진단 (2026-10-09) - region 라벨별·연도별 건수"""
import os, requests
URL = os.environ["SUPABASE_URL"].rstrip("/"); K = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Prefer": "count=exact", "Range": "0-0"}
def cnt(table, region, y0, y1):
    r = requests.get(f"{URL}/rest/v1/{table}", headers=H, timeout=120,
                     params={"select": "id", "region": f"eq.{region}", "deal_date": f"gte.{y0}0101"} | ({"and": f"(deal_date.lt.{y1}0101)"} if y1 else {}))
    cr = r.headers.get("Content-Range", "*/0").split("/")[-1]
    return int(cr) if cr.isdigit() else f"ERR{r.status_code}"
names = ["인천 서구", "인천 서해구", "인천 검단구", "인천 제물포구", "인천 미추홀구", "인천 중구", "인천 영종구", "인천 동구", "인천 부평구", "경기 부천시"]
for t in ("villa_trades", "house_trades", "villa_rent"):
    print("==", t)
    for n in names:
        print(f"  {n}: 2022~2024 {cnt(t, n, 2022, 2025)} / 2025 {cnt(t, n, 2025, 2026)} / 2026 {cnt(t, n, 2026, None)}")
# 서구/서해구 동 목록 샘플
for n in ("인천 서구", "인천 서해구"):
    r = requests.get(f"{URL}/rest/v1/villa_trades", headers={"apikey": K, "Authorization": "Bearer " + K}, timeout=60,
                     params={"select": "dong,deal_date", "region": f"eq.{n}", "order": "deal_date.desc", "limit": 3})
    print(n, "최근:", r.json() if r.ok else r.status_code)
