import { LAWD_CODES, fetchMonth, upsertBatch, sleep, DELAY_MS } from './shared.mjs';

const now    = new Date();
const months = [];

// 이번달 + 전달
for (let i = 0; i <= 1; i++) {
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
