/* 🏘️ 빌라 과거 낙찰 사례 채점 (2026-11-10, 사용자: 과거 낙찰 사례로 테스트해줘 - API 호출·하루 용량에 막히지 않게 장치를 마련해서)
   입력: villa-cases-asof.json(2026-06 이후 낙찰 사례 + 그 당시 시점 종합 시세·하위값·대장 값), villa-winbid-pre.json(2026-06 이전 사례로만 학습한 낙찰가 모델)
   앱의 실제 계산(필요 마진 villaMarginPlan · 예상 낙찰가 villaWinbid · 추천가 villaBidPlan · 이슈 의심 villaIssueFor)을 가상 브라우저에서 그대로 돌려 추천가·예상 낙찰가·낙찰 가능성을 실제 낙찰가와 비교한다.
   🛡️ 멈추지 않게 하는 장치(사용자 2026-11-10: 시험을 멈추는 장치가 아니라 멈춤을 피하는 장치로):
     ① 외부·서버 호출을 아예 만들지 않음 - 앱이 부르는 모든 /api/*·카카오·네이버·공공데이터 요청은 가상 브라우저 안에서 빈 응답으로 받아 서버·외부 API 한도를 쓰지 않음(상한이 필요 없는 구조). 필요한 값(내 자산 세금 설정)만 한 번 받고, 실패하면 기다렸다 다시 시도(대기·재시도, 끝내 안 되면 기본값으로 계속)
     ② 서버가 느려도 기다렸다 진행(기다림은 길어도 시험은 계속) - 입력은 파일이라 서버 상태와 무관
     ③ 요청 수가 많아지면 중단하지 않고 그 요청도 로컬에서 막은 채 계속 / 시간이 길어져도 중단하지 않고 계속(작업 자체의 제한 시간만 있음)
     ④ 이어하기: 사례를 BATCH 단위로 처리하며 매번 결과를 파일에 저장 → 중간에 죽으면 같은 파일에서 이어서 계속(RESUME) / 가상 브라우저가 멈추면 새로 띄워 같은 묶음을 더 작게 나눠 다시 시도
   출력: villa-score.json, villa-score-rows.json */
import { chromium } from 'playwright';
import fs from 'fs';

const SITE = process.env.SITE_URL || 'https://1234auction.vercel.app';
const CASES = process.env.CASES || 'villa-cases-asof.json';
const PRE = process.env.PRE_MODEL || 'villa-winbid-pre.json';
const MAX_NET = parseInt(process.env.MAX_NET_CALLS || '40', 10);   // 허용할 화면 파일 요청 수의 기준(넘어도 멈추지 않고 나머지를 로컬에서 막음)
const BATCH = parseInt(process.env.BATCH || '150', 10);
const T0 = Date.now();

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// 서버 상태: 느리면 기다렸다가(최대 20분, 지수 대기) 계속 - 이 도구는 서버를 거의 안 부르므로 끝내 느려도 진행
{
  let wait = 15000, waited = 0;
  for (;;) {
    const t = Date.now();
    const ok = await fetch(SITE + '/api/data-coverage', { signal: AbortSignal.timeout(20000) }).then((r) => r.status === 200).catch(() => false);
    const ms = Date.now() - t;
    if (ok && ms < 4000) { console.log(`서버 확인 정상 ${ms}ms`); break; }
    if (waited >= 20 * 60000) { console.log('서버가 계속 느리지만 이 도구는 파일로 진행하므로 계속해요'); break; }
    console.log(`서버가 느려요(${ok ? ms + 'ms' : '오류'}) - ${Math.round(wait / 1000)}초 기다렸다 다시 확인`);
    await sleep(wait); waited += wait; wait = Math.min(wait * 2, 120000);
  }
}
const cases = JSON.parse(fs.readFileSync(CASES, 'utf8')), pre = JSON.parse(fs.readFileSync(PRE, 'utf8'));
// 필요한 외부 값 1건: 내 자산(세금 계산용 주택 수·소득 설정) - 한 번만 받음(Redis 읽기 1회)
let assets = [];
for (let k = 0, wait = 10000; k < 6; k++, wait = Math.min(wait * 2, 120000)) {
  const r = await fetch(SITE + '/api/auction?kind=myAssets', { signal: AbortSignal.timeout(30000) }).then((x) => (x.ok ? x.json() : null)).catch(() => null);
  if (Array.isArray(r)) { assets = r; break; }
  console.log(`내 자산 못 받음(${k + 1}/6) - ${Math.round(wait / 1000)}초 뒤 다시`); await sleep(wait);
}
console.log('내 자산 항목', assets.length, assets.length ? '(세금 계산용, 1회 호출)' : '(받지 못해 기본 세금 설정으로 계속)');

