/* 연산자이(부산 연제구, 사건 2024-213) 예상 낙찰가 재현 시험(2026-11-11) - 같은 사건·같은 시점(입찰 30일 전) 자료·같은 서버 모델로, 앱 코드 버전만 바꿔 계산해 어느 변경이 값을 바꿨는지 가림.
   버전마다 public/index.html을 git에서 꺼내 로컬 서버로 띄우고(API·정적 파일은 실서버로 중계), 현재 하네스(asof-harness-cases.js)로 한 사건만 계산. 측정 전용. */
import { chromium } from 'playwright';
import http from 'http';
import fs from 'fs';
import { execSync } from 'child_process';
const SITE = 'https://1234auction.vercel.app';
const COMMITS = (process.env.COMMITS || 'HEAD').split(',');
const CASE_NO = process.env.CASE_NO || '2024-213', SALE = process.env.SALE || '2026-11-06';
const DAYS = (process.env.DAYS || '30').split(',').map(Number);
let harness = fs.readFileSync('scripts/lib/asof-harness-cases.js', 'utf8');
harness = harness.replace('const w = row && row.winbid;', 'const w = row && row.winbid; try { window.__lastRow = row; } catch (e) {}');
const out = [];
for (const commit of COMMITS) {
  const html = commit === 'HEAD' ? fs.readFileSync('public/index.html') : execSync(`git show ${commit}:public/index.html`, { maxBuffer: 1 << 30 });
  const server = http.createServer(async (req, res) => {
    try {
      const u = req.url || '/';
      if (u === '/' || u.startsWith('/?') || u === '/index.html') { res.setHeader('content-type', 'text/html; charset=utf-8'); res.end(html); return; }
      const body = ['GET', 'HEAD'].includes(req.method) ? undefined : await new Promise((r) => { const c = []; req.on('data', (d) => c.push(d)); req.on('end', () => r(Buffer.concat(c))); });
      const h = {}; ['content-type', 'accept', 'authorization'].forEach((k) => { if (req.headers[k]) h[k] = req.headers[k]; });
      const r = await fetch(SITE + u, { method: req.method, headers: h, body });
      const buf = Buffer.from(await r.arrayBuffer());
      r.headers.forEach((v, k) => { if (!['content-encoding', 'content-length', 'transfer-encoding', 'connection'].includes(k)) res.setHeader(k, v); });
      res.statusCode = r.status; res.end(buf);
    } catch (e) { res.statusCode = 502; res.end(String(e)); }
  }).listen(0);
  const port = server.address().port;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, timezoneId: 'Asia/Seoul', locale: 'ko-KR' });
  page.on('pageerror', (e) => console.log(commit, '페이지 오류:', String(e).slice(0, 140)));
  try {
    await page.goto(`http://localhost:${port}/`, { waitUntil: 'load' });
    await page.waitForFunction(() => typeof auctionList !== 'undefined' && auctionList.length > 100 && typeof bidCaseList !== 'undefined' && bidCaseList.length > 1000, null, { timeout: 240000 });
    await page.waitForTimeout(5000);
    await page.evaluate(() => { try { loadSaleRuleParams(); } catch (e) {} try { loadWinbidModel(); } catch (e) {} });
    try { await page.waitForFunction(() => typeof winbidModel !== 'undefined' && !!winbidModel && !!winbidModel.factors, null, { timeout: 150000 }); } catch (e) { console.log(commit, '최신 낙찰가 모델 대기 시간 초과'); }
    await page.waitForTimeout(4000);
    await page.addScriptTag({ content: harness });
    const info = await page.evaluate(([cn, sale]) => {
      const c = bidCaseList.find((x) => String(x.caseNo).replace(/\s/g, '') === cn && x.saleDate === sale);
      if (!c) return { err: 'case not found' };
      const by = __vc.assign([c]); const lawd = Object.keys(by)[0];
      return { id: c.id, lawd, model: winbidModel ? { gen: winbidModel.generatedAt, factors: winbidModel.factors } : null };
    }, [CASE_NO, SALE]);
    console.log(commit, JSON.stringify(info));
    if (info.id) {
      for (const dBefore of DAYS) {
        const r = await page.evaluate(async ([lawd, id, d]) => {
          const rows = await __vc.processCases(lawd, bidCaseList.filter((x) => x.id === id), d); const rw = window.__lastRow, w = rw && rw.winbid;
          return { rows, dbg: rw ? { sale: rw.sale, saleStack: !!rw.saleStack, minBid: rw.minBid, fails: rw.fails, recBid: rw.recBid, est: w && w.est, pred: w && w.pred, price: w && w.price, compShift: w && w.compShift, corrPct: w && w.corrPct, comp: w && w.comp, flowC: w && w.flowC, flowUp: w && w.flowUp } : null };
        }, [info.lawd, info.id, dBefore]);
        out.push({ commit, daysBefore: dBefore, row: r.rows[0], dbg: r.dbg }); console.log(commit, dBefore, JSON.stringify(r.dbg), JSON.stringify(r.rows[0] && { wbP: r.rows[0].wbP, wbEst: r.rows[0].wbEst, rec: r.rows[0].rec, stk: r.rows[0].stk, err: r.rows[0].err }));
      }
    }
  } catch (e) { console.log(commit, '실패:', String(e.message || e).slice(0, 200)); out.push({ commit, err: String(e.message || e).slice(0, 200) }); }
  await browser.close().catch(() => {}); server.close();
}
fs.writeFileSync('replay-case.json', JSON.stringify(out, null, 1));
