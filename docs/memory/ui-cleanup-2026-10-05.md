---
name: ui-cleanup-2026-10-05
description: 2026-10-05 menu/modal cleanup — what was hidden or removed (UI-only, data and functions kept) and why
metadata:
  type: project
---
User-directed cleanup on 2026-10-05:
- **Top bar.** 더보기 was removed. It now has one row: 입찰후보 (toggles with 지도) · 내 자산 · 경매물건 등록 (paste plus CSV) · 낙찰사례 · 돈되는 지역 · 사이클 · 사용법 · 백업.
  - "앱을 열면 입찰후보부터" moved to the board header.
  - Menu entries gone: 경매관리, 백테스트 일괄등록, 배지 재로딩, and the 급등지역 tab.
- **상세 modal.** `setupAuctionModalV4` hides, via the am4 classes:
  - AI 자동 채우기, AI 브리핑, 개발호재 AI 검색
  - ② 예상마진 and the 매입가율 stats, AVM, 공시가 참고, 상세 도구
  - 권리서류 분석 and 체크리스트 (both had 0 uses)
  - For apartments only: 호가, 비교물건 and 예측 적용 are hidden; villas still need them.
- **Other places.**
  - Complex panel: 임장메모 is shown only when old notes exist; 저평가 진단 is gone.
  - 낙찰사례 panel: the matching and 연식 buttons are hidden, because the server automates both.
  - Bid board: duplicate buttons removed — row 지도/상세, drawer bottom, header 사용법/CSV.
- **Kept on purpose.** 등급 filter, 신고가 and 후발주자 tabs, 평형별 인기 단지 찾기, and the 메모 field (322 uses).

**Why:** the user wants only features that match the current flow (CSV → board verdict → drawer → bid; 낙찰/매도 tracked in 내 자산).
**How to apply:** don't re-add these. To restore one, remove its am4-hide/hide line — the code and data are still there.
