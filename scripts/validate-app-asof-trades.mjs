/* 아파트 앱 실제 계산 종단 검증(실거래 기준, 2026-11-07, 사용자: 서울 표본이 왜 적나) - 경매 물건이 아니라 실제 거래를 대상으로 지역 접두(서울 '11')의 모든 구에서
   시점별 거래를 뽑아 앱의 예상매도가와 실제 거래가를 비교. 요약은 signal|__asof_val_trades__에 저장(서버 mode=sigGet&name=asof_val_trades). */
import { chromium } from 'playwright';
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';
import fs from 'fs';

const SITE = process.env.SITE_URL || 'https://1234auction.vercel.app';
const PREFIX = process.env.LAWD_PREFIX || '11';
const CUTOFFS = (process.env.CUTOFFS || '2026-02-01,2026-04-01,2026-06-01,2026-08-01,2026-09-15').split(',');
const WINDOW_DAYS = parseInt(process.env.WINDOW_DAYS || '40', 10);
const CAP = parseInt(process.env.MAX_PER_REGION || '120', 10);
const supa = createClient(process.env.SUPABASE_URL.trim(), process.env.SUPABASE_SERVICE_ROLE_KEY.trim(), { auth: { persistSession: false }, realtime: { transport: ws } });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, timezoneId: 'Asia/Seoul', locale: 'ko-KR' });
page.on('pageerror', (e) => console.log('페이지 오류:', String(e).slice(0, 160)));
console.log('앱 여는 중…');
await page.goto(SITE, { waitUntil: 'load' });
await page.waitForFunction(() => typeof auctionList !== 'undefined' && auctionList.length > 100, null, { timeout: 120000 });
await page.waitForTimeout(5000);
await page.addScriptTag({ path: 'scripts/lib/asof-harness-trades.js' });
await page.evaluate(() => { try { loadSaleRuleParams(); } catch (e) {} });
await page.waitForTimeout(4000);
const lawds = await page.evaluate((p) => __v2.lawds(p), PREFIX);
const list = Object.keys(lawds).sort();
console.log(`대상 지역 ${list.length}곳(접두 ${PREFIX})`);
const rows = [], failed = []; let eligibleAll = 0;
for (const l of list) {
  try {
    const r = await page.evaluate(([a, t, c, w, cap]) => __v2.processRegionTrades(a, t, c, w, cap), [l, lawds[l], CUTOFFS, WINDOW_DAYS, CAP]);
    r.rows.forEach((x) => rows.push(x)); eligibleAll += r.eligible;
  } catch (e) { failed.push(l); console.log(`❌ ${l}: ${String(e.message || e).slice(0, 140)}`); }
}
await browser.close().catch(() => {});
fs.writeFileSync('asof-trades.json', JSON.stringify(rows));
const med = (a) => { a = a.slice().sort((x, y) => x - y); const k = a.length >> 1; return a.length % 2 ? a[k] : (a[k - 1] + a[k]) / 2; };
const q = (a, p) => { a = a.slice().sort((x, y) => x - y); return a[Math.floor((a.length - 1) * p)]; };
const stat = (list) => {
  const ok = list.filter((r) => r.sale > 0 && r.truth && r.truth.length); if (!ok.length) return null;
  const e = ok.map((r) => r.truth[0] / r.sale - 1);   // 정답(실제 거래가)÷예상 - 1 (양수 = 예상이 낮음)
  return { n: e.length, 오차중앙: +(med(e.map(Math.abs)) * 100).toFixed(2), 치우침: +(med(e) * 100).toFixed(2), 하방10: +(q(e, 0.1) * 100).toFixed(1), 하방25: +(q(e, 0.25) * 100).toFixed(1), 상방75: +(q(e, 0.75) * 100).toFixed(1), 상방90: +(q(e, 0.9) * 100).toFixed(1),
    오차10퍼초과비율: +(e.filter((x) => Math.abs(x) > 0.1).length / e.length * 100).toFixed(1), 높게예상10퍼: +(e.filter((x) => x < -0.1).length / e.length * 100).toFixed(1), 낮게예상10퍼: +(e.filter((x) => x > 0.1).length / e.length * 100).toFixed(1) };
};
const tierOf = (r) => r.sale == null ? 'E 값 없음' : (/가중 중위값|가장 최근 3건/.test(r.by) ? 'A 6개월 같은 평형 3건 이상' : (/3건 미만/.test(r.by) ? 'B 거래 부족 → 이전 거래·다른 평형 추론' : (/같은 단지 거래/.test(r.by) ? 'C 같은 단지 거래 없음 → 주변 비교' : 'D 기존 방식(주변 비교 등)')));
const summary = { at: new Date().toISOString(), prefix: PREFIX, cutoffs: CUTOFFS, windowDays: WINDOW_DAYS, cap: CAP, regions: list.length, failedRegions: failed, total: rows.length, eligible: eligibleAll, errors: rows.filter((r) => r.err).length, all: stat(rows), byTier: {}, byCutoff: {}, byFloor: {}, byRegion: {} };
for (const t of [...new Set(rows.map(tierOf))].sort()) summary.byTier[t] = stat(rows.filter((r) => tierOf(r) === t));
for (const c of CUTOFFS) summary.byCutoff[c] = stat(rows.filter((r) => r.cutoff === c));
summary.byFloor = { '1~2층': stat(rows.filter((r) => parseInt(r.floor) >= 1 && parseInt(r.floor) <= 2)), '3~9층': stat(rows.filter((r) => parseInt(r.floor) >= 3 && parseInt(r.floor) <= 9)), '10층+': stat(rows.filter((r) => parseInt(r.floor) >= 10)) };
for (const l of list) { const s = stat(rows.filter((r) => r.lawd === l)); if (s && s.n >= 40) summary.byRegion[l] = s; }
console.log(JSON.stringify(summary, null, 1));
const { error } = await supa.from('leader_follower_cache').upsert({ id: 'signal|__asof_val_trades__', payload: summary, fetched_at: summary.at }, { onConflict: 'id' });
console.log(error ? '저장 실패: ' + error.message : '✅ 저장');
if (!rows.length) process.exit(1);
