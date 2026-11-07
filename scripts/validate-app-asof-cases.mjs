/* 아파트 낙찰사례 종단 재계산(2026-11-07) - 사례마다 낙찰일 35일 전 자료로 앱 계산(종합 평가 보정 포함)을 돌려 rows.json로 저장. 낙찰가 모델을 종합 예상매도가 기준으로 다시 학습·채점하는 데 씀. */
import { chromium } from 'playwright';
import fs from 'fs';
const SITE = process.env.SITE_URL || 'https://1234auction.vercel.app';
const PREFIXES = (process.env.LAWD_PREFIX || '11').split(',');
const FROM = process.env.SALE_FROM || '2025-02-15';
const OUT = process.env.OUT_FILE || 'rows.json';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, timezoneId: 'Asia/Seoul', locale: 'ko-KR' });
page.on('pageerror', (e) => console.log('페이지 오류:', String(e).slice(0, 160)));
await page.goto(SITE, { waitUntil: 'load' });
await page.waitForFunction(() => typeof auctionList !== 'undefined' && auctionList.length > 100 && typeof bidCaseList !== 'undefined' && bidCaseList.length > 1000, null, { timeout: 180000 });
await page.waitForTimeout(5000);
await page.addScriptTag({ path: 'scripts/lib/asof-harness-cases.js' });
await page.evaluate(() => { try { loadSaleRuleParams(); } catch (e) {} });
await page.waitForTimeout(4000);
const plan = await page.evaluate(([from, pf]) => {
  const cs = bidCaseList.filter((c) => /아파트/.test(c.propertyType || '') && c.saleDate >= from && c.finalBidPrice > 0 && c.minBidPrice > 0 && c.areaM2 > 0);
  const by = __vc.assign(cs), out = {};
  Object.keys(by).forEach((l) => { if (pf.some((p) => l.startsWith(p))) out[l] = by[l]; });
  return { total: cs.length, byLawd: out };
}, [FROM, PREFIXES]);
console.log('대상 사례', plan.total, '지역', Object.keys(plan.byLawd).length);
const rows = [], failed = [];
for (const l of Object.keys(plan.byLawd).sort()) {
  try {
    const r = await page.evaluate(([lawd, ids]) => { const set = new Set(ids); return __vc.processCases(lawd, bidCaseList.filter((c) => set.has(c.id)), 35); }, [l, plan.byLawd[l]]);
    r.forEach((x) => rows.push(x));
  } catch (e) { failed.push(l); console.log('❌', l, String(e.message || e).slice(0, 140)); }
}
await browser.close().catch(() => {});
fs.writeFileSync(OUT, JSON.stringify(rows));
console.log('rows', rows.length, '오류 행', rows.filter((r) => r.err).length, '보정 적용', rows.filter((r) => r.stk).length, '실패 지역', failed.length);
if (!rows.length) process.exit(0);