let allowed = 0, blocked = 0; const blockedKinds = {};
let browser = null, page = null;
async function startPage() {   // 가상 브라우저를 띄워 앱 계산 함수가 준비될 때까지 기다림(실패하면 새로 띄워 다시 - 이어하기용)
  try { if (browser) await browser.close(); } catch (e) {}
  browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1200, height: 800 }, timezoneId: 'Asia/Seoul', locale: 'ko-KR' });
  page = await ctx.newPage();
  page.on('pageerror', (e) => { const m = String(e).slice(0, 120); if (!/kakao|naver|Script error/.test(m)) console.log('페이지 오류:', m); });
  await ctx.route('**/*', (route) => {
    const req = route.request(), u = new URL(req.url()), rt = req.resourceType();
    const same = u.origin === new URL(SITE).origin;
    // 앱 화면 파일(문서·스크립트·스타일·이미지)만 받음 - 요청 수가 많아져도 멈추지 않고 계속(필요 이상은 로컬에서 막음)
    if (same && (rt === 'document' || rt === 'script' || rt === 'stylesheet' || rt === 'image' || rt === 'font' || rt === 'manifest') && allowed < MAX_NET * 5) { allowed++; return route.continue(); }
    if (same && /\/(villa-winbid|winbid-model|apt-stack|liquidity-curve)\.json$/.test(u.pathname)) return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
    // 그 밖의 모든 요청(/api/*·외부 사이트)은 가상 브라우저 안에서 빈 응답 - 실제 서버·외부 API 한도를 쓰지 않음
    blocked++; const k = (same ? '내 서버 ' : '') + u.host + (same ? u.pathname.split('/').slice(0, 3).join('/') : ''); blockedKinds[k] = (blockedKinds[k] || 0) + 1;
    if (same && u.pathname.startsWith('/api/')) return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    return route.abort();
  });
  await page.goto(SITE, { waitUntil: 'domcontentloaded', timeout: 180000 });
  await page.waitForFunction(() => typeof villaMarginPlan === 'function' && typeof villaWinbid === 'function' && typeof villaBidPlan === 'function' && typeof solveAuctionBidFromRecord === 'function' && typeof myAssets !== 'undefined', null, { timeout: 180000 });
  await page.waitForTimeout(3000);
  await page.evaluate(([as, model]) => {   // 내 자산·낙찰가 모델 주입(사전 학습본)
    myAssets = { loaded: true, items: (as || []).filter((x) => x && x.id !== 'profile'), profile: ((as || []).filter((x) => x && x.id === 'profile')[0]) || null };
    villaWinModel = model;
  }, [assets, pre]);
}
async function startWithRetry() {
  for (let k = 0, wait = 10000; ; k++, wait = Math.min(wait * 2, 120000)) {
    try { await startPage(); console.log('앱 함수 준비. 허용 요청', allowed, '/ 차단 요청', blocked); return; }
    catch (e) { console.log(`앱 준비 실패(${k + 1}회): ${String(e.message || e).slice(0, 100)} - ${Math.round(wait / 1000)}초 뒤 다시`); await sleep(wait); if (k >= 8) { console.log('앱 준비가 계속 안 돼 지금까지 결과로 채점'); return; } }
  }
}
// 이어하기: 같은 이름의 결과 파일이 있으면 이미 한 사례는 건너뜀
const RES_FILE = 'villa-score-rows.json';
let results = []; try { if (process.env.RESUME === '1' && fs.existsSync(RES_FILE)) results = JSON.parse(fs.readFileSync(RES_FILE, 'utf8')); } catch (e) {}
const doneIds = new Set(results.map((r) => String(r.id)));
const todo = cases.filter((c) => !doneIds.has(String(c.id)));
console.log(`전체 ${cases.length}건 중 이미 한 ${doneIds.size}건 제외, 남은 ${todo.length}건`);
await startWithRetry();

