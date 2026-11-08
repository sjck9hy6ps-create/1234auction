/* 호가 → 실거래 짝짓기 채점(2026-11-08): 붙여넣은 호가 기록(listingHistory: 그때의 최저·25%·중앙·비슷한 층 최저 호가)과 그 뒤 같은 단지·평형의 첫 실거래·60일 중위를 비교해
   '호가 대비 실제 거래가' 비율을 잼 - 호가 상한의 흥정률(지금 3%)·가장 싼 2건 평균 규칙을 실측으로 바꾸기 위한 자료. 실거래 신고는 지연되므로 시간이 지날수록 짝이 늘어남. */
import { chromium } from 'playwright';
import fs from 'fs';
const SITE = process.env.SITE_URL || 'https://1234auction.vercel.app';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, timezoneId: 'Asia/Seoul', locale: 'ko-KR' });
page.on('pageerror', (e) => console.log('페이지 오류:', String(e).slice(0, 160)));
await page.goto(SITE, { waitUntil: 'load' });
await page.waitForFunction(() => typeof auctionList !== 'undefined' && auctionList.length > 100, null, { timeout: 180000 });
await page.waitForTimeout(4000);
const plan = await page.evaluate(() => {
  const by = {}; let snaps = 0;
  auctionList.forEach((a) => { if (a.propType === 'apt' && a.bCode && Array.isArray(a.listingHistory) && a.listingHistory.length) { (by[String(a.bCode).slice(0, 5)] = by[String(a.bCode).slice(0, 5)] || []).push(a.id); snaps += a.listingHistory.length; } });
  return { by, snaps, n: Object.values(by).reduce((s, x) => s + x.length, 0) };
});
console.log('호가 기록 있는 아파트 물건', plan.n, '기록(스냅샷)', plan.snaps, '지역', Object.keys(plan.by).length);
const pairs = [];
for (const l of Object.keys(plan.by).sort()) {
  try {
    const r = await page.evaluate(async ([lawd, ids]) => {
      const wasLoaded = !!dataCache[lawd];
      if (!wasLoaded) { const d = await fetchHouseDataCached(lawd); if (!d || d.error || !Array.isArray(d.apt)) return []; await ingestRegionHouseData(d, '', lawd); }
      const out = [], region = allAptList.filter((ap) => ap.lawdCd === lawd && (ap.buildingType || 'apt') === 'apt');
      const set = new Set(ids.map(String));
      auctionList.filter((a) => set.has(String(a.id))).forEach((a) => {
        const ap = region.find((x) => x.latest && x.latest.dong === a.dong && String(x.latest.bunji) === String(a.bunji)); if (!ap) return;
        const area = (parseFloat(a.pyung) || 0) * 3.305785; if (!area) return;
        const tr = (ap.trades || []).filter((t) => Math.abs((+t.area || 0) - area) <= 3).map((t) => ({ ms: new Date(t.year, t.month - 1, t.day).getTime(), p: parseInt(String(t.amount).replace(/,/g, ''), 10), fl: parseInt(t.floor, 10) || null })).filter((t) => t.p > 0).sort((x, y) => x.ms - y.ms);
        a.listingHistory.forEach((h) => {
          if (!h || !h.at || !(h.med > 0)) return;
          const t0 = new Date(h.at + 'T00:00:00+09:00').getTime();
          const after = tr.filter((t) => t.ms > t0 && t.ms <= t0 + 150 * 864e5); if (!after.length) return;
          const w60 = after.filter((t) => t.ms <= t0 + 60 * 864e5).map((t) => t.p).sort((x, y) => x - y);
          out.push({ id: a.id, at: h.at, n: h.n, min: h.min, q25: h.q25, med: h.med, simMin: h.simMin || null, first: after[0].p, firstDays: Math.round((after[0].ms - t0) / 864e5), firstFl: after[0].fl, tfloor: parseInt(a.floor, 10) || null, med60: w60.length ? w60[Math.floor(w60.length / 2)] : null, n60: w60.length });
        });
      });
      if (!wasLoaded) { delete dataCache[lawd]; delete rentCacheByLawd[lawd]; try { mergedLawdCds.delete(lawd); } catch (e) {} try { rebuildMergedLists(); } catch (e) {} }
      return out;
    }, [l, plan.by[l]]);
    r.forEach((x) => pairs.push(x));
  } catch (e) { console.log('❌', l, String(e.message || e).slice(0, 120)); }
}
await browser.close().catch(() => {});
const med = (a) => { const b = a.slice().sort((x, y) => x - y); const n = b.length; return n ? (n % 2 ? b[(n - 1) / 2] : (b[n / 2 - 1] + b[n / 2]) / 2) : null; };
const stat = (arr) => ({ n: arr.length, 중앙: arr.length ? +(med(arr) * 100).toFixed(1) : null, 하위25: arr.length ? +(arr.slice().sort((x, y) => x - y)[Math.floor(arr.length * 0.25)] * 100).toFixed(1) : null, 상위25: arr.length ? +(arr.slice().sort((x, y) => x - y)[Math.floor(arr.length * 0.75)] * 100).toFixed(1) : null });
const rep = { 짝: pairs.length, 물건: new Set(pairs.map((p) => p.id)).size };
rep['첫거래÷최저호가 -1'] = stat(pairs.filter((p) => p.min > 0).map((p) => p.first / p.min - 1));
rep['첫거래÷25%호가 -1'] = stat(pairs.filter((p) => p.q25 > 0).map((p) => p.first / p.q25 - 1));
rep['첫거래÷중앙호가 -1'] = stat(pairs.filter((p) => p.med > 0).map((p) => p.first / p.med - 1));
rep['첫거래÷비슷한층최저 -1'] = stat(pairs.filter((p) => p.simMin > 0).map((p) => p.first / p.simMin - 1));
rep['60일중위÷최저호가 -1'] = stat(pairs.filter((p) => p.min > 0 && p.med60).map((p) => p.med60 / p.min - 1));
console.log('📊 호가→실거래:', JSON.stringify(rep, null, 1));
fs.writeFileSync('listing-gap.json', JSON.stringify({ at: new Date().toISOString(), rep, pairs }));
