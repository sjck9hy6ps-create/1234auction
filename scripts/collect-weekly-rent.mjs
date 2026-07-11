import { LAWD_CODES, sleep, DELAY_MS, fetchMonthRent, upsertRent } from './shared-rent.mjs';

const now    = new Date();
const months = [];
// 이번달 + 전달 (신고 지연 대응)
for (let i = 0; i <= 1; i++) {
  const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
  months.push(String(d.getFullYear()) + String(d.getMonth() + 1).padStart(2, '0'));
}

console.log(`\n📅 주간 전월세 수집: ${months.join(', ')}`);

let total = 0;

for (const ym of months) {
  const rows = [];
  for (const { code, name } of LAWD_CODES) {
    const r = await fetchMonthRent(code, name, ym);
    rows.push(...r);
    await sleep(DELAY_MS);
  }
  await upsertRent(rows);
  total += rows.length;
  console.log(`✅ ${ym}: ${rows.length}건`);
}

console.log(`\n🎉 주간 전월세 수집 완료! 총 ${total}건`);
