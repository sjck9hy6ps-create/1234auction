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
// ── 가격 그래프·빌라 최근거래가·10년 그래프 미리 만들기(2026-11-15, 사용자: 가격차트 금액을 미리 계산하고, 변동 작은 값은 바로 불러오게)
//    보드 계산이 끝나면 앱이 임시 지역 자료를 내려 버리므로, 지역(법정동 코드)별로 실거래를 다시 받아 → 그 지역 물건들을 계산 → 자료를 내리는 순서로 진행.
//    ① 물건별 최근 3년 같은 평형(아파트)·같은 건물 비슷한 면적(빌라) 거래 [날짜, 가격(만), 층, 직거래]
//    ② 빌라 최근거래가 1건(앱과 같은 규칙 villaRecentPick, 비교 건물 승강기 정보 포함)
//    ③ 단지별 10년 그래프의 '최근 자료보다 오래된' 달 [년월, 거래 수, 중앙값]
const charts = {}, hist = {}, band = {};   // band: 단지 안 잘 거래되는 평형 요약(2026-11-21) id → [0비활발·1보통·2활발, 이 평형 거래수, 순위, 평형 수, 비중%]
try {
  const lawds = await page.evaluate(() => {
    const set = {};
    (bidBoardRows || []).forEach((r) => { if (r.type === 'apt' && !r.pending && !r.skippedPast && r.a) { const l = r.lawd || bidBoardLawdOf(r.a); if (l) set[l] = (set[l] || 0) + 1; } });
    villaMetroRows(true).forEach((r) => { const l = r.lawd || bidBoardLawdOf(r.a); if (l) set[l] = (set[l] || 0) + 1; });
    return Object.keys(set);
  });
  console.log(`가격 그래프 계산 대상 지역 ${lawds.length}곳`);
  const tStart = Date.now();
  let done = 0;
  for (const lawd of lawds) {
    if (Date.now() - tStart > 45 * 60 * 1000) { console.log('가격 그래프 계산 시간 초과 - 나머지 지역은 건너뜀'); break; }
    try {
      const res = await page.evaluate(async (lw) => {
        const out = { charts: {}, hist: {}, band: {} };
        if (!dataCache[lw]) { const dd = await fetchHouseDataCached(lw); if (dd && !dd.error && Array.isArray(dd.apt)) await ingestRegionHouseData(dd, '', lw); }
        if (!dataCache[lw]) return out;
        const lawdOf = (r) => r.lawd || bidBoardLawdOf(r.a);
        const aptRows = (bidBoardRows || []).filter((r) => r.type === 'apt' && !r.pending && !r.skippedPast && r.a && lawdOf(r) === lw);
        const villaRows = villaMetroRows(true).filter((r) => lawdOf(r) === lw);
        const cut = Date.now() - 3 * 366 * 86400000;
        const add = (r) => {
          try {
            const a = [];
            drawerTrades(r).forEach((t) => { if (t.d && t.d.getTime() >= cut && t.p > 0) a.push([t.d.getFullYear() * 10000 + (t.d.getMonth() + 1) * 100 + t.d.getDate(), t.p, isNaN(t.f) ? null : t.f, t.direct ? 1 : 0]); });
            if (a.length) out.charts[r.id] = a.slice(0, 80);
          } catch (e) {}
        };
        aptRows.forEach(add); villaRows.forEach(add);
        aptRows.forEach((r) => { try { const b = aptBandBrief(r, true); if (b) out.band[r.id] = [{ bad: 0, mid: 1, good: 2 }[b.v], b.n, b.rank, b.nb, b.share]; } catch (e) {} });
        // ② 빌라 최근거래가 (승강기 정보를 못 받은 물건은 저장하지 않음 - 앱이 실시간으로 계산)
        let idx = 0;
        const work = async () => {
          while (idx < villaRows.length) {
            const r = villaRows[idx++];
            try {
              const cc = villaNearComps(r, 0.15);
              if (!cc || !cc.rows) continue;
              const nearAll = cc.rows.filter((x) => !x.direct);
              if (nearAll.length) await villaCompElevatorLoad(r, nearAll, 0.15);
              const rp = villaRecentPick(r);
              if (rp.pend) continue;
              if (rp.near) out.charts[r.id + '#n'] = { p: rp.near.price || rp.near.p || rp.near.amount, ts: rp.near.ts, fl: rp.near.floor, ar: Math.round(rp.near.area * 10) / 10, by: rp.compBy(rp.near), di: rp.near.dist, nm: rp.near.name || '', tier: rp.tier };
              else out.charts[r.id + '#n'] = { n: nearAll.length };
            } catch (e) {}
          }
        };
        await Promise.all(Array.from({ length: 6 }, work));
        // ③ 10년 그래프
        currentPyung = 'all';
        const todo = {};
        aptRows.concat(villaRows).forEach((r) => {
          try {
            const a = r.a, ap = ownComplexEntries(a, r.bunjiFull || fullBunjiFromAddr(a.addr, a.dong, a.bunji), r.type)[0], l = ap && ap.latest;
            if (!l || !l.region || !l.dong || !l.bunji) return;
            const type = (ap.buildingType || l.buildingType) === 'villa' ? 'villa' : 'apt', key = [l.region, l.dong, l.bunji, type].join('|');
            if (!todo[key]) todo[key] = ap;
          } catch (e) {}
        });
        const keys = Object.keys(todo);
        for (let i = 0; i < keys.length; i += 8) {
          const batch = keys.slice(i, i + 8), res = {};
          batch.forEach((k) => { res[k] = pnHistoryFor(todo[k], todo[k].trades || []); });
          for (let w = 0; w < 60 && batch.some((k) => res[k] === 'loading'); w++) { await new Promise((rr) => setTimeout(rr, 200)); batch.forEach((k) => { if (res[k] === 'loading') res[k] = pnHistoryFor(todo[k], todo[k].trades || []); }); }
          batch.forEach((k) => {
            const h = res[k], ap = todo[k], recent = ap.trades || [];
            if (!h || h === 'loading' || !h.length) return;
            const py = pnChartPyung(recent); if (!py) return;
            let minYm = 999999; recent.forEach((t) => { const ym = t.year * 100 + t.month; if (ym > 0 && ym < minYm) minYm = ym; });
            const by = {};
            h.forEach((t) => { if (!(t.area > 0) || String(toPyung(t.area)) !== String(py)) return; const v = parseInt(t.amount); const ym = t.year * 100 + t.month; if (!(v > 0) || ym >= minYm) return; (by[ym] = by[ym] || []).push(v); });
            const m = Object.keys(by).map(Number).sort((x, y) => x - y).map((ym) => { const v = by[ym].sort((x, y) => x - y); return [ym, v.length, v[v.length >> 1]]; });
            out.hist[k] = { py: py, m: m };
          });
        }
        // 자료 내리기(메모리)
        delete dataCache[lw]; delete rentCacheByLawd[lw]; mergedLawdCds.delete(lw);
        return out;
      }, lawd);
      Object.assign(charts, res.charts); Object.assign(hist, res.hist); Object.assign(band, res.band || {});
    } catch (e) { console.log('가격 그래프 계산 실패', lawd, String(e).slice(0, 120)); }
    done++;
    if (done % 20 === 0) console.log(`가격 그래프 계산 ${done}/${lawds.length}곳 · 점 ${Object.keys(charts).length} · 10년 단지 ${Object.keys(hist).length} · ${Math.round((Date.now() - tStart) / 1000)}s`);
  }
  console.log(`가격 그래프 점 ${Object.keys(charts).length}건 (빌라 최근거래가 ${Object.keys(charts).filter((k) => k.endsWith('#n')).length}) · 10년 그래프 ${Object.keys(hist).length}개 단지`);
} catch (e) { console.log('가격 그래프 미리 계산 실패:', String(e).slice(0, 200)); }
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
// 서버 캐시 미리 데우기(2026-10-21): 앱이 쓰는 주소(v=저장 시각)로 한 번씩 받아 두면 첫 사용자도 빠름
try {
  const { data: mt } = await supabase.from('leader_follower_cache').select('payload').eq('id', 'board|cache|meta').maybeSingle();
  const at = mt && mt.payload && mt.payload.at;
  if (at) {
    let okN = 0;
    for (let i = 0; i < rows.length; i += 8) {
      await Promise.all(Array.from({ length: Math.min(8, rows.length - i) }, (_, k) => fetch(`${SITE}/api/data-coverage?mode=boardCacheChunk&i=${i + k}&v=${at}`).then((r) => { if (r.ok) okN++; return r.arrayBuffer(); }).catch(() => {})));
    }
    console.log(`캐시 데우기 ${okN}/${rows.length}`);
  }
} catch (e) { console.log('캐시 데우기 실패(무시):', String(e).slice(0, 120)); }
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

