import { LAWD_CODES, sleep, DELAY_MS, fetchMonthRent, upsertRent } from './shared-rent.mjs';

const TARGET_YEAR = parseInt(process.env.TARGET_YEAR || String(new Date().getFullYear()));
const now          = new Date();
const currentYear  = now.getFullYear();
const currentMonth = now.getMonth() + 1;
const ALL_MONTHS   = [1,2,3,4,5,6,7,8,9,10,11,12];
const targetMonths = TARGET_YEAR < currentYear
  ? ALL_MONTHS
  : ALL_MONTHS.filter(m => m <= currentMonth);

console.log(`\n📅 ${TARGET_YEAR}년 아파트 전월세 수집 시작`);
console.log(`총 ${LAWD_CODES.length}개 지역 × ${targetMonths.length}개월\n`);

let total = 0;

for (const month of targetMonths) {
  const ym   = String(TARGET_YEAR) + String(month).padStart(2, '0');
  const rows = [];

  console.log(`\n🗓️  ${ym} 수집 시작...`);

  for (const { code, name } of LAWD_CODES) {
    const r = await fetchMonthRent(code, name, ym);
    rows.push(...r);
    await sleep(DELAY_MS);
  }

  // 첫 달 첫 건은 실제 필드가 잘 채워졌는지 확인용으로 콘솔에 출력
  if (month === targetMonths[0] && rows.length > 0) {
    console.log('   샘플 row:', JSON.stringify(rows[0]));
  }

  await upsertRent(rows);
  total += rows.length;

  console.log(`✅ ${ym} 완료 | ${rows.length}건 (누적 ${total}건)`);
}

console.log(`\n🎉 ${TARGET_YEAR}년 전월세 수집 완료! 총 ${total}건`);
