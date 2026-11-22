/* 계산 자동 검증 (2026-11-22, 전체 점검 제안 1번)
   앱(public/index.html)을 가상 브라우저(Chromium)로 열어, 돈이 나오는 계산이 법정 기준·직접 계산·이전에 확인한 값과 맞는지 점검합니다.
   - 취득세·소득세·재산세·종부세·중개수수료·등기비·인지세 표(독립 계산 또는 확인된 값과 대조)
   - 장부 계산 항등식(총비용·세전·세후), 이자(일시상환·원리금균등·마이너스 대출), 건물분 부가세, 건강보험 소득월액
   - 같은 해 손익 통산·이월결손금·매도 후 고정(연봉이 바뀌어도 값이 그대로)
   - 입찰 추천가를 구하는 식 ↔ 그 가격의 순이익 일치
   - 무작위 장부 600건에서 오류·NaN 없음, 세율 파일(tax-rates.json) 형식·값 범위
   - 앱을 여는 동안 스크립트 오류 없음
   사용: node tests/calc-regression.mjs   (CI에서는 GitHub Actions가 자동 실행. 내 컴퓨터에선 CHROME_PATH로 크롬 경로를 줄 수 있음)
   실패하면 종료 코드 1 → GitHub Actions가 빨간 표시와 메일로 알려 줌 */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public');
let pw;
try { pw = await import('playwright'); } catch (e) { pw = await import('playwright-core'); }
const { chromium } = pw.default && pw.default.chromium ? pw.default : pw;

const MIME = { '.html': 'text/html; charset=utf-8', '.json': 'application/json; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css' };
const server = http.createServer((req, res) => {
  const u = decodeURIComponent((req.url || '/').split('?')[0]);
  const f = path.join(ROOT, u === '/' ? 'index.html' : u);
  if (!f.startsWith(ROOT) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); res.end('not found'); return; }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' }); res.end(fs.readFileSync(f));
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {});
const page = await browser.newPage({ viewport: { width: 1200, height: 800 }, timezoneId: 'Asia/Seoul', locale: 'ko-KR' });
const pageErrors = [];
page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 300)));
// 외부 API·지도 스크립트는 막아서(서버 없이도 돌도록) 계산 함수만 시험
await page.route((url) => !String(url).startsWith(base), (route) => route.abort());
await page.route((url) => String(url).startsWith(base + '/api/'), (route) => route.fulfill({ status: 404, body: '{}' }));
await page.goto(base + '/index.html', { waitUntil: 'domcontentloaded' });
await page.waitForFunction(() => typeof window.ledgerCalc === 'function' && typeof window.calcAcquisitionTaxDetailed === 'function', null, { timeout: 60000 });
await page.waitForTimeout(1500);