// ── 가격 그래프 점 올리기: 물건 번호 해시로 40묶음(앱이 같은 식으로 묶음을 고름)
try {
  if (charts && Object.keys(charts).length >= 100) {
    const NCH = 40, hashOf = (id) => { let h = 0; for (const ch of String(id)) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return h % NCH; };
    const parts = Array.from({ length: NCH }, () => ({ items: {} }));
    Object.keys(charts).forEach((id) => { parts[hashOf(id)].items[id] = charts[id]; });
    for (let i = 0; i < NCH; i++) {
      for (let t = 0; t < 4; t++) {
        const { error } = await supabase.from('leader_follower_cache').upsert({ id: `board|chart|${i}`, payload: parts[i], fetched_at: now }, { onConflict: 'id' });
        if (!error) break;
        console.log('그래프 점 저장 재시도', i, error.message);
        await new Promise((res) => setTimeout(res, 3000 * (t + 1)));
      }
    }
    const cat = Date.now();
    await supabase.from('leader_follower_cache').upsert({ id: 'board|chart|meta', payload: { n: NCH, count: Object.keys(charts).length, at: cat }, fetched_at: now }, { onConflict: 'id' });
    console.log(`✅ 가격 그래프 점 올림: ${NCH}묶음 / ${Object.keys(charts).length}건`);
    let okN = 0;   // 서버 캐시 미리 데우기
    for (let i = 0; i < NCH; i += 8) await Promise.all(Array.from({ length: Math.min(8, NCH - i) }, (_, k) => fetch(`${SITE}/api/data-coverage?mode=boardCacheChunk&kind=chart&i=${i + k}&v=${cat}`).then((r) => { if (r.ok) okN++; return r.arrayBuffer(); }).catch(() => {})));
    console.log(`그래프 점 캐시 데우기 ${okN}/${NCH}`);
  } else console.log('가격 그래프 점이 너무 적어 올리지 않음');
} catch (e) { console.log('가격 그래프 점 올리기 실패(무시):', String(e).slice(0, 200)); }

