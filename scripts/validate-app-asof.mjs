/* 앱 실제 계산 종단 검증(2026-10-19, 사용자: "앱이 실제로 내는 값이 정확한지 확인") - 가상 브라우저로 앱을 열고, 지역마다 거래 자료를 받아 과거 시점(cutoff)으로 되돌린 뒤
   앱의 실제 함수(computeBidBoardRow)로 경매 아파트의 예상매도가를 계산하고, 그 시점 이후 60일 안에 실제로 거래된 같은 단지·같은 평형(±3㎡) 가격과 비교한다.
   (파이썬으로 규칙을 재현한 설계 검증과 달리 앱이 실제로 화면에 내는 값을 그대로 검증. 지역 단위로 처리해 전송량을 아끼고 지역별로 이어서 할 수 있음)
   - 지역별 결과는 asof-partial/r-<지역코드>.json에 저장 → 재시도·이어서 하기(resume_run_id)에서 끝난 지역은 건너뜀
   - 실패 원인은 validate-app-asof-failures.json과 서버(signal|__asof_val_log__)에 남김
   결과: validate-app-asof.json(행 단위) + 요약 출력 + Supabase leader_follower_cache 'signal|__asof_val__' */
import { chromium } from 'playwright';
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';
import fs from 'fs';

const SITE = process.env.SITE_URL || 'https://1234auction.vercel.app';
const CUTOFFS = (process.env.CUTOFFS || '2026-04-01,2026-05-15,2026-07-01,2026-08-15').split(',');
const WINDOW_DAYS = parseInt(process.env.WINDOW_DAYS || '60', 10);
const CAP = parseInt(process.env.MAX_PER_REGION || '25', 10);       // 지역·시점마다 최대 물건 수
const REGION_LIMIT = parseInt(process.env.REGION_LIMIT || '0', 10);  // 시험용: 앞의 N개 지역만(0 = 전부)
const PARTIAL_DIR = 'asof-partial';
fs.mkdirSync(PARTIAL_DIR, { recursive: true });
const regionFile = (l) => `${PARTIAL_DIR}/r-${l}.json`;
const REGIONS_FILE = `${PARTIAL_DIR}/_regions.json`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ── 실패 기록: 어느 단계·어느 지역에서 어떤 오류가 났는지와 그때 페이지의 오류를 파일·서버 저장소에 남겨 바로 고쳐서 이어 돌릴 수 있게 함 ──
const FAIL_FILE = 'validate-app-asof-failures.json';
const failureLog = fs.existsSync(FAIL_FILE) ? JSON.parse(fs.readFileSync(FAIL_FILE, 'utf8')) : [];
const pageErrors = [];
let currentStage = '시작', currentRegion = null;
const supa = process.env.SUPABASE_URL ? createClient(process.env.SUPABASE_URL.trim(), process.env.SUPABASE_SERVICE_ROLE_KEY.trim(), { auth: { persistSession: false }, realtime: { transport: ws } }) : null;
async function recordFailure(stage, region, err, extra) {
  const e = err instanceof Error ? err : new Error(String(err));
  const rec = { at: new Date().toISOString(), runId: process.env.GITHUB_RUN_ID || null, attempt: parseInt(process.env.ATTEMPT || '1', 10), stage, region: region || null,
    message: String(e.message || e).slice(0, 400), stack: String(e.stack || '').split('\n').slice(0, 6).join(' | ').slice(0, 800), pageErrors: pageErrors.slice(-8), ...(extra || {}) };
  failureLog.push(rec);
  try { fs.writeFileSync(FAIL_FILE, JSON.stringify(failureLog, null, 1)); } catch (x) {}
  console.log(`❌ 실패 기록: [${stage}${region ? ' · ' + region : ''}] ${rec.message}`);
  if (supa) { try { await supa.from('leader_follower_cache').upsert({ id: 'signal|__asof_val_log__', payload: { updatedAt: rec.at, runId: rec.runId, entries: failureLog.slice(-30) }, fetched_at: rec.at }, { onConflict: 'id' }); } catch (x) {} }
}
process.on('unhandledRejection', async (e) => { await recordFailure(currentStage, currentRegion, e, { uncaught: true }); process.exit(1); });
process.on('uncaughtException', async (e) => { await recordFailure(currentStage, currentRegion, e, { uncaught: true }); process.exit(1); });

