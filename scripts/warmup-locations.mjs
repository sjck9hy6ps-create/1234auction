name: 전체 지역 좌표·건축물대장 웜업 (수동)
on:
  workflow_dispatch:      # 수동 실행 전용 - 자동 스케줄 없음
jobs:
  warmup:
    runs-on: ubuntu-latest
    timeout-minutes: 350
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: 의존성 설치
        run: npm install @supabase/supabase-js ws
      - name: 웜업 실행
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
          KAKAO_REST_API_KEY: ${{ secrets.KAKAO_REST_API_KEY }}
          SITE_URL: https://1234auction.vercel.app
        run: node scripts/warmup-locations.mjs
