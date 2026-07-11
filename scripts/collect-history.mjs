import { createClient } from '@supabase/supabase-js';
import { LAWD_CODES, fetchMonth, sleep, DELAY_MS } from './shared.mjs';

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);

const TARGET_YEAR = parseInt(process.env.TARGET_YEAR || String(new Date().getFullYear()));

const now          = new Date();
const currentYear  = now.getFullYear();
const currentMonth = now.getMonth() + 1;

const ALL_MONTHS = [1,2,3,4,5,6,7,8,9,10,11,12];
const targetMonths = TARGET_YEAR < currentYear
  ? ALL_MONTHS
  : ALL_MONTHS.filter(m => m <= currentMonth);

console.log(`/n📅 ${TARGET_YEAR}년 수집 시작`);
console.log(`총 ${LAWD_CODES.length}개 지역 × ${targetMonths.length}개월 = ${LAWD_CODES.length * targetMonths.length}회 호출n`);

let totalInserted = 0;
let callCount     = 0;
const totalCalls  = LAWD_CODES.length * targetMonths.length;

for (const month of targetMonths) {
  const ym        = String(TARGET_YEAR) + String(month).padStart(2, '0');
  const monthRows = [];

  for (const { code, name } of LAWD_CODES) {
    const rows = await fetchMonth(code, name, ym);
    monthRows.push(...rows);
    callCount++;
    await sleep(DELAY_MS);

    if (callCount % 100 === 0) {
      const pct = ((callCount / totalCalls) * 100).toFixed(1);
      console.log(`진행: ${callCount}/${totalCalls} (${pct}%) | ${ym}`);
    }
  }

  // 중복 제거 (region, danji, size, floor, deal_date 기준)
  const uniqueRows = Array.from(
    new Map(
      monthRows.map(row => [
        `${row.region}_${row.dong}_${row.danji}_${row.size}_${row.floor}_${row.deal_date}`,
        row
      ])
    ).values()
  );

  const { error } = await supabase
    .from('house_trades')
    .upsert(uniqueRows, {
      onConflict: 'region,dong,danji,size,floor,deal_date'
    });

  if (error) {
    console.error(`❌ upsert 에러: ${error.message}`);
  }

  totalInserted += uniqueRows.length;
  console.log(`✅ ${ym} 완료: ${uniqueRows.length}건 (누적 ${totalInserted}건)`);
}

console.log(`/n🎉 ${TARGET_YEAR}년 완료! 총 ${totalInserted}건`);






