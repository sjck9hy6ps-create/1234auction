---
name: board-precompute
description: 입찰후보 로딩 속도 해결책(2026-10-10): 가상 브라우저 사전 계산 + 화면 반응 개선, 운영 방법
metadata:
  type: project
---

문제: 입찰후보를 처음 열면(업로드 직후·계산 버전 변경 후) 지역 100~179곳을 받아 계산해 수 분 걸리고 클릭이 씹힘.
해결: scripts/precompute-board.mjs(playwright, workflow precompute-board.yml, 매일 KST 05:30 + 월 08:00 + 수동)가 앱을 열어 forceRefreshBidBoard로 계산(약 5분) → 저장 계산을 Supabase leader_follower_cache 'board|cache|meta'·'board|cache|0..N'에 올림. 앱(mergeServerBoardCache)은 열 때 받아 합침(48시간 이내) → 1,634건 12초 안에 완료(전엔 약 5분).
수동 갱신: 업로드 직후 바로 쓰려면 `gh workflow run precompute-board.yml`(약 5분). BOARD_CALC_VER을 올리면 서버 저장본도 무효(sig 불일치)라 워크플로를 한 번 돌려야 함.
화면 반응: 표 120건씩(더 보기), 계산 중 다시 그리기 5초·클릭 직후 미룸, 저장 계산 복원 40ms 단위 분할, 상세 열 때 표 전체 재그리기 생략. 원인으로 확인된 멈춤: 부천 calcPriceGrades 제곱 계산(villaMemo로 해결).
