/* 입찰 전날 값 저장 (2026-11-18, 사용자: 입찰 전날 계산한 값을 낙찰 결과와 비교해야 정확한 성적표)
   매일 저녁(KST) 가상 브라우저가 앱을 열어 입찰후보를 계산하고 → 입찰이 내일·오늘인 물건의 예측(추천가·예상 낙찰가·낙찰 가능성·예상매도가)을 predSnap/predHist로 저장.
   앱을 사용자가 직접 열지 않은 날에도 입찰 전날 값이 남도록 하는 안전장치(앱의 savePredSnapshots를 그대로 씀). 계산 방식은 바꾸지 않음. */
import { chromium } from 'playwright';

const SITE = process.env.SITE_URL || 'https://1234auction.vercel.app';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, timezoneId: 'Asia/Seoul', locale: 'ko-KR' });
page.setDefaultTimeout(60000);
page.on('pageerror', (e) => console.log('페이지 오류:', String(e).slice(0, 200)));
await page.addInitScript(() => { window.__prefetchAhead = 10; });
console.log('앱 여는 중…');
await page.goto(SITE, { waitUntil: 'load' });
await page.waitForTimeout(10000);
await page.evaluate(() => { try { const rp = document.getElementById('remind-panel'); if (rp) rp.style.display = 'none'; } catch (e) {} try { document.getElementById('bid-board').style.display = 'flex'; } catch (e) {} try { openBidBoard(); } catch (e) {} });
const t0 = Date.now(); let last = '';
for (;;) {
  await page.waitForTimeout(15000);
  const st = await page.evaluate(() => ({ prog: (document.getElementById('bb-progress') || {}).innerText || '', running: !!window.bidBoardRunning, rows: bidBoardRows.length, pending: bidBoardRows.filter((r) => r.pending).length }));
  const line = `${Math.round((Date.now() - t0) / 1000)}s · ${st.prog || '(진행 표시 없음)'} · 행 ${st.rows} · 대기 ${st.pending} · 실행중 ${st.running}`;
  if (line !== last) console.log(line);
  last = line;
  if (!st.running && !st.prog && st.rows > 0 && st.pending === 0) break;
  if (Date.now() - t0 > 50 * 60 * 1000) { console.log('시간 초과'); break; }
}
await page.waitForTimeout(8000);
const before = await page.evaluate(() => {
  const o = { d0: 0, d1: 0 };
  (bidBoardRows || []).forEach((r) => { if (r.dday && r.dday.diffDays >= 0 && r.dday.diffDays <= 1) { if (r.dday.diffDays === 0) o.d0++; else o.d1++; } });
  return o;
});
console.log('입찰 오늘/내일 물건', JSON.stringify(before));
await page.evaluate(async () => { try { await savePredSnapshots(); } catch (e) { console.log('저장 오류', e && e.message); } });
await page.waitForTimeout(20000);
const after = await page.evaluate(() => {
  const t = new Date(); const today = t.getFullYear() + '-' + String(t.getMonth() + 1).padStart(2, '0') + '-' + String(t.getDate()).padStart(2, '0'); let saved = 0, tomorrow = 0;
  (bidBoardRows || []).forEach((r) => { if (r.dday && r.dday.diffDays === 1) { tomorrow++; if (r.a && r.a.predSnap && r.a.predSnap.at === today) saved++; } });
  return { today, tomorrow, saved };
});
console.log('✅ 입찰 내일 물건 ' + after.tomorrow + '건 중 오늘(' + after.today + ') 저장 ' + after.saved + '건');
await browser.close();