// ── 단지 안 잘 거래되는 평형 요약 올리기(2026-11-21): 입찰후보 목록 간단 표기용 - 한 줄(board|band|0)
try {
  if (Object.keys(band).length >= 100) {
    for (let t = 0; t < 4; t++) {
      const { error } = await supabase.from('leader_follower_cache').upsert({ id: 'board|band|0', payload: { items: band, at: Date.now() }, fetched_at: now }, { onConflict: 'id' });
      if (!error) { console.log(`✅ 평형 활발도 올림: ${Object.keys(band).length}건`); break; }
      console.log('평형 활발도 저장 재시도', error.message); await new Promise((res) => setTimeout(res, 3000 * (t + 1)));
    }
  } else console.log('평형 활발도 계산이 너무 적어 올리지 않음');
} catch (e) { console.log('평형 활발도 올리기 실패(무시):', String(e).slice(0, 200)); }

// ── 10년 그래프 미리 계산본 올리기(단지 키 해시로 40묶음)
try {
  if (hist && Object.keys(hist).length >= 100) {
    const NCH = 40, hashOf = (id) => { let h = 0; for (const ch of String(id)) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return h % NCH; };
    const parts = Array.from({ length: NCH }, () => ({ items: {} }));
    Object.keys(hist).forEach((k) => { parts[hashOf(k)].items[k] = hist[k]; });
    for (let i = 0; i < NCH; i++) {
      for (let t = 0; t < 4; t++) {
        const { error } = await supabase.from('leader_follower_cache').upsert({ id: `board|hist|${i}`, payload: parts[i], fetched_at: now }, { onConflict: 'id' });
        if (!error) break;
        console.log('10년 그래프 저장 재시도', i, error.message);
        await new Promise((res) => setTimeout(res, 3000 * (t + 1)));
      }
    }
    const hat = Date.now();
    await supabase.from('leader_follower_cache').upsert({ id: 'board|hist|meta', payload: { n: NCH, count: Object.keys(hist).length, at: hat }, fetched_at: now }, { onConflict: 'id' });
    console.log(`✅ 10년 그래프 올림: ${NCH}묶음 / ${Object.keys(hist).length}개 단지`);
    let okN = 0;
    for (let i = 0; i < NCH; i += 8) await Promise.all(Array.from({ length: Math.min(8, NCH - i) }, (_, k) => fetch(`${SITE}/api/data-coverage?mode=boardCacheChunk&kind=hist&i=${i + k}&v=${hat}`).then((r) => { if (r.ok) okN++; return r.arrayBuffer(); }).catch(() => {})));
    console.log(`10년 그래프 캐시 데우기 ${okN}/${NCH}`);
  } else console.log('10년 그래프 미리 계산이 너무 적어 올리지 않음');
} catch (e) { console.log('10년 그래프 올리기 실패(무시):', String(e).slice(0, 200)); }

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
