/* 입찰후보 계산 미리 해 두기 (2026-10-10, 사용자: "지역 자료 불러오는 중이 너무 길다 - 획기적으로 줄이고 싶다")
   앱이 입찰후보를 열 때 하는 계산(지역 실거래 179곳 받아 물건별 시세·추천가 계산, 처음엔 수 분)을 GitHub Actions의 가상 브라우저가 대신 해서
   결과(앱이 쓰는 저장 계산과 같은 모양)를 Supabase에 올려 둠 → 앱은 열 때 이걸 받아 쓰고 바뀐 물건만 다시 계산 → 수 초.
   저장 위치: leader_follower_cache 'board|cache|meta'(개수·시각)와 'board|cache|0..N'(150건씩) */
import { chromium } from 'playwright';
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';

const SITE = process.env.SITE_URL || 'https://1234auction.vercel.app';
const supabase = createClient(process.env.SUPABASE_URL?.trim(), process.env.SUPABASE_SERVICE_ROLE_KEY?.trim(), { auth: { persistSession: false }, realtime: { transport: ws } });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
page.setDefaultTimeout(60000);
page.on('pageerror', (e) => console.log('페이지 오류:', String(e).slice(0, 200)));
console.log('앱 여는 중…');
await page.goto(SITE, { waitUntil: 'load' });
await page.waitForTimeout(10000);
await page.evaluate(() => { try { document.getElementById('remind-panel').style.display = 'none'; document.getElementById('bid-board').style.display = 'flex'; } catch (e) {} forceRefreshBidBoard(); });
const t0 = Date.now();
let last = '';
for (;;) {
  await page.waitForTimeout(15000);
  const st = await page.evaluate(() => ({ prog: (document.getElementById('bb-progress') || {}).innerText || '', running: !!window.bidBoardRunning, rows: bidBoardRows.length, pending: bidBoardRows.filter((r) => r.pending).length }));
  const line = `${Math.round((Date.now() - t0) / 1000)}s · ${st.prog || '(진행 표시 없음)'} · 행 ${st.rows} · 대기 ${st.pending} · 실행중 ${st.running}`;
  if (line !== last) console.log(line);
  last = line;
  if (!st.running && !st.prog && st.rows > 0 && st.pending === 0) break;
  if (Date.now() - t0 > 80 * 60 * 1000) { console.log('시간 초과'); break; }
}
// 연식·승강기·세대수 채우기(앱이 입찰후보 계산 직후 배경에서 하는 일)가 끝나길 기다린 뒤 저장 계산에 반영 - 안 그러면 사용자 앱의 물건 값(연식 등)과 서버 계산의 식별값이 달라 일부 물건을 다시 계산하게 됨(2026-10-11)
await page.waitForTimeout(6000);
{
  const tf = Date.now();
  while (Date.now() - tf < 25 * 60 * 1000) {
    const busy = await page.evaluate(() => !!householdFillRunning);
    if (!busy) break;
    await page.waitForTimeout(10000);
  }
  console.log(`연식·세대수 채우기 대기 ${Math.round((Date.now() - tf) / 1000)}s`);
}
const fixed = await page.evaluate(async () => {
  const cache = (await listIdbOp('readonly', function (st) { return st.get(BOARD_CACHE_KEY); })) || {};
  let n = 0;
  bidBoardRows.forEach(function (r) {
    const c = cache[r.id];
    if (c && r.a && !r.pending && !r.skippedPast && c.sig !== boardBaseSig(r.a)) { const row = boardRowForCache(r); if (row) { cache[r.id] = { sig: boardBaseSig(r.a), at: Date.now(), row: row }; n++; } }
  });
  if (n) await listIdbOp('readwrite', function (st) { return st.put(cache, BOARD_CACHE_KEY); });
  return n;
});
console.log(`채운 연식 등을 반영해 다시 저장한 물건 ${fixed}건`);
const cache = await page.evaluate(async () => await listIdbOp('readonly', function (st) { return st.get(BOARD_CACHE_KEY); }));
// ── 빌라 탭 미리 계산(2026-10-10, 사용자: 빌라 입찰후보 창이 매번 느림 → 실사용 전에 웜업) ──
let villa = null;
try {
  await page.evaluate(() => { setLiteVisit('villa'); setVillaVisit('all'); });
  const tv = Date.now();
  for (;;) {
    await page.waitForTimeout(15000);
    const st = await page.evaluate(() => ({ busy: !!villaLoadBusy, final: !!villaLiqFinal, rows: villaMetroRows(true).length, ve: villaMetroRows(true).filter((r) => villaVeCache[r.id]).length, hsq: hsQueue.length, hsr: hsRunning }));
    console.log(`빌라 ${Math.round((Date.now() - tv) / 1000)}s · 행 ${st.rows} · 예상매도가 ${st.ve} · 생활권 ${st.final} · 대장 대기 ${st.hsq}/${st.hsr}`);
    if (!st.busy && st.final && st.ve >= st.rows && st.hsq === 0 && st.hsr === 0) break;
    if (!st.busy && st.final && st.ve >= st.rows && Date.now() - tv > 15 * 60 * 1000) break; // 대장 조회는 최대 15분만 기다림
    if (Date.now() - tv > 40 * 60 * 1000) { console.log('빌라 시간 초과'); break; }
  }
  villa = await page.evaluate(() => villaCalcSnapshot());
} catch (e) { console.log('빌라 미리 계산 실패:', String(e).slice(0, 200)); }
await browser.close();
const ids = Object.keys(cache || {});
console.log(`저장 계산 ${ids.length}건`);
if (ids.length < 50) { console.error('저장 계산이 너무 적어 올리지 않음'); process.exit(1); }
const CH = 150, now = new Date().toISOString();
const rows = [];
for (let i = 0; i * CH < ids.length; i++) {
  const items = {};
  ids.slice(i * CH, (i + 1) * CH).forEach((id) => { items[id] = { ...cache[id], srv: true }; });
  rows.push({ id: `board|cache|${i}`, payload: { items }, fetched_at: now });
}
for (const r of rows) {
  for (let a = 0; a < 4; a++) {
    const { error } = await supabase.from('leader_follower_cache').upsert(r, { onConflict: 'id' });
    if (!error) break;
    console.log('저장 재시도', r.id, error.message);
    await new Promise((res) => setTimeout(res, 3000 * (a + 1)));
  }
}
await supabase.from('leader_follower_cache').upsert({ id: 'board|cache|meta', payload: { n: rows.length, count: ids.length, at: Date.now() }, fetched_at: now }, { onConflict: 'id' });
console.log(`✅ 올림: ${rows.length}묶음 / ${ids.length}건`);
if (villa && Object.keys(villa.ve || {}).length >= 50) {
  const vids = Object.keys(villa.ve), VC = 100, vrows = [];
  for (let i = 0; i * VC < vids.length; i++) {
    const part = { ve: {}, liq: {}, hs: {} };
    vids.slice(i * VC, (i + 1) * VC).forEach((id) => { part.ve[id] = villa.ve[id]; if (villa.liq[id]) part.liq[id] = villa.liq[id]; if (villa.hs[id]) part.hs[id] = villa.hs[id]; });
    vrows.push({ id: `board|villa|${i}`, payload: part, fetched_at: now });
  }
  for (const r of vrows) {
    for (let a = 0; a < 4; a++) {
      const { error } = await supabase.from('leader_follower_cache').upsert(r, { onConflict: 'id' });
      if (!error) break;
      console.log('빌라 저장 재시도', r.id, error.message);
      await new Promise((res) => setTimeout(res, 3000 * (a + 1)));
    }
  }
  await supabase.from('leader_follower_cache').upsert({ id: 'board|villa|meta', payload: { n: vrows.length, count: vids.length, at: Date.now() }, fetched_at: now }, { onConflict: 'id' });
  console.log(`✅ 빌라 올림: ${vrows.length}묶음 / ${vids.length}건 (생활권 ${Object.keys(villa.liq).length}, 대장 ${Object.keys(villa.hs).length})`);
} else console.log('빌라 계산이 너무 적어 올리지 않음');
