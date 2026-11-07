/* 빌라 앱 실제 계산 종단 검증(2026-11-07, 사용자: 종합 평가 값이 앱 실제 계산보다 나은지 직접 채점) - 가상 브라우저로 앱을 열고 지역마다 빌라 거래를 받아
   2026년 이후 실제 거래마다 앱의 villaSaleEst가 '그 거래 30일 전 자료'로 낸 값을 구해 서버(signal|__villa_bt_appasof__)에 저장. 같은 거래를 종합 모델로 예측해 비교하는 건 eval-villa-app-vs-stack.py. */
import { chromium } from 'playwright';
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';
import fs from 'fs';

const SITE = process.env.SITE_URL || 'https://1234auction.vercel.app';
const FROM = parseInt(process.env.FROM_YMD || '20260101', 10);
const CAP = parseInt(process.env.MAX_PER_REGION || '150', 10);
const REGION_LIMIT = parseInt(process.env.REGION_LIMIT || '0', 10);
const supa = createClient(process.env.SUPABASE_URL.trim(), process.env.SUPABASE_SERVICE_ROLE_KEY.trim(), { auth: { persistSession: false }, realtime: { transport: ws } });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, timezoneId: 'Asia/Seoul', locale: 'ko-KR' });
page.on('pageerror', (e) => console.log('페이지 오류:', String(e).slice(0, 160)));
console.log('앱 여는 중…');
await page.goto(SITE, { waitUntil: 'load' });
await page.waitForFunction(() => typeof auctionList !== 'undefined' && auctionList.length > 100, null, { timeout: 120000 });
await page.waitForTimeout(5000);
await page.addScriptTag({ path: 'scripts/lib/villa-asof-harness.js' });
let regions = Object.keys(await page.evaluate(() => __vv.regions())).sort();
if (REGION_LIMIT > 0) regions = regions.slice(0, REGION_LIMIT);
console.log(`대상 지역 ${regions.length}곳`);
const rows = []; const failed = []; let n = 0;
for (const l of regions) {
  n++;
  try {
    const r = await page.evaluate(([a, b, c]) => __vv.processRegion(a, b, c), [l, FROM, CAP]);
    r.rows.forEach((x) => rows.push(x));
  } catch (e) { failed.push(l); console.log(`❌ ${l}: ${String(e.message || e).slice(0, 120)}`); }
  if (n % 10 === 0) console.log(`  ${n}/${regions.length} 지역 · 누적 ${rows.length}건`);
}
await browser.close().catch(() => {});
fs.writeFileSync('villa-asof.json', JSON.stringify(rows));
const ok = rows.filter((r) => r.app > 0), err = ok.map((r) => Math.abs(r.app / r.price - 1)).sort((a, b) => a - b);
console.log(`총 ${rows.length}건 · 앱 값 있음 ${ok.length}건 · 앱 오차 중앙 ${(err[err.length >> 1] * 100).toFixed(2)}% · 실패 지역 ${failed.length}`);
const payload = { generatedAt: new Date().toISOString(), from: FROM, cap: CAP, failedRegions: failed, rows };
const { error } = await supa.from('leader_follower_cache').upsert({ id: 'signal|__villa_bt_appasof__', payload, fetched_at: payload.generatedAt }, { onConflict: 'id' });
console.log(error ? '저장 실패: ' + error.message : '✅ 저장');
if (error) process.exit(1);
