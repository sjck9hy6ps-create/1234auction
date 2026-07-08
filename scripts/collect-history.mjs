import { LAWD_CODES, fetchMonth, upsertBatch, sleep, DELAY_MS } from './shared.mjs';

const TARGET_YEAR = parseInt(process.env.TARGET_YEAR || String(new Date().getFullYear()));

// ✅ 최신월(12월)부터 → 1월 순으로 수집
const MONTHS = [12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1];

// 현재 연도면 현재 월까지만 수집
const now          = new Date();
const currentYear  = now.getFullYear();
const currentMonth = now.getMonth() + 1;

const targetMonths = TARGET_YEAR === currentYear
  ? MONTHS.filter(m => m <= currentMonth)  // 현재 월까지만
  : MONTHS;                                 // 전년도는 12~1월 전체

console.log(`\n📅 \${TARGET_YEAR}년 수집 시작 (${targetMonths[0]}월 → \${targetMonths[targetMonths.length - 1]}월)`);
console.log(`총 \${LAWD_CODES.length}개 지역 × \${targetMonths.length}개월 = \${LAWD_CODES.length * targetMonths.length}회 호출 예정\n`);

let totalInserted = 0;
let callCount     = 0;
const totalCalls  = LAWD_CODES.length * targetMonths.length;

for (const month of targetMonths) {
  const ym       = String(TARGET_YEAR) + String(month).padStart(2, '0');
  const monthRows = [];

  for (const lawdCd of LAWD_CODES) {
    const rows = await fetchMonth(lawdCd, ym);
    monthRows.push(...rows);
    callCount++;
    await sleep(DELAY_MS);

    if (callCount % 50 === 0) {
      const pct = ((callCount / totalCalls) * 100).toFixed(1);
      console.log(`진행: \${callCount}/${totalCalls}회 (${pct}%) | 현재: \${ym}`);
    }
  }

  await upsertBatch(monthRows);
  totalInserted += monthRows.length;
  console.log(`✅ \${ym} 완료: \${monthRows.length}건 저장 (누적 \${totalInserted}건)`);
}

console.log(`\n🎉 \${TARGET_YEAR}년 수집 완료! 총 \${totalInserted}건`);