async function withRetry(label, region, fn, tries = 3) {
  let last;
  for (let i = 1; i <= tries; i++) {
    try { return await fn(); }
    catch (e) { last = e; console.log(`  ${label} 실패(${i}/${tries}): ${String(e.message || e).slice(0, 120)}`); await recordFailure(label, region, e, { retry: `${i}/${tries}` }); await sleep(3000 * i); }
  }
  throw last;
}

let regionList = fs.existsSync(REGIONS_FILE) ? JSON.parse(fs.readFileSync(REGIONS_FILE, 'utf8')) : null;
const rows = [], failedRegions = [];
const allDone = () => regionList && regionList.every((l) => fs.existsSync(regionFile(l)));

if (!allDone()) { // 모든 지역이 이전 시도에서 끝났으면 앱을 다시 열지 않음
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, timezoneId: 'Asia/Seoul', locale: 'ko-KR' });
  let pageCrashed = false;
  page.on('pageerror', (e) => { pageErrors.push(String(e).slice(0, 200)); });
  page.on('console', (m) => { if (m.type() === 'error') pageErrors.push('console: ' + m.text().slice(0, 160)); });
  page.on('crash', () => { pageCrashed = true; console.log('페이지가 멈췄어요(crash)'); });
  currentStage = '앱 열기'; console.log('앱 여는 중…');
  const resp = await page.goto(SITE, { waitUntil: 'load' });
  if (!resp || resp.status() >= 400) throw new Error(`앱이 열리지 않아요(HTTP ${resp && resp.status()}) - Vercel 정지·점검 여부를 확인하세요`);
  await page.waitForFunction(() => typeof auctionList !== 'undefined' && auctionList.length > 100, null, { timeout: 120000 });
  await page.waitForTimeout(5000);
  currentStage = '검증 도구 심기';
  await page.addScriptTag({ path: 'scripts/lib/asof-harness.js' });
  await page.evaluate(() => { try { loadSaleRuleParams(); } catch (e) {} });
  await page.waitForTimeout(4000); // 서버의 회전율·전세가율 보정 표를 받음(앱이 실제로 쓰는 값)
  const regions = await page.evaluate(() => __v.regions());
  regionList = Object.keys(regions).sort();
  if (REGION_LIMIT > 0) regionList = regionList.slice(0, REGION_LIMIT);
  fs.writeFileSync(REGIONS_FILE, JSON.stringify(regionList));
  console.log(`대상 지역 ${regionList.length}곳(아파트 경매물건 ${Object.values(regions).reduce((a, b) => a + b, 0)}건)`);
  currentStage = '지역별 검증';
  let n = 0;
  for (const lawd of regionList) {
    n++; currentRegion = lawd;
    if (fs.existsSync(regionFile(lawd))) { JSON.parse(fs.readFileSync(regionFile(lawd), 'utf8')).forEach((r) => rows.push(r)); continue; }
    if (pageCrashed) { failedRegions.push(lawd); continue; }
    try {
      const res = await withRetry('지역 계산', lawd, () => page.evaluate(([l, c, w, cap]) => __v.processRegion(l, c, w, cap), [lawd, CUTOFFS, WINDOW_DAYS, CAP]));
      fs.writeFileSync(regionFile(lawd), JSON.stringify(res.rows));
      res.rows.forEach((r) => rows.push(r));
      if (n % 20 === 0) console.log(`  ${n}/${regionList.length} 지역 · 누적 ${rows.length}건`);
    } catch (e) {
      failedRegions.push(lawd);
      await recordFailure('지역 실패', lawd, e);
      if (pageCrashed) console.log('페이지가 죽어서 남은 지역은 다음 시도에서 이어서 합니다');
    }
  }
  await browser.close().catch(() => {});
} else {
  console.log('모든 지역이 이전 시도에서 끝났어요 - 저장된 결과로 요약만 만듭니다');
  for (const l of regionList) JSON.parse(fs.readFileSync(regionFile(l), 'utf8')).forEach((r) => rows.push(r));
}
fs.writeFileSync('validate-app-asof.json', JSON.stringify(rows));

