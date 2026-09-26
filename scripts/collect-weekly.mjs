import { LAWD_CODES, fetchMonth, upsertBatch, sleep, DELAY_MS } from './shared.mjs';

const now    = new Date();
const months = [];

// 이번달 + 전달 + 전전달 (2026-09 확인: 국토부 신고기한은 30일이지만 실제로는 더 늦게
// 신고되는 경우가 있어, 2개월치만 보면 늦게 신고된 과거월 거래를 영영 못 잡는 문제가
// 있었음(예: 7월 계약 건이 9월에 조회해도 안 잡힘) - 3개월치로 넓혀서 늦은 신고를
// 좀 더 넓게 커버함. 단, 이보다 더 늦게 신고되는 극소수 건은 여전히 놓칠 수 있어
// 주기적으로 collect-history.mjs로 전체 재백필하는 것도 권장.
for (let i = 0; i <= 2; i++) {
  const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
  months.push(String(d.getFullYear()) + String(d.getMonth() + 1).padStart(2, '0'));
}

console.log(`\n📅 주간 수집: ${months.join(', ')}`);

let totalInserted = 0;

for (const ym of months) {
  const monthRows = [];

  for (const { code, name } of LAWD_CODES) {
    const rows = await fetchMonth(code, name, ym);
    monthRows.push(...rows);
    await sleep(DELAY_MS);
  }

  await upsertBatch(monthRows);
  totalInserted += monthRows.length;
  console.log(`✅ ${ym}: ${monthRows.length}건`);
}

console.log(`\n🎉 주간 완료! 총 ${totalInserted}건`);
