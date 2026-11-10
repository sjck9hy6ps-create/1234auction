/* 🏘️ 빌라 과거 낙찰 사례 채점 (2026-11-10, 사용자: 과거 낙찰 사례로 테스트해줘 - API 호출·하루 용량에 막히지 않게 장치를 마련해서)
   입력: villa-cases-asof.json(2026-06 이후 낙찰 사례 + 그 당시 시점 종합 시세·하위값·대장 값), villa-winbid-pre.json(2026-06 이전 사례로만 학습한 낙찰가 모델)
   앱의 실제 계산(필요 마진 villaMarginPlan · 예상 낙찰가 villaWinbid · 추천가 villaBidPlan · 이슈 의심 villaIssueFor)을 가상 브라우저에서 그대로 돌려 추천가·예상 낙찰가·낙찰 가능성을 실제 낙찰가와 비교한다.
   🛡️ 한도 보호 장치:
     ① 외부 호출 전면 차단 - 앱이 부르는 모든 /api/*·카카오·네이버·공공데이터 요청은 가상 브라우저에서 막고 빈 응답을 줌(실제 서버·외부 API로 나가지 않음). 필요한 값(내 자산 세금 설정)만 Node가 한 번 받아 넣음
     ② 호출 상한 - 허용한 요청 수가 MAX_NET_CALLS(기본 40)를 넘으면 즉시 중단 / 차단된 요청 수도 기록
     ③ 시간 상한 TIME_BUDGET_MIN(기본 40분) / 사례를 BATCH 단위로 처리하고 진행 상황을 파일에 저장(중단돼도 이어서 가능, RESUME=1)
     ④ 시작 전 서버 상태 확인(느리면 중단) - 이 도구는 서버를 새로 읽지 않음(입력은 파일)
   출력: villa-score.json, villa-score-rows.json */
import { chromium } from 'playwright';
import fs from 'fs';

const SITE = process.env.SITE_URL || 'https://1234auction.vercel.app';
const CASES = process.env.CASES || 'villa-cases-asof.json';
const PRE = process.env.PRE_MODEL || 'villa-winbid-pre.json';
const MAX_NET = parseInt(process.env.MAX_NET_CALLS || '40', 10);
const BUDGET_MS = parseInt(process.env.TIME_BUDGET_MIN || '40', 10) * 60000;
const BATCH = parseInt(process.env.BATCH || '150', 10);
const T0 = Date.now();

// ④ 서버 상태 확인
{
  const t = Date.now();
  const ok = await fetch(SITE + '/api/data-coverage', { signal: AbortSignal.timeout(20000) }).then((r) => r.status === 200).catch(() => false);
  const ms = Date.now() - t;
  console.log(`서버 확인 ${ok ? '정상' : '오류'} ${ms}ms`);
  if (!ok || ms > 4000) { console.log('서버가 느리거나 오류라 돌리지 않아요'); process.exit(1); }
}
const cases = JSON.parse(fs.readFileSync(CASES, 'utf8')), pre = JSON.parse(fs.readFileSync(PRE, 'utf8'));
// 필요한 외부 값 1건: 내 자산(세금 계산용 주택 수·소득 설정) - 한 번만 받음(Redis 읽기 1회)
const assets = await fetch(SITE + '/api/auction?kind=myAssets', { signal: AbortSignal.timeout(30000) }).then((r) => r.json()).catch(() => []);
console.log('내 자산 항목', Array.isArray(assets) ? assets.length : '?', '(세금 계산용, 1회 호출)');

let allowed = 0, blocked = 0; const blockedKinds = {};
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1200, height: 800 }, timezoneId: 'Asia/Seoul', locale: 'ko-KR' });
const page = await ctx.newPage();
page.on('pageerror', (e) => { const m = String(e).slice(0, 120); if (!/kakao|naver|Script error/.test(m)) console.log('페이지 오류:', m); });
await ctx.route('**/*', (route) => {
  const req = route.request(), u = new URL(req.url()), rt = req.resourceType();
  const same = u.origin === new URL(SITE).origin;
  if (same && (rt === 'document' || (rt === 'script') || rt === 'stylesheet' || rt === 'image' || rt === 'font' || rt === 'manifest')) { allowed++; if (allowed > MAX_NET) { console.log('🛑 허용 요청 상한 초과 - 중단'); browser.close().catch(() => {}); process.exit(2); } return route.continue(); }
  if (same && /\/(villa-winbid|winbid-model|apt-stack|liquidity-curve)\.json$/.test(u.pathname)) return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  // 그 밖의 모든 요청(/api/*·외부 사이트)은 막고 빈 응답
  blocked++; const k = (same ? '내 서버 ' : '') + u.host + (same ? u.pathname.split('/').slice(0, 3).join('/') : ''); blockedKinds[k] = (blockedKinds[k] || 0) + 1;
  if (same && u.pathname.startsWith('/api/')) return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
  return route.abort();
});
await page.goto(SITE, { waitUntil: 'domcontentloaded', timeout: 120000 });
await page.waitForFunction(() => typeof villaMarginPlan === 'function' && typeof villaWinbid === 'function' && typeof villaBidPlan === 'function' && typeof solveAuctionBidFromRecord === 'function' && typeof myAssets !== 'undefined', null, { timeout: 120000 });
await page.waitForTimeout(3000);
// 내 자산·낙찰가 모델 주입(사전 학습본)
await page.evaluate(([as, model]) => {
  myAssets = { loaded: true, items: (as || []).filter((x) => x && x.id !== 'profile'), profile: ((as || []).filter((x) => x && x.id === 'profile')[0]) || null };
  villaWinModel = model;
}, [assets, pre]);
console.log('앱 함수 준비. 허용 요청', allowed, '/ 차단 요청', blocked);

const results = [];
for (let i = 0; i < cases.length; i += BATCH) {
  if (Date.now() - T0 > BUDGET_MS) { console.log('⏱ 시간 상한 도달 - 여기까지 채점'); break; }
  const chunk = cases.slice(i, i + BATCH);
  const out = await page.evaluate((cs) => cs.map((c) => {
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
      else if (c.nRad != null && c.nRad <= 2) why = '반경 거래 적음';
      else if (!isNaN(fl) && fl <= 0) why = '지하';
      else if (pe.p < VILLA_VISIT_MIN_P) why = '낙찰 가능성 낮음';
      return { id: c.id, sale: c.sale, actual: c.actual, minbid: c.minbid, est: ve.est, lvl: c.lvl, sido: c.sido, wbPrice: wb ? wb.price : null, margin: mp ? mp.margin : null, mpBid: mp ? mp.bid : null, rec: pe ? pe.bid : null, p: pe ? pe.p : null, net: pe ? pe.net : null, go: !why, why: why, bidders: c.bidders };
    } catch (e) { return { id: c.id, err: String(e.message || e).slice(0, 120) }; }
  }), chunk);
  results.push(...out);
  fs.writeFileSync('villa-score-progress.json', JSON.stringify({ done: results.length, of: cases.length }));
  console.log(`처리 ${results.length}/${cases.length} (허용 ${allowed} 차단 ${blocked})`);
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
fs.writeFileSync('villa-score-rows.json', JSON.stringify(results));