const results = await page.evaluate(async () => {
  const R = [];
  const ok = (name, pass, detail) => R.push({ name, pass: !!pass, detail: pass ? '' : String(detail == null ? '' : detail).slice(0, 300) });
  const near = (a, b, tol) => Math.abs(a - b) <= (tol == null ? 0.5 : tol);
  const J = (x) => JSON.stringify(x);

  // 세율 파일을 읽지 않은 코드 기본값 기준으로 시험(월간 갱신이 값을 바꿔도 "법정 기준 표"는 별도로 관리)
  // ── 1. 취득세 (비조정·조정 × 주택 수 × 면적, 법정 세율표와 대조) ──
  const acq = (bid, py, rank, adj, cheap) => calcAcquisitionTaxDetailed(bid, 'apt', py, rank, adj, !!cheap) / bid * 100;
  const A = [
    // [입찰가(만원), 평, 주택수, 조정, 기대 합계세율%]  (85㎡ 이하=25.7평 미만 / 초과=30평)
    [10000, 20, 1, false, 1.1], [60000, 20, 1, false, 1.1], [75000, 30, 1, false, 2.4], [90000, 30, 1, false, 3.5], [120000, 30, 1, false, 3.5],
    [10000, 20, 2, false, 1.1], [10000, 20, 3, false, 8.4], [10000, 20, 4, false, 12.4], [10000, 30, 3, false, 9.0],
    [10000, 20, 2, true, 8.4], [10000, 20, 3, true, 12.4], [10000, 30, 2, true, 9.0], [10000, 30, 3, true, 13.4]
  ];
  A.forEach(([b, py, rk, adj, exp]) => { const v = acq(b, py, rk, adj); ok('취득세 ' + b + '만 ' + py + '평 ' + rk + '주택' + (adj ? ' 조정' : ''), near(v, exp, 0.06), v); });
  ok('취득세 공시가 저가 배제(중과 배제)', near(acq(8000, 20, 3, true, true), 1.1, 0.06), acq(8000, 20, 3, true, true));
  ok('취득세 오피스텔 4.6%', near(calcAcquisitionTaxDetailed(19800, 'officetel', 25, 1, false, false), 19800 * 0.046, 0.6), calcAcquisitionTaxDetailed(19800, 'officetel', 25, 1, false, false));

  // ── 2. 종합소득세: 독립 누진 계산 ──
  const SL = [[1400, .06], [5000, .15], [8800, .24], [15000, .35], [30000, .38], [50000, .40], [100000, .42], [Infinity, .45]];
  const indep = (x) => { let t = 0, prev = 0; for (const [m, r] of SL) { if (x > m) t += (m - prev) * r; else { t += (x - prev) * r; break; } prev = m; } return t; };
  [500, 1400, 3000, 5000, 7000, 8800, 12000, 15000, 25000, 30000, 45000, 50000, 80000, 100000, 150000].forEach((x) => {
    const b = lookupIncomeTaxBracket(x), v = x * b.rate - b.dedManwon; ok('소득세 과세표준 ' + x + '만', near(v, indep(x), 1.5), v + ' vs ' + indep(x));
  });
  { const br = TAX_CONFIG.incomeTax.brackets; let c = true; for (let i = 1; i < br.length; i++) { const p = br[i - 1], m = br[i].minManwon; if (Math.abs(m * p.rate - p.dedManwon - (m * br[i].rate - br[i].dedManwon)) > 1.5) c = false; } ok('소득세 누진공제 구간 연속', c); }

  // ── 3. 재산세·종부세·중개·등기·이자·인지 (확인된 값 고정) ──
  [[3000, 3], [6000, 7], [9000, 10], [12000, 13], [20000, 24]].forEach(([m, e]) => ok('재산세 공시가 ' + m + '만 1주택', calcPropertyTax(m * 10000, 1, true, 12, 1) === e, calcPropertyTax(m * 10000, 1, true, 12, 1)));
  ok('재산세 6/1 안 걸리면 0', calcPropertyTax(90000000, 1, false, 3, 0) === 0);
  ok('재산세 6/1 두 번이면 2배', calcPropertyTax(90000000, 1, true, 12, 2) === 2 * calcPropertyTax(90000000, 1, true, 12, 1));
  [[50000, 50000, 1, 0], [100000, 100000, 1, 0], [100000, 100000, 2, 36], [150000, 100000, 1, 108], [150000, 100000, 2, 230], [300000, 200000, 1, 1008]].forEach(([t, o, rk, e]) => ok('종부세 합계 ' + t + '만 주택 ' + rk, calcCompTax(t, o * 10000, rk, true, 12, 1) === e, calcCompTax(t, o * 10000, rk, true, 12, 1)));
  [[3000, 18], [6000, 30], [9000, 45], [15000, 75], [20000, 80], [40000, 160]].forEach(([m, e]) => ok('중개수수료 ' + m + '만', calcAgentFee(m, 'apt') === e, calcAgentFee(m, 'apt')));
  ok('등기비 0.5%', calcRegistryFee(10000) === 50 && calcRegistryFee(5000) === 25);
  ok('대출이자 1억 5% 3·12개월', calcLoanInterest(10000, 5, 3) === 125 && calcLoanInterest(10000, 5, 12) === 500);
  [[500, 0], [1000, 0], [1001, 1], [3000, 1], [3001, 2], [5000, 2], [5001, 3.5], [10000, 3.5], [10001, 7.5], [100000, 7.5], [100001, 17.5]].forEach(([m, e]) => ok('인지세(매도인 몫) ' + m + '만', calcStampDuty(m) === e, calcStampDuty(m)));
  ok('건물분 부가세 10/110', near(vatOnSale(24500, 0.65), 24500 * 0.65 * 10 / 110, 1));

  // ── 3-2. 권리분석 소액임차인 지역·시기 표 (주임법 시행령 제10조·수도권정비계획법 시행령 별표 1) ──
  [['서울특별시 강남구 역삼동', 0], ['인천광역시 남동구 구월동', 1], ['인천광역시 서구 당하동', 2], ['인천광역시 연수구 송도동', 2], ['인천광역시 강화군 길상면', 3], ['경기도 남양주시 평내동', 1], ['경기도 남양주시 별내동', 3], ['경기도 용인시 수지구 죽전동', 1], ['경기도 안산시 단원구 고잔동', 2], ['부산광역시 해운대구 우동', 2], ['부산 기장군 정관읍', 3], ['대구광역시 달성군 옥포읍', 3], ['전남광주통합특별시 서구 풍암동', 2], ['전남광주통합특별시 나주시 빛가람동', 3], ['충청남도 천안시 서북구 두정동', 3]].forEach(([ad, e]) => ok('소액임차인 지역 구간 ' + ad, rightsMinorTier(ad) === e, rightsMinorTier(ad)));
  [['2024-01-01', '서울', 16500, 5500], ['2022-01-01', '서울', 15000, 5000], ['2019-01-01', '서울', 11000, 3700], ['2017-01-01', '서울', 10000, 3400], ['2015-01-01', '서울', 9500, 3200], ['2012-01-01', '서울', 7500, 2500], ['2009-01-01', '서울', 6000, 2000]].forEach(([d, ad, lim, pay]) => { const m = rightsMinorLimit(d, ad); ok('소액임차인 시기별 표 ' + d, m && m.limit === lim * 10000 && m.pay === pay * 10000, JSON.stringify(m)); });
  ok('소액임차인 2008년 이전은 표 없음', rightsMinorLimit('2007-01-01', '서울') === null);
  { const mkT = (n, dep) => ({ name: n, deposit: dep * 10000, moveIn: '2019-01-01', fixed: '2019-01-02', distDate: '2025-01-05', tankStanding: false });
    const rt = { baseDate: '2022-06-01', registry: [{ seq: 1, type: '근저당', date: '2022-06-01', holder: '은행', amount: 90000000, extinguished: true }, { seq: 2, type: '임의경매', date: '2025-01-01', holder: '은행' }], tenants: [mkT('가', 5000), mkT('나', 5000), mkT('다', 5000)] };
    const w = rightsWaterfall(rt, 6000 * 10000, { addr: '서울특별시 노원구 상계동', execWon: 0 }), paid = w.tenants.map((t) => t.minorPaid || 0); const tot = paid.reduce((a, b) => a + b, 0);
    ok('소액임차인 3명 합계가 낙찰가 1/2(3000만) 넘으면 같은 비율로 안분', Math.abs(tot - 3000 * 10000) <= 3 && Math.abs(paid[0] - paid[1]) <= 1 && Math.abs(paid[1] - paid[2]) <= 1, JSON.stringify(paid)); }

  // ── 4. 장부 계산 항등식·이자·부가세 ──
  const base = { id: 't1', name: '시험', type: 'house', win: { date: '2025-01-01', price: 20000 }, sale: { date: '2026-01-01', price: 30000 }, items: [], loans: [{}, {}], taxes: [{ kind: '종합소득세(증가분)', amount: 100 }], vatMode: 'off', rev: { draws: [] } };
  const mk = (o) => Object.assign(JSON.parse(J(base)), o);
  { const c = ledgerCalc(mk({ items: [{ id: 'a', cat: '취득', sub: '취득세', amount: 900 }], loans: [{ amount: 15000, rate: 5, type: 'bullet', start: '2025-01-01', end: '2026-01-01' }, {}] }));
    ok('장부 일시상환 이자 15000×5%×365/365=750', near(c.interest, 750, 0.5), c.interest);
    ok('장부 총비용 = 낙찰가+비용+이자', near(c.totalCost, 20000 + 900 + 750, 0.5), c.totalCost);
    ok('장부 세전 = 매도가−총비용', near(c.pre, 30000 - 21650, 0.5), c.pre);
    ok('장부 세후 = 세전−입력한 세금', near(c.net, c.pre - 100, 0.01), c.net); }
  { const c = ledgerCalc(mk({ loans: [{ amount: 2000, rate: 8, type: 'amort', term: 36, start: '2025-01-01', end: '2026-01-01' }, {}] }));
    const r = 0.08 / 12, n = 36, P = 2000 * r / (1 - Math.pow(1 + r, -n)); let bal = 2000, t = 0; for (let i = 0; i < 12; i++) { const it = bal * r; t += it; bal -= (P - it); }
    ok('원리금균등 36개월 중 12개월 이자', near(c.interest, t, 1), c.interest + ' vs ' + t); }
  { const c = ledgerCalc(mk({ rev: { rate: '6', draws: [{ id: 'd1', date: '2026-01-03', repay: '2026-01-10', amount: 2000 }, { id: 'd2', date: '2025-06-01', amount: 3000 }] } }));
    const e1 = 2000 * 0.06 * 7 / 365, e2 = 3000 * 0.06 * 214 / 365; ok('마이너스 대출 인출별 일할 이자(상환일 있음·없음=매도일)', near(c.interest, e1 + e2, 0.1), c.interest + ' vs ' + (e1 + e2)); }
  { const c = ledgerCalc(mk({ vatMode: 'on', vatRatio: '65', taxes: [{ kind: '종합소득세(증가분)', amount: 0 }] }));
    const v = 30000 * 0.65 * 10 / 110; ok('건물분 부가세를 매출에서 뺌', near(c.vatPay, v, 0.01) && near(c.pre, 30000 - v - 20000, 0.01), c.vatPay + '/' + c.pre); }
  { const c = ledgerCalc(mk({ vatMode: 'on', vatRatio: '65', vatDeduct: 1, items: [{ id: 'x', cat: '수리', sub: '도배·장판', amount: 1000, inv: 1 }] }));
    ok('계산서 부가세는 환급 시 비용 제외(순이익 영향 없음)', near(c.itemsTotal, 1000, 0.01) && near(c.vatTotal, 100, 0.01), c.itemsTotal + '/' + c.vatTotal); }
  { const c = ledgerCalc(mk({ vatMode: 'off', vatDeduct: 0, items: [{ id: 'x', cat: '수리', sub: '도배·장판', amount: 1000, inv: 1 }] }));
    ok('계산서 부가세는 환급 안 받으면 비용에 포함', near(c.itemsTotal, 1100, 0.01), c.itemsTotal); }

  // ── 5. 세금(소득세·건보료)·결손금 통산·이월결손금·매도 후 고정 ──
  myAssets.loaded = true; myAssets.items = []; myAssets.profile = { id: 'profile', isDealer: true, salary: 6500, otherIncome: 0, extraBizIncome: 0 };
  ledger.loaded = true;
  const w = maWorkIncome(myAssets.profile);
  ok('연봉 6500 → 근로소득공제 1300·소득금액 5200·과세표준 4530', w.ded === 1300 && w.gross === 5200 && w.base === 4530, J(w));
  const deal = (id, date, sale, win) => ({ id, name: id, type: 'house', win: { date: '2026-01-01', price: win }, sale: { date, price: sale }, items: [], loans: [{}, {}], taxes: [], vatMode: 'off', rev: { draws: [] } });
  { const a1 = deal('A1', '2026-03-10', 23000, 20000), a2 = deal('A2', '2026-09-10', 18000, 20000); ledger.items = [a1, a2];
    const s = ledgerCalc(a1).taxSum + ledgerCalc(a2).taxSum, f = (x) => { const b = lookupIncomeTaxBracket(x); return x * b.rate - b.dedManwon; }, agg = (f(4530 + 1000) - f(4530)) * 1.1;
    ok('같은 해 이익 3000·손실 2000 → 건별 세금 합 = 합산(1000) 세금', near(s, agg, 3), s + ' vs ' + agg);
    ledger.items = [deal('B1', '2026-03-10', 18000, 20000), deal('B2', '2026-09-10', 23000, 20000)];
    const s2 = ledgerCalc(ledger.items[0]).taxSum + ledgerCalc(ledger.items[1]).taxSum; ok('손익 순서를 바꿔도 한 해 합계 세금 같음', near(s2, agg, 3), s2 + ' vs ' + agg); }
  { const c1 = deal('C1', '2026-05-10', 10000, 20000); ledger.items = [c1];
    const yi = lgYearInfo(2026); ok('올해 큰 손실은 근로소득금액까지 통산하고 남는 4800만을 이월', near(yi.loss, 4800, 0.5) && near(lgCarryIn(2027), 4800, 0.5), J(yi));
    const d1 = deal('D1', '2027-04-10', 24000, 20000); ledger.items = [c1, d1]; const c = ledgerCalc(d1);
    const f = (x) => { const b = lookupIncomeTaxBracket(x); return x * b.rate - b.dedManwon; }, inc = f(3730) - f(0), exp = inc * 1.1 + (4000 - 2000) * 0.0719;
    ok('이월결손금 4800 공제 후 2027년 이익 4000의 세금·건보료', near(c.taxSum, exp, 3), c.taxSum + ' vs ' + exp); }
  { const f1 = deal('F1', '2026-03-10', 23000, 20000); ledger.items = [f1]; lgFreezeIfDue(f1); const t0 = ledgerCalc(f1).taxSum;
    myAssets.profile = Object.assign({}, myAssets.profile, { salary: 12000 }); const t1 = ledgerCalc(f1).taxSum, frozen = ledgerCalc(f1).taxFrozen;
    ok('매도일이 지나 고정된 예상 세금은 연봉을 바꿔도 그대로', frozen && near(t0, t1, 0.001), t0 + '→' + t1);
    f1.items = [{ id: 'z', cat: '수리', sub: '도배·장판', amount: 500 }]; ok('비용을 고치면(이익이 달라지면) 고정이 풀림', !ledgerCalc(f1).taxFrozen);
    myAssets.profile = Object.assign({}, myAssets.profile, { salary: 6500 }); }
  { // 건보료: 보수 외 소득 2,000만 이하면 0, 초과분×7.19%
    ledger.items = [deal('H1', '2026-03-10', 22000, 20000)]; const c = ledgerCalc(ledger.items[0]); const h = (c.taxList.find((t) => /건강/.test(t.kind)) || {}).amount || 0; ok('이익 2000 이하면 건강보험 소득월액 0', h === 0, h);
    ledger.items = [deal('H2', '2026-03-10', 26000, 20000)]; const c2 = ledgerCalc(ledger.items[0]); const h2 = (c2.taxList.find((t) => /건강/.test(t.kind)) || {}).amount || 0; ok('이익 6000 → 초과분 4000×7.19%', near(h2, 4000 * 0.0719, 1), h2); }

  // ── 6. 입찰 추천가 ↔ 그 가격의 순이익 ──
  myAssets.items = []; ledger.items = [];
  { const a = { propType: 'apt', pyung: 25.7, addr: '광주광역시 광산구 월계동 1', appraisal: 12800, minBid: 7168, target: 14333, compTargetMargin: 1000, repair: 800, officialPriceWon: 75700000, bidDate: '2027-02-10', holdAuto: 6 };
    const s = solveAuctionBidFromRecord(a); const n = s && netAtBidFromRecord(Object.assign({}, a, { actualBid: s.bid }));
    ok('추천가를 구하는 식과 순이익 계산 일치(목표마진 1000)', s && n && near(n.net, 1000, 3), J(s) + ' / ' + J(n));
    const s2 = solveAuctionBidFromRecord(Object.assign({}, a, { compTargetMargin: 2000 })); ok('목표마진을 높이면 추천 입찰가는 낮아짐', s && s2 && s2.bid < s.bid, (s && s.bid) + ' vs ' + (s2 && s2.bid)); }

  // ── 7. 무작위 장부 600건: 오류·NaN 없음 ──
  { let seed = 12345; const rnd = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296, pick = (a) => a[Math.floor(rnd() * a.length)], range = (a, b) => a + rnd() * (b - a);
    const dates = ['2024-03-01', '2025-08-19', '2026-01-10', '2026-11-30', '2027-04-02', '2026-12-31', '2027-01-01', '', 'bad'], types = ['house', 'officetel', 'other'];
    let bad = 0, thrown = 0, ex = '';
    for (let i = 0; i < 600; i++) {
      const r = { id: 'fz' + i, type: pick(types), vatMode: pick(['', 'on', 'off']), win: { date: pick(dates), price: pick([0, '', 5000, 19800, 50000, range(1000, 300000)]) }, sale: { date: pick(dates), price: pick([0, '', -5, 10000, 24500, range(1000, 400000)]) }, items: [], taxes: [], vatRatio: pick(['', 65, 0, 150, -3]), vatIn: pick(['', 0, 5000]), vatDeduct: pick([0, 1]), rev: { rate: pick(['', 6, 0]), draws: [{ id: 'q' + i, date: pick(dates), repay: pick(['', pick(dates)]), amount: pick([0, '', 2000, range(0, 9000)]) }] },
        loans: [{ amount: pick([0, '', 17600, range(0, 40000)]), rate: pick([0, '', 5.37, range(0, 15)]), type: pick(['bullet', 'amort', '']), term: pick(['', 0, 36, 120, 'x']), start: pick(dates), end: pick(dates), interestPaid: pick(['', 0, 100]) }, {}] };
      for (let k = 0; k < Math.floor(rnd() * 4); k++) r.items.push({ id: 'i' + k, cat: '수리', sub: 'x', amount: pick([0, '', 50, range(-100, 5000), 'abc']), inv: pick([0, 1]) });
      ledger.items = [r];
      try { const c = ledgerCalc(r); ['winP', 'saleP', 'itemsTotal', 'interest', 'totalCost', 'vatPay', 'taxSum'].forEach((k) => { if (!isFinite(c[k])) { bad++; ex = ex || (k + '=' + c[k]); } }); if (c.pre != null && !isFinite(c.pre)) { bad++; ex = ex || 'pre'; } if (c.net != null && !isFinite(c.net)) { bad++; ex = ex || 'net'; } lgYearInfo(2026); lgFreezeIfDue(JSON.parse(J(r))); } catch (e) { thrown++; ex = ex || String(e).slice(0, 80); }
    }
    ok('무작위 장부 600건: NaN·무한대 없음', bad === 0, bad + ' ' + ex); ok('무작위 장부 600건: 예외 없음', thrown === 0, thrown + ' ' + ex); }
  ledger.items = []; myAssets.items = [];
  return R;
});

