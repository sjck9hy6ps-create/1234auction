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
const MMOS = (process.env.MMOS || '').split(',').filter(Boolean);   // 'mmo' 또는 'mmo:1'(1이면 근거 두께별 위험 여유 규칙 끔)   // 최소 순이익 가정(만원) 목록 - 비우면 앱 기본값 한 번만
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
  const browser = await chromium.launch(process.env.CHROME_CHANNEL ? { channel: process.env.CHROME_CHANNEL } : {});
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, timezoneId: 'Asia/Seoul', locale: 'ko-KR' });
  page.on('pageerror', (e) => console.log(commit, '페이지 오류:', String(e).slice(0, 140)));
  page.on('requestfailed', (r) => console.log(commit, '요청 실패:', r.url().slice(0, 120), r.failure() && r.failure().errorText));
  page.on('response', (r) => { if (r.status() >= 400) console.log(commit, '응답', r.status(), r.url().slice(0, 120)); });
  try {
    await page.goto(commit === 'HEAD' && process.env.USE_LIVE === '1' ? SITE : `http://localhost:${port}/`, { waitUntil: 'load' });   // 현재 코드는 실서버 그대로(중계 없이)
    try { await page.waitForFunction(() => typeof auctionList !== 'undefined' && auctionList.length > 100 && typeof bidCaseList !== 'undefined' && bidCaseList.length > 1000, null, { timeout: 240000 }); } catch (e) { console.log(commit, '목록 대기 시간 초과:', await page.evaluate(() => JSON.stringify({ a: typeof auctionList !== 'undefined' ? auctionList.length : null, b: typeof bidCaseList !== 'undefined' ? bidCaseList.length : null }))); throw e; }
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
      for (const dBefore of DAYS) for (const mv of (MMOS.length ? MMOS : [null])) {
        const mmo = mv == null ? null : Number(String(mv).split(':')[0]), norisk = mv != null && String(mv).split(':')[1] === '1';
        const r = await page.evaluate(async ([lawd, id, d, mm, nr]) => {
          window.__mmo = mm == null ? 0 : mm; const __rtr = window.riskTableRate; if (nr) window.riskTableRate = function () { return null; };   // 0이면 앱 기본값, 양수면 그 값을 최소 순이익으로
          const rows = await __vc.processCases(lawd, bidCaseList.filter((x) => x.id === id), d); const rw = window.__lastRow, w = rw && rw.winbid;
          const pk = rw && rw.pick ? { keys: Object.keys(rw.pick), infeasible: !!rw.pick.infeasible, max: rw.pick.max ? rw.pick.max.bid : null, best: rw.pick.best ? rw.pick.best.bid : null, rec: rw.pick.rec ? rw.pick.rec.bid : null } : null;
          const MINM = typeof minMarginOf === 'function' && rw ? minMarginOf(rw) : null;
          window.__mmo = 0; window.riskTableRate = __rtr;
          return { rows, dbg: rw ? { sale: rw.sale, saleStack: !!rw.saleStack, minBid: rw.minBid, fails: rw.fails, recBid: rw.recBid, recAggr: rw.recAggr, minMargin: MINM, evBid: rw.pick && rw.pick.ev ? rw.pick.ev.bid : null, evNet: rw.pick && rw.pick.ev ? rw.pick.ev.net : null, maxBid: rw.pick && rw.pick.max ? rw.pick.max.bid : null, maxNet: rw.pick && rw.pick.max ? rw.pick.max.net : null, p70: rw.pick && rw.pick.p70 ? rw.pick.p70.bid : null, regionCls: rw.regionCls, n6: rw.ownStats ? rw.ownStats.n6 : null, riskRate: (function () { try { const os3 = rw.ownStats; const t = riskTableRate({ cls: rw.regionCls, n6: os3 ? os3.n6 : null, disp6: os3 ? os3.disp6 : null, lastAgeM: os3 ? os3.lastAgeM : null, fb: rw.saleFb || null }); return t && t.rate; } catch (e) { return null; } })(), pick: pk, est: w && w.est, pred: w && w.pred, price: w && w.price, compShift: w && w.compShift, corrPct: w && w.corrPct, comp: w && w.comp, flowC: w && w.flowC, flowUp: w && w.flowUp, probRec: w && w.probRec } : null };
        }, [info.lawd, info.id, dBefore, mmo, norisk]);
        out.push({ commit, daysBefore: dBefore, mmo, norisk, row: r.rows[0], dbg: r.dbg }); console.log(commit, dBefore, 'mmo', mmo, 'norisk', norisk, JSON.stringify(r.dbg), JSON.stringify(r.rows[0] && { wbP: r.rows[0].wbP, wbEst: r.rows[0].wbEst, rec: r.rows[0].rec, stk: r.rows[0].stk, err: r.rows[0].err }));
      }
    }
  } catch (e) { console.log(commit, '실패:', String(e.message || e).slice(0, 200)); out.push({ commit, err: String(e.message || e).slice(0, 200) }); }
  await browser.close().catch(() => {}); server.close();
}
fs.writeFileSync('replay-case.json', JSON.stringify(out, null, 1));
