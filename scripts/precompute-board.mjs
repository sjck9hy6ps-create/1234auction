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
const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, timezoneId: 'Asia/Seoul', locale: 'ko-KR' }); // 한국 시각 기준(입찰일 지남 여부·남은 일수가 사용자 화면과 같게, 2026-10-15)
// 빌라 월세 시세는 매주 새 신고로 다시 계산(2026-10-11) - 단, 서버에 저장된 빌라 계산이 5일 안이면 다시 계산하지 않음(2026-10-18: 월세 강제 재계산이 빌라 단계 15분 이상의 대부분이었고, 아파트 규칙만 바뀐 재실행에서도 매번 돌았음). RC_FORCE=1이면 항상 강제
let rcForce = process.env.RC_FORCE === '1';
if (!rcForce) {
  try {
    const { data: vm } = await supabase.from('leader_follower_cache').select('payload').eq('id', 'board|villa|meta').maybeSingle();
    const at = vm && vm.payload && vm.payload.at;
    rcForce = !at || Date.now() - at >= 5 * 86400000;
    console.log(`빌라 월세 재계산 ${rcForce ? '실행(저장본이 오래됐거나 없음)' : '건너뜀(저장본이 5일 안)'}`);
  } catch (e) { rcForce = true; }
}
await page.addInitScript((f) => { window.__rcForce = f; window.__prefetchAhead = 10; }, rcForce); // 지역 자료 미리 받기도 4곳 → 10곳(가상 브라우저는 화면이 없어 더 많이 받아도 됨)
page.setDefaultTimeout(60000);
page.on('pageerror', (e) => console.log('페이지 오류:', String(e).slice(0, 200)));
console.log('앱 여는 중…');
await page.goto(SITE, { waitUntil: 'load' });
await page.waitForTimeout(10000);
await page.evaluate(() => { try { const rp = document.getElementById('remind-panel'); if (rp) rp.style.display = 'none'; } catch (e) {} try { document.getElementById('bid-board').style.display = 'flex'; } catch (e) {} forceRefreshBidBoard(); });
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
// 연식·세대수 채우기를 직접 시작해 끝까지 기다림(앱이 계산 직후 2초 뒤 배경에서 하는 일 - 서버 계산이 이걸 건너뛰면 사용자 앱이 열 때마다 같은 물건을 다시 조회함)
await page.evaluate(() => { try { document.getElementById('bid-board').style.display = 'flex'; } catch (e) {} fillHouseholdsInBackground(); });
await page.waitForTimeout(3000);
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
    if (c && r.a && !r.pending && !r.skippedPast && r.type && !(r.verdict === 'nodata' && !r.loaded && r.a.lat)) { const row = boardRowForCache(r); if (row) { cache[r.id] = { sig: boardBaseSig(r.a), at: Date.now(), row: row }; n++; } }
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
    const st = await page.evaluate(() => ({ busy: !!villaLoadBusy, final: !!villaLiqFinal, rows: villaMetroRows(true).length, ve: villaMetroRows(true).filter((r) => villaVeCache[r.id]).length, rcf: villaMetroRows(true).filter((r) => villaRcFresh[r.id]).length, hsq: hsQueue.length, hsr: hsRunning }));
    console.log(`빌라 ${Math.round((Date.now() - tv) / 1000)}s · 행 ${st.rows} · 예상매도가 ${st.ve} · 생활권 ${st.final} · 월세 ${st.rcf} · 대장 대기 ${st.hsq}/${st.hsr}`);
    if (!st.busy && st.final && st.ve >= st.rows && (!rcForce || st.rcf >= st.rows) && st.hsq === 0 && st.hsr === 0) break; // 월세를 다시 계산하지 않는 날엔 월세 완료 수를 기다리지 않음
    if (!st.busy && st.final && st.ve >= st.rows && Date.now() - tv > 15 * 60 * 1000) break; // 대장 조회는 최대 15분만 기다림
    if (Date.now() - tv > 40 * 60 * 1000) { console.log('빌라 시간 초과'); break; }
  }
  // 대장 연식이 채워진 뒤 예상매도가가 새 연식으로 다시 계산돼야 하므로(식별값에 연식 포함) 다 맞을 때까지 기다림(최대 20분)
  const tw = Date.now();
  for (;;) {
    const ok = await page.evaluate(() => !villaLoadBusy && villaMetroRows(true).every((r) => { const c = villaVeCache[r.id]; return c && c.sig === villaVeSig(r.a); }));
    if (ok || Date.now() - tw > 20 * 60 * 1000) { console.log(`빌라 연식 반영 재계산 대기 ${Math.round((Date.now() - tw) / 1000)}s · ${ok ? '완료' : '시간 초과'}`); break; }
    await page.waitForTimeout(10000);
  }
  // 판정(ev)은 화면을 그릴 때 14ms씩 나눠 계산하므로 헤드리스에선 일부만 끝나 있음 → 저장 전에 전부 한 번에 계산(기준값을 올려 저장본이 무효가 된 날에도 완전하게)
  const evDone = await page.evaluate(() => { window.__villaEvDeadline = 0; let n = 0; villaMetroRows(true).forEach((r) => { try { const e = villaEval(r); if (e && !e.pending) n++; } catch (e) {} }); return n; });
  console.log(`빌라 판정 계산 ${evDone}건`);
  villa = await page.evaluate(() => villaCalcSnapshot());
} catch (e) { console.log('빌라 미리 계산 실패:', String(e).slice(0, 200)); }
// ── 이번 주 변동 비교용 요약(2026-10-12, 사용자: 파이프라인 전후로 달라진 값 확인) - 물건별 핵심 값만 뽑아 두고, 아래에서 지난 기준 저장본과 비교 ──
let summary = null;
try {
  summary = await page.evaluate(() => {
    const out = {};
    (bidBoardRows || []).forEach((r) => {
      if (r.type !== 'apt' || r.pending || r.skippedPast || !r.a) return;
      const pe = r.pick && r.pick.ev;
      out[r.id] = ['a', r.a.caseNo || '', r.name || '', r.region || '', r.minBid || 0, r.a.bidDate || '', Math.round(r.sale || 0), pe ? Math.round(pe.bid) : 0, r.visit && r.visit.go ? 1 : 0, pe ? Math.round(pe.p * 100) : 0, pe ? Math.round(pe.net) : 0, (r.visit && r.visit.why) || ''];
    });
    villaMetroRows(true).forEach((r) => {
      const ev = villaEval(r); if (!ev || ev.pending) return;
      const pe = ev.pn && ev.pn.ev;
      out[r.id] = ['v', r.a.caseNo || '', (typeof villaNameFor === 'function' ? villaNameFor(r) : r.name) || '', r.region || '', r.minBid || 0, r.a.bidDate || '', ev.ve ? Math.round(ev.ve.est) : 0, pe ? Math.round(pe.bid) : 0, ev.visit && ev.visit.go ? 1 : 0, pe ? Math.round(pe.p * 100) : 0, pe ? Math.round(pe.net) : 0, (ev.visit && ev.visit.why) || ''];
    });
    return out;
  });
} catch (e) { console.log('변동 요약 만들기 실패:', String(e).slice(0, 200)); }
await browser.close();
// 2026-10-21(사용자: 입찰후보 저장 계산 불러오는 시간이 김) - 임장 후보를 앞쪽 묶음에 모아 앱이 후보부터 받고 화면을 먼저 채우게 함(나머지는 뒤에서)
const ids = Object.keys(cache || {}).sort((x, y) => {
  const gx = cache[x] && cache[x].row && cache[x].row.visit && cache[x].row.visit.go ? 0 : 1, gy = cache[y] && cache[y].row && cache[y].row.visit && cache[y].row.visit.go ? 0 : 1;
  return gx - gy;
});
const goN = ids.filter((id) => cache[id] && cache[id].row && cache[id].row.visit && cache[id].row.visit.go).length;
console.log(`저장 계산 ${ids.length}건 (임장 후보 ${goN}건)`);
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
await supabase.from('leader_follower_cache').upsert({ id: 'board|cache|meta', payload: { n: rows.length, count: ids.length, at: Date.now(), goN, goChunks: Math.max(1, Math.ceil(goN / CH)) }, fetched_at: now }, { onConflict: 'id' });
console.log(`✅ 올림: ${rows.length}묶음 / ${ids.length}건`);
if (villa && Object.keys(villa.ve || {}).length >= 50) {
  const vids = Object.keys(villa.ve), VC = 100, vrows = [];
  for (let i = 0; i * VC < vids.length; i++) {
    const part = { ve: {}, liq: {}, hs: {}, ev: {}, rc: {} };
    vids.slice(i * VC, (i + 1) * VC).forEach((id) => { part.ve[id] = villa.ve[id]; if (villa.liq[id]) part.liq[id] = villa.liq[id]; if (villa.hs[id]) part.hs[id] = villa.hs[id]; if (villa.ev && villa.ev[id]) part.ev[id] = villa.ev[id]; if (villa.rc && villa.rc[id]) part.rc[id] = villa.rc[id]; });
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

// ── 이번 주 변동(2026-10-12): 지난 기준 저장본(board|snap|base)과 비교해 board|diff|latest에 저장. 기준은 5일 넘게 지났을 때만 새로 교체(한 주에 여러 번 돌려도 주 단위로 비교) ──
try {
  if (summary && Object.keys(summary).length >= 100) {
    const nowIso = new Date().toISOString();
    const { data: bs } = await supabase.from('leader_follower_cache').select('payload').eq('id', 'board|snap|base').maybeSingle();
    const base = bs && bs.payload && bs.payload.items ? bs.payload : null;
    if (base) {
      const A = base.items, B = summary, today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
      const rec = (x) => ({ id: null, t: x[0], caseNo: x[1], name: x[2], region: x[3], minBid: x[4], bidDate: x[5] });
      const goIn = [], goOut = [], recChg = [], estChg = [], added = [];
      let removed = 0, same = 0;
      Object.keys(B).forEach((id) => {
        const n = B[id], o = A[id];
        if (!o) { if (!n[5] || n[5].replace(/-/g, '') >= today) added.push({ ...rec(n), est: n[6], rec: n[7], go: n[8] }); return; }
        const base0 = rec(n); let moved = false;
        if (o[8] !== n[8]) { (n[8] ? goIn : goOut).push({ ...base0, rec: n[7], recOld: o[7], why: n[11], whyOld: o[11], p: n[9] }); moved = true; }
        if (o[7] && n[7] && Math.abs(n[7] - o[7]) / o[7] >= 0.03 && Math.abs(n[7] - o[7]) >= 100) { recChg.push({ ...base0, rec: n[7], recOld: o[7], go: n[8] }); moved = true; }
        if (o[6] && n[6] && Math.abs(n[6] - o[6]) / o[6] >= 0.03) { estChg.push({ ...base0, est: n[6], estOld: o[6], rec: n[7], recOld: o[7] }); moved = true; }
        if (!moved) same++;
      });
      Object.keys(A).forEach((id) => { if (!B[id]) removed++; });
      const byAbs = (k, ko) => (x, y) => Math.abs(y[k] - y[ko]) - Math.abs(x[k] - x[ko]);
      recChg.sort(byAbs('rec', 'recOld')); estChg.sort(byAbs('est', 'estOld'));
      const diff = { at: nowIso, baseAt: base.at, counts: { now: Object.keys(B).length, base: Object.keys(A).length, same, added: added.length, removed, goIn: goIn.length, goOut: goOut.length, recChg: recChg.length, estChg: estChg.length },
        goIn: goIn.slice(0, 100), goOut: goOut.slice(0, 100), recChg: recChg.slice(0, 120), estChg: estChg.slice(0, 80), added: added.slice(0, 80) };
      await supabase.from('leader_follower_cache').upsert({ id: 'board|diff|latest', payload: diff, fetched_at: nowIso }, { onConflict: 'id' });
      console.log(`✅ 변동 저장: 임장 후보 신규 ${goIn.length}·제외 ${goOut.length}, 추천가 변동 ${recChg.length}, 예상매도가 변동 ${estChg.length}, 새 물건 ${added.length}, 사라진 ${removed}`);
    } else console.log('변동 비교 기준이 아직 없어 이번 값을 기준으로 저장해 둠');
    if (!base || Date.now() - new Date(base.at).getTime() >= 5 * 86400000) {
      await supabase.from('leader_follower_cache').upsert({ id: 'board|snap|base', payload: { at: nowIso, items: summary }, fetched_at: nowIso }, { onConflict: 'id' });
      console.log(`변동 비교 기준 저장: ${Object.keys(summary).length}건`);
    }
  } else console.log('변동 요약이 너무 적어 비교 건너뜀');
} catch (e) { console.log('변동 비교 실패:', String(e).slice(0, 200)); }
