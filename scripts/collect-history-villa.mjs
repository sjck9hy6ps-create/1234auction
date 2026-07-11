import { LAWD_CODES, sleep, DELAY_MS, fetchMonthVilla, upsertVilla } from './shared-villa.mjs';

const TARGET_YEAR = parseInt(process.env.TARGET_YEAR || String(new Date().getFullYear()));

const now          = new Date();
const currentYear  = now.getFullYear();
const currentMonth = now.getMonth() + 1;

const ALL_MONTHS   = [1,2,3,4,5,6,7,8,9,10,11,12];
const targetMonths = TARGET_YEAR < currentYear
  ? ALL_MONTHS
  : ALL_MONTHS.filter(m => m <= currentMonth);

console.log(`\n📅 \${TARGET_YEAR}년 연립다세대 수집 시작`);
console.log(`총 \${LAWD_CODES.length}개 지역 × \${targetMonths.length}개월 = \${LAWD_CODES.length * targetMonths.length}회 호출\n`);

let totalInserted = 0;
let callCount     = 0;
const totalCalls  = LAWD_CODES.length * targetMonths.length;

for (const month of targetMonths) {
  const ym        = String(TARGET_YEAR) + String(month).padStart(2, '0');
  const monthRows = [];

  for (const { code, name } of LAWD_CODES) {
    const rows = await fetchMonthVilla(code, name, ym);
    monthRows.push(...rows);
    callCount++;
    await sleep(DELAY_MS);

    if (callCount % 100 === 0) {
      const pct = ((callCount / totalCalls) * 100).toFixed(1);
      console.log(`  진행: \${callCount}/${totalCalls} (${pct}%) | 현재 \${ym}`);
    }
  }

  await upsertVilla(monthRows);
  totalInserted += monthRows.length;
  console.log(`✅ \${ym} 완료: \${monthRows.length}건 (누적 \${totalInserted}건)`);
}

console.log(`\n🎉 \${TARGET_YEAR}년 연립다세대 완료! 총 \${totalInserted}건`);