const EVAL_FN = (cs) => cs.map((c) => {
  try {
    const sale = String(c.sale), bd = sale.slice(0, 4) + '-' + sale.slice(4, 6) + '-' + sale.slice(6, 8);
    const area = c.area, pyung = Math.round(area / 3.305785 * 10) / 10;
    const a = { id: 'vc_' + c.id, caseNo: c.caseNo, addr: c.addr, dong: c.dong, bunji: c.bunji, pyung: String(pyung), floor: String(c.floor == null ? '' : c.floor), buildYear: c.by ? String(Math.round(c.by)) : '', bidDate: bd, minBid: String(Math.round(c.minbid)), appraisal: String(Math.round(c.appr || 0)), propType: 'villa', lat: c.lat, lon: c.lon };
    const row = { id: a.id, a: a, type: 'villa', minBid: Math.round(c.minbid), pyung: pyung, name: c.addr, region: villaRegionLabel(c.addr), metro: true };
    const est = c.est, l10 = Math.min(c.q10 || est * 0.85, est), l25 = Math.min(c.q25 || est * 0.92, est);
    const ve = { est: Math.round(est), lvl: c.lvl, by: c.by || null, disp: c.disp == null ? null : c.disp, n1: c.nBld, n2: c.nDong, lo: Math.round(l25), hi: Math.round(est * 1.1), errPct: 10, stack: { est: Math.round(est), l25: Math.round(l25), l10: Math.round(l10), rel10: (est - l10) / est, rel25: (est - l25) / est, nr: c.nRad } };
    const title = c.elv == null || c.grnd == null ? null : { useAprDay: c.by ? String(Math.round(c.by)) + '0101' : null, rideElvtCnt: c.elv ? 1 : 0, emgenElvtCnt: 0, grndFlrCnt: c.grnd, hhldCnt: c.hh };
    const mp = villaMarginPlan(row, ve, title), wb = villaWinbid(row, ve, title), pn = villaBidPlan(row, ve, mp, wb);
    let issue = null; try { issue = villaIssueFor(row, ve); } catch (e) {}
    const fl = parseInt(a.floor, 10), pe = pn && pn.ev;
    let why = '';
    if (mp && mp.age != null && mp.age <= VILLA_NEW_YEARS) why = '신축';
    else if (issue) why = '이슈';
    else if (!pn || pn.infeasible || !pe) why = '마진 부족';
    else if (ve.lvl === '동1~4' || ve.lvl === '시군구') why = '근거 약함';
    else if (c.nRad != null && c.lat != null && c.nRad <= 2) why = '반경 거래 적음';   // 좌표가 없는 사례는 반경을 못 재므로 이 규칙을 적용하지 않음
    else if (!isNaN(fl) && fl <= 0) why = '지하';
    else if (pe.p < VILLA_VISIT_MIN_P) why = '낙찰 가능성 낮음';
    return { id: c.id, sale: c.sale, actual: c.actual, minbid: c.minbid, est: ve.est, lvl: c.lvl, sido: c.sido, wbPrice: wb ? wb.price : null, margin: mp ? mp.margin : null, mpBid: mp ? mp.bid : null, rec: pe ? pe.bid : null, p: pe ? pe.p : null, net: pe ? pe.net : null, go: !why, why: why, bidders: c.bidders };
  } catch (e) { return { id: c.id, err: String(e.message || e).slice(0, 120) }; }
});
async function runChunk(chunk, depth = 0) {   // 묶음이 실패하면 새 브라우저로 반으로 쪼개 다시(끝내 안 되면 그 묶음만 오류로 표시하고 다음으로)
  try { return await page.evaluate(EVAL_FN, chunk); }
  catch (e) {
    console.log(`묶음 실패(${chunk.length}건, 깊이 ${depth}): ${String(e.message || e).slice(0, 100)}`);
    if (depth >= 3 || chunk.length <= 1) return chunk.map((c) => ({ id: c.id, err: '묶음 실패' }));
    await startWithRetry();
    const h = Math.ceil(chunk.length / 2), a = await runChunk(chunk.slice(0, h), depth + 1), b = await runChunk(chunk.slice(h), depth + 1);
    return a.concat(b);
  }
}
for (let i = 0; i < todo.length; i += BATCH) {
  const out = await runChunk(todo.slice(i, i + BATCH));
  results.push(...out);
  fs.writeFileSync(RES_FILE, JSON.stringify(results));   // 묶음마다 저장 - 중간에 죽어도 여기서 이어감
  console.log(`처리 ${results.length}/${cases.length} (허용 ${allowed} 차단 ${blocked}) 경과 ${Math.round((Date.now() - T0) / 60000)}분`);
}
await browser.close().catch(() => {});

