#!/bin/sh
# 앱에 직접 올린 자료(경매물건·낙찰사례·임장메모·내 자산)는 Supabase가 아니라 Upstash Redis에 있어서 backup-full(Supabase)에 안 들어가요.
# 이 스크립트로 앱 주소에서 내려받아 PC에 보관하세요(키 필요 없음). 사용: sh scripts/backup-app-data.sh [폴더]
SITE=${SITE_URL:-https://1234auction.vercel.app}
OUT=${1:-backups/app-data-$(date +%Y%m%d)}
mkdir -p "$OUT"
for k in auctions bidCases siteNotes myAssets; do
  curl -s -m 180 "$SITE/api/auction?kind=$k" -o "$OUT/$k.json" -w "$k %{http_code} %{size_download}바이트\n"
done
echo "저장 위치: $OUT"
