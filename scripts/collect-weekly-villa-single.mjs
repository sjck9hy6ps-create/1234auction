import { LAWD_CODES, sleep, DELAY_MS, fetchMonthVilla, fetchMonthSingle, upsertVilla, upsertSingle } from './shared-villa.mjs';

// 실거래가 신고는 계약일로부터 최대 30일까지 지연될 수 있어
// 이번 달과 지난 달, 두 달치를 함께 갱신합니다.
const now = new Date();
const targets = [
  { year: now.getFullYear(), month: now.getMonth() + 1 },
];
const prevDate = new Date(now.getFullYear(), now.getMonth() - 1, 1);
targets.push({ year: prevDate.getFullYear(), month: prevDate.getMonth() + 1 });

console.log(`\n📅 연립다세대 + 단독/다가구 주간 수집 시작`);
console.log(`대상 월: ${targets.map(t => `${t.year}${String(t.month).padStart(2, '0')}`).join(', ')}`);
console.log(`총 ${LAWD_CODES.length}개 지역 × ${targets.length}개월\n`);

let totalVilla  = 0;
let totalSingle = 0;

for (const { year, month } of targets) {
  const ym         = String(year) + String(month).padStart(2, '0');
  const villaRows  = [];
  const singleRows = [];

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

  // 월 단위로 upsert (기존 데이터는 onConflict 조건으로 덮어쓰기)
  await upsertVilla(villaRows);
  await upsertSingle(singleRows);

  totalVilla  += villaRows.length;
  totalSingle += singleRows.length;

  console.log(`✅ ${ym} 완료 | 연립다세대 ${villaRows.length}건 / 단독다가구 ${singleRows.length}건`);
}

console.log(`\n🎉 주간 수집 전체 완료!`);
console.log(`   연립다세대 총 ${totalVilla}건`);
console.log(`   단독다가구 총 ${totalSingle}건`);