// ── 8. 세율 파일 형식·값 범위 + 코드 적용 ──
const rates = JSON.parse(fs.readFileSync(path.join(ROOT, 'tax-rates.json'), 'utf8'));
const fileChecks = [];
const fc = (name, pass, detail) => fileChecks.push({ name, pass: !!pass, detail: pass ? '' : String(detail || '') });
fc('세율 파일: values·ver 있음', rates && rates.values && typeof rates.ver === 'number');
fc('세율 파일: 건강보험 요율 0~20%·기준금액 양수', rates.values && rates.values.health && rates.values.health.rate > 0 && rates.values.health.rate < 0.2 && rates.values.health.thresholdMan > 0, JSON.stringify(rates.values && rates.values.health));
{ const t = rates.values && rates.values.stamp && rates.values.stamp.tiers; let mono = Array.isArray(t) && t.length >= 2; if (mono) for (let i = 1; i < t.length; i++) if (!(t[i].maxManwon > t[i - 1].maxManwon) || t[i].tax < t[i - 1].tax) mono = false; fc('세율 파일: 인지세 구간이 오름차순·세액 비감소', mono, JSON.stringify(t)); }
fc('세율 파일: 매매 소득세 구간 키 존재', rates.values && rates.values.incomeTax && Array.isArray(rates.values.incomeTax.brackets) && rates.values.incomeTax.brackets.length >= 7);
fc('세율 파일: extra 항목 형식(id·label·stage·base·status·금액 규칙)', (rates.extra || []).every((e) => e.id && e.label && ['acq', 'sale', 'profit'].includes(e.stage) && ['bid', 'sale', 'profit'].includes(e.base) && e.status && (e.rate != null || e.fixedMan != null || (e.tiers && e.tiers.length))), JSON.stringify(rates.extra));
fc('세율 파일: schedule 항목에 시행일(from)·status', (rates.schedule || []).every((e) => e.from && e.status));
const apply = await page.evaluate((doc) => { try { const keep = JSON.parse(JSON.stringify(TAX_CONFIG, (k, v) => (v === Infinity ? 1e18 : v))); applyTaxRatesFile(doc); const a = calcAcquisitionTaxDetailed(60000, 'apt', 20, 1, false, false), s = calcStampDuty(24500), h = TAX_CONFIG.health.rate; return { ok: isFinite(a) && a > 0 && isFinite(s) && h > 0, a, s, h }; } catch (e) { return { ok: false, err: String(e) }; } }, rates);
fc('세율 파일을 앱에 적용해도 계산이 정상', apply.ok, JSON.stringify(apply));
results.push(...fileChecks);
results.push({ name: '앱을 여는 동안 스크립트 오류 없음', pass: pageErrors.length === 0, detail: pageErrors.slice(0, 3).join(' | ') });

await browser.close(); server.close();
const failed = results.filter((r) => !r.pass);
console.log(`계산 자동 검증: ${results.length - failed.length}/${results.length} 통과`);
failed.forEach((r) => console.log(`  ✗ ${r.name}${r.detail ? ' — ' + r.detail : ''}`));
if (failed.length) process.exit(1);
console.log('모두 통과');