// ── 채점 ──
const R = results.filter((r) => !r.err && r.actual > 0 && r.est > 0), med = (a) => { const b = a.slice().sort((x, y) => x - y), n = b.length; return n ? (n % 2 ? b[(n - 1) / 2] : (b[n / 2 - 1] + b[n / 2]) / 2) : null; };
const pct = (x) => (x == null ? null : Math.round(x * 1000) / 10);
const rep = { 사례: results.length, 오류: results.filter((r) => r.err).length, 채점대상: R.length, 허용요청: allowed, 차단요청: blocked, 차단종류: blockedKinds };
const W = R.filter((r) => r.wbPrice > 0);
const ew = W.map((r) => r.wbPrice / r.actual - 1);
rep.예상낙찰가 = { n: W.length, 중앙오차: pct(med(ew.map(Math.abs))), 쏠림: pct(med(ew)), '±10%': pct(ew.filter((x) => Math.abs(x) <= 0.1).length / ew.length) };
const stat = (S, label) => {
  const A = S.filter((r) => r.rec > 0); if (!A.length) return { n: 0 };
  const won = A.filter((r) => r.actual <= r.rec);
  const o = { n: A.length, 추천가로낙찰: pct(won.length / A.length), 낙찰가_추천가_중앙: Math.round(med(A.map((r) => r.actual / r.rec)) * 1000) / 1000, 평균_예측낙찰가능성: pct(A.reduce((s, r) => s + (r.p || 0), 0) / A.length) };
  const nets = won.filter((r) => r.net != null).map((r) => r.net); if (nets.length) o.낙찰시_예상순이익_중앙_만원 = Math.round(med(nets));
  return o;
};
rep.추천가_전체 = stat(R);
rep.추천가_후보만 = stat(R.filter((r) => r.go));
rep.후보수 = R.filter((r) => r.go).length;
rep.후보제외사유 = R.reduce((m, r) => { const k = r.go ? '후보' : (r.why || '?'); m[k] = (m[k] || 0) + 1; return m; }, {});
const cal = []; [[0, 0.1], [0.1, 0.25], [0.25, 0.5], [0.5, 1.01]].forEach(([lo, hi]) => { const G = R.filter((r) => r.rec > 0 && r.p != null && r.p >= lo && r.p < hi); if (G.length >= 15) cal.push({ 예측구간: Math.round(lo * 100) + '~' + Math.round(Math.min(hi, 1) * 100) + '%', n: G.length, 예측: pct(G.reduce((s, r) => s + r.p, 0) / G.length), 실제: pct(G.filter((r) => r.actual <= r.rec).length / G.length) }); });
rep.낙찰가능성_구간별 = cal;
rep.시세단계별_추천가 = {}; ['건물3+', '건물1~2+동', '동5+', '동1~4', '시군구'].forEach((l) => { const G = R.filter((r) => r.lvl === l); if (G.length >= 30) rep.시세단계별_추천가[l] = stat(G); });
console.log(JSON.stringify(rep, null, 1));
fs.writeFileSync('villa-score.json', JSON.stringify(rep));