// ── 요약 ──
const tierOf = (r) => r.sale == null ? 'E 값 없음' : (/가중 중위값|가장 최근 3건/.test(r.by) ? 'A 6개월 같은 평형 3건 이상' : (/3건 미만/.test(r.by) ? 'B 거래 부족 → 이전 거래·다른 평형 추론' : (/같은 단지 거래가 없어/.test(r.by) ? 'C 같은 단지 거래 없음 → 주변 비교' : 'D 기존 방식(주변 비교 등)')));
const med = (a) => { a = a.slice().sort((x, y) => x - y); const k = a.length >> 1; return a.length % 2 ? a[k] : (a[k - 1] + a[k]) / 2; };
const q = (a, p) => { a = a.slice().sort((x, y) => x - y); return a[Math.floor((a.length - 1) * p)]; };
const stat = (list) => {
  const ok = list.filter((r) => r.sale > 0 && r.truth && r.truth.length);
  if (!ok.length) return null;
  const e = ok.map((r) => med(r.truth) / r.sale - 1);   // 정답 = 창 안 거래가 중앙값
  const f = ok.map((r) => r.truth[0] / r.sale - 1);     // 정답 = 창 안 첫 거래가
  return { n: e.length, 오차중앙: +(med(e.map(Math.abs)) * 100).toFixed(2), 치우침: +(med(e) * 100).toFixed(2), 하방10: +(q(e, 0.1) * 100).toFixed(1), 하방25: +(q(e, 0.25) * 100).toFixed(1), 첫거래오차중앙: +(med(f.map(Math.abs)) * 100).toFixed(2), 첫거래치우침: +(med(f) * 100).toFixed(2), 오차10퍼초과비율: +(e.filter((x) => Math.abs(x) > 0.1).length / e.length * 100).toFixed(1) };
};
const summary = { at: new Date().toISOString(), failures: failureLog.length, failedRegions, regions: regionList ? regionList.length : 0, cutoffs: CUTOFFS, windowDays: WINDOW_DAYS, maxPerRegion: CAP, total: rows.length, errors: rows.filter((r) => r.err).length, noValue: rows.filter((r) => r.sale == null).length, byClass: {}, byTier: {}, byClassTier: {} };
for (const cls of ['서울', '경기·인천', '지방']) summary.byClass[cls] = stat(rows.filter((r) => r.cls === cls));
for (const t of [...new Set(rows.map(tierOf))].sort()) { summary.byTier[t] = stat(rows.filter((r) => tierOf(r) === t)); for (const cls of ['서울', '경기·인천', '지방']) { const s = stat(rows.filter((r) => tierOf(r) === t && r.cls === cls)); if (s && s.n >= 30) summary.byClassTier[cls + ' · ' + t] = s; } }
summary.all = stat(rows);
console.log('\n===== 앱 실제 출력 종단 검증 요약 =====');
console.log(JSON.stringify(summary, null, 1));
if (supa) {
  const { error } = await supa.from('leader_follower_cache').upsert({ id: 'signal|__asof_val__', payload: summary, fetched_at: new Date().toISOString() }, { onConflict: 'id' });
  console.log(error ? '요약 저장 실패: ' + error.message : '✅ 요약 저장');
}
if (failedRegions.length) { console.log(`⚠️ 실패한 지역 ${failedRegions.length}곳 - 작업을 다시 시도하면 이 지역만 이어서 합니다`); process.exit(2); }
