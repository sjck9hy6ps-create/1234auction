/* 앱 실제 계산 종단 검증(2026-10-19, 사용자: "앱이 실제로 내는 값이 정확한지 확인") - 가상 브라우저로 앱을 열고, 거래 자료를 과거 시점(cutoff)으로 되돌린 뒤
   앱의 실제 함수(computeBidBoardRow)로 경매물건의 예상매도가를 계산하고, 그 시점 이후 60일 안에 실제로 거래된 같은 단지·같은 평형(±3㎡) 가격과 비교한다.
   (파이썬으로 규칙을 재현한 설계 검증과 달리 앱이 실제로 화면에 내는 값을 그대로 검증)
   결과: validate-app-asof.json(행 단위) + 요약 출력 + Supabase leader_follower_cache 'signal|__asof_val__' */
import { chromium } from 'playwright';
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';
import fs from 'fs';

const SITE = process.env.SITE_URL || 'https://1234auction.vercel.app';
const CUTOFFS = (process.env.CUTOFFS || '2026-04-01,2026-05-15,2026-07-01,2026-08-15').split(',');
const WINDOW_DAYS = parseInt(process.env.WINDOW_DAYS || '60', 10);
const MAX_SUBJECTS = parseInt(process.env.MAX_SUBJECTS || '2500', 10);
const supabase = process.env.SUPABASE_URL ? createClient(process.env.SUPABASE_URL.trim(), process.env.SUPABASE_SERVICE_ROLE_KEY.trim(), { auth: { persistSession: false }, realtime: { transport: ws } }) : null;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, timezoneId: 'Asia/Seoul', locale: 'ko-KR' });
page.on('pageerror', (e) => console.log('페이지 오류:', String(e).slice(0, 160)));
console.log('앱 여는 중…');
await page.goto(SITE, { waitUntil: 'load' });
await page.waitForTimeout(10000);
// 1) 모든 지역 거래 자료를 메모리에 올림(입찰후보 계산과 같은 방식)
await page.evaluate(() => { try { document.getElementById('remind-panel').style.display = 'none'; } catch (e) {} try { document.getElementById('bid-board').style.display = 'flex'; } catch (e) {} forceRefreshBidBoard(); });
const t0 = Date.now();
for (;;) {
  await page.waitForTimeout(15000);
  const st = await page.evaluate(() => ({ prog: (document.getElementById('bb-progress') || {}).innerText || '', running: !!window.bidBoardRunning, rows: bidBoardRows.length, pending: bidBoardRows.filter((r) => r.pending).length }));
  console.log(`${Math.round((Date.now() - t0) / 1000)}s · ${st.prog || '(표시 없음)'} · 행 ${st.rows} · 대기 ${st.pending}`);
  if (!st.running && !st.prog && st.rows > 0 && st.pending === 0) break;
  if (Date.now() - t0 > 60 * 60 * 1000) { console.log('시간 초과'); break; }
}
await page.waitForTimeout(20000); // 배경 작업이 가라앉도록
// 2) 되돌리기·검증 도구를 페이지에 심음
await page.evaluate(() => {
  const RD = Date;
  window.__v = {
    RD, full: allAptList, rent: Object.assign({}, rentCacheByLawd), subjects: [], truth: {},
    prepare(cStr, windowDays, maxN) {
      const C = new RD(cStr + 'T00:00:00+09:00').getTime(), end = C + windowDays * 864e5;
      // 정답: 같은 단지·같은 평형(±3㎡) 중개 거래 중 cutoff ~ cutoff+windowDays 사이(되돌리기 전 전체 자료로 찾음)
      const subs = [];
      auctionList.forEach((a) => {
        if (a.propType !== 'apt' || a.isBacktest || !a.lat || !a.lon || !(parseFloat(a.pyung) > 0)) return;
        const lawd = bidBoardLawdOf(a); if (!lawd || !dataCache[lawd]) return;
        const bj = fullBunjiFromAddr(a.addr, a.dong, a.bunji), area = parseFloat(a.pyung) * 3.305785, tr = [];
        ownComplexEntries(a, bj, 'apt').forEach((ap) => (ap.trades || []).forEach((t) => {
          if (t.dealing_type === '직거래' || Math.abs(t.area - area) > 3) return;
          const d = new RD(t.year, t.month - 1, t.day).getTime();
          if (d >= C && d < end) tr.push({ d, p: parseInt(t.amount) });
        }));
        if (tr.length) { tr.sort((x, y) => x.d - y.d); subs.push({ id: a.id, truth: tr }); }
      });
      // 무작위로 maxN건만(재현 가능하게 id 정렬 후 간격 추출)
      subs.sort((x, y) => String(x.id).localeCompare(String(y.id)));
      const step = Math.max(1, Math.ceil(subs.length / maxN)); this.subjects = subs.filter((_, i) => i % step === 0);
      this.C = C; return { eligible: subs.length, used: this.subjects.length };
    },
    rewind() {
      const cut = this.C, R = this.RD;
      class FD extends R { constructor(...a) { if (a.length === 0) super(cut); else super(...a); } static now() { return cut; } }
      window.Date = FD;
      const list = [];
      this.full.forEach((ap) => {
        if (!ap.__ot) ap.__ot = ap.trades;
        const tr = ap.__ot.filter((t) => new R(t.year, t.month - 1, t.day).getTime() < cut);
        if (!tr.length) return;
        list.push(Object.assign({}, ap, { trades: tr, latest: tr[0] }));
      });
      allAptList = list; buildAptMatchIndex();
      Object.keys(this.rent).forEach((k) => { rentCacheByLawd[k] = this.rent[k].filter((r) => { const ds = String(r.deal_date || ''); return ds.length < 8 || new R(+ds.slice(0, 4), +ds.slice(4, 6) - 1, +ds.slice(6, 8)).getTime() < cut; }); });
      auctionWonEstCache = {}; regionPpmIdxCache = {}; try { calcPriceGrades(); } catch (e) {}
      return { apts: list.length };
    },
    run(from, to) {
      const out = [], byId = {}; auctionList.forEach((a) => { byId[a.id] = a; });
      this.subjects.slice(from, to).forEach((s) => {
        const a = byId[s.id]; if (!a) return;
        const a2 = Object.assign({}, a, { id: 'asof_' + a.id, bidDate: new this.RD(this.C + 35 * 864e5).toISOString().slice(0, 10) });
        let row = null, err = null; try { row = computeBidBoardRow(a2); } catch (e) { err = String(e.message || e).slice(0, 80); }
        out.push({ id: a.id, cls: row && row.regionCls, sale: row && row.sale, by: row && (row.saleSimBy || ''), n6: row && row.ownStats ? row.ownStats.n6 : null, weak: !!(row && row.saleFb && row.saleFb.weak), pyung: a.pyung, floor: a.floor, truth: s.truth.map((t) => t.p), err });
      });
      return out;
    },
    restore() { window.Date = this.RD; allAptList = this.full; buildAptMatchIndex(); Object.keys(this.rent).forEach((k) => { rentCacheByLawd[k] = this.rent[k]; }); auctionWonEstCache = {}; regionPpmIdxCache = {}; }
  };
});
// 3) 시점별 실행
const rows = [];
for (const c of CUTOFFS) {
  const info = await page.evaluate(([c, w, m]) => __v.prepare(c, w, m), [c, WINDOW_DAYS, MAX_SUBJECTS]);
  console.log(`cutoff ${c}: 정답 거래가 있는 아파트 경매물건 ${info.eligible}건 → ${info.used}건 사용`);
  await page.evaluate(() => __v.rewind());
  for (let i = 0; i < info.used; i += 300) {
    const part = await page.evaluate(([a, b]) => __v.run(a, b), [i, i + 300]);
    part.forEach((r) => { r.cutoff = c; rows.push(r); });
    console.log(`  ${Math.min(i + 300, info.used)}/${info.used}`);
  }
  await page.evaluate(() => __v.restore());
}
await browser.close();
fs.writeFileSync('validate-app-asof.json', JSON.stringify(rows));
// 4) 요약
const tierOf = (r) => r.sale == null ? 'E 값 없음' : (/가중 중위값|가장 최근 3건/.test(r.by) ? 'A 6개월 같은 평형 3건 이상' : (/3건 미만/.test(r.by) ? 'B 거래 부족 → 이전 거래·다른 평형 추론' : (/같은 단지 거래가 없어/.test(r.by) ? 'C 같은 단지 거래 없음 → 주변 비교' : 'D 기존 방식(주변 비교 등)')));
const med = (a) => { a = a.slice().sort((x, y) => x - y); const k = a.length >> 1; return a.length % 2 ? a[k] : (a[k - 1] + a[k]) / 2; };
const q = (a, p) => { a = a.slice().sort((x, y) => x - y); return a[Math.floor((a.length - 1) * p)]; };
const stat = (list) => {
  const e = list.filter((r) => r.sale > 0 && r.truth.length).map((r) => med(r.truth) / r.sale - 1); // 정답 = 창 안 거래가 중앙값
  const f = list.filter((r) => r.sale > 0 && r.truth.length).map((r) => r.truth[0] / r.sale - 1);   // 정답 = 창 안 첫 거래가
  if (!e.length) return null;
  return { n: e.length, 오차중앙: +(med(e.map(Math.abs)) * 100).toFixed(2), 치우침: +(med(e) * 100).toFixed(2), 하방10: +(q(e, 0.1) * 100).toFixed(1), 하방25: +(q(e, 0.25) * 100).toFixed(1), 첫거래오차중앙: +(med(f.map(Math.abs)) * 100).toFixed(2), 첫거래치우침: +(med(f) * 100).toFixed(2) };
};
const summary = { at: new Date().toISOString(), cutoffs: CUTOFFS, windowDays: WINDOW_DAYS, total: rows.length, errors: rows.filter((r) => r.err).length, noValue: rows.filter((r) => r.sale == null).length, byClass: {}, byTier: {}, byClassTier: {} };
for (const cls of ['서울', '경기·인천', '지방']) summary.byClass[cls] = stat(rows.filter((r) => r.cls === cls));
for (const t of [...new Set(rows.map(tierOf))].sort()) { summary.byTier[t] = stat(rows.filter((r) => tierOf(r) === t)); for (const cls of ['서울', '경기·인천', '지방']) { const s = stat(rows.filter((r) => tierOf(r) === t && r.cls === cls)); if (s && s.n >= 30) summary.byClassTier[cls + ' · ' + t] = s; } }
summary.all = stat(rows);
console.log('\n===== 앱 실제 출력 종단 검증 요약 =====');
console.log(JSON.stringify({ ...summary }, null, 1));
if (supabase) {
  const { error } = await supabase.from('leader_follower_cache').upsert({ id: 'signal|__asof_val__', payload: summary, fetched_at: new Date().toISOString() }, { onConflict: 'id' });
  console.log(error ? '요약 저장 실패: ' + error.message : '✅ 요약 저장');
}
