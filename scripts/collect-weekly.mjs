import { LAWD_CODES, fetchMonth, upsertBatch, sleep, DELAY_MS } from './shared.mjs';

// 최신월부터 2개월 수집 (이번달 + 전달)
const now    = new Date();
const months = [];

for (let i = 0; i <= 1; i++) {
  const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
  months.push(
    String(d.getFullYear()) + String(d.getMonth() + 1).padStart(2, '0')
  );
}

console.log(`\n📅 주간 수집 시작: \${months.join(', ')}`);

let totalInserted = 0;

for (const ym of months) {
  const monthRows = [];

  for (const lawdCd of LAWD_CODES) {
    const rows = await fetchMonth(lawdCd, ym);
    monthRows.push(...rows);
    await sleep(DELAY_MS);
  }

  await upsertBatch(monthRows);
  totalInserted += monthRows.length;
  console.log(`✅ \${ym} 완료: \${monthRows.length}건 저장`);
}

console.log(`\n🎉 주간 수집 완료! 총 \${totalInserted}건`);
