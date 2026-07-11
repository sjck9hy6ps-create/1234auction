import { LAWD_CODES, sleep, DELAY_MS, fetchMonthVilla, fetchMonthSingle, upsertVilla, upsertSingle } from './shared-villa.mjs';

const TARGET_YEAR = parseInt(process.env.TARGET_YEAR || String(new Date().getFullYear()));
const now          = new Date();
const currentYear  = now.getFullYear();
const currentMonth = now.getMonth() + 1;
const ALL_MONTHS   = [1,2,3,4,5,6,7,8,9,10,11,12];
const targetMonths = TARGET_YEAR < currentYear
  ? ALL_MONTHS
  : ALL_MONTHS.filter(m => m <= currentMonth);

console.log(`\n📅 ${TARGET_YEAR}년 연립다세대 + 단독/다가구 수집 시작`);
console.log(`총 ${LAWD_CODES.length}개 지역 × ${targetMonths.length}개월\n`);

let totalVilla  = 0;
let totalSingle = 0;

for (const month of targetMonths) {
  const ym          = String(TARGET_YEAR) + String(month).padStart(2, '0');
  const villaRows   = [];
  const singleRows  = [];

  console.log(`\n🗓️  ${ym} 수집 시작...`);

  for (const { code, name } of LAWD_CODES) {
    // 연립다세대 호출
    const vRows = await fetchMonthVilla(code, name, ym);
    villaRows.push(...vRows);
    await sleep(DELAY_MS);

    // 단독/다가구 호출
    const sRows = await fetchMonthSingle(code, name, ym);
    singleRows.push(...sRows);
    await sleep(DELAY_MS);
  }

  // 월 단위로 upsert
  await upsertVilla(villaRows);
  await upsertSingle(singleRows);

  totalVilla  += villaRows.length;
  totalSingle += singleRows.length;

  console.log(`✅ ${ym} 완료 | 연립다세대 ${villaRows.length}건 / 단독다가구 ${singleRows.length}건`);
  console.log(`   누적 | 연립다세대 ${totalVilla}건 / 단독다가구 ${totalSingle}건`);
}

console.log(`\n🎉 ${TARGET_YEAR}년 전체 완료!`);
console.log(`   연립다세대 총 ${totalVilla}건`);
console.log(`   단독다가구 총 ${totalSingle}건`);
