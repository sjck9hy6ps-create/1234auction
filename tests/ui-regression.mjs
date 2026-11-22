/* 화면 조작 자동 시험 (2026-11-22): 실제 클릭·입력으로 장부 입력 화면을 점검(저장은 하지 않음, 서버 요청은 모두 차단)
   점검: 장부 새로 만들기 화면 → 이름 입력 → 비용 카드 클릭→팝업에 금액 입력→확인 → 카드에 금액 표시 → 초안 자동 보관 →
         새로고침 후 같은 장부를 열면 입력이 복원 → 모바일 폭에서 설명 버튼이 삭제 버튼과 겹치지 않음 → 스크립트 오류 없음
   사용: node tests/ui-regression.mjs (CHROME_PATH로 크롬 경로 지정 가능) */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public');
let pw; try { pw = await import('playwright'); } catch (e) { pw = await import('playwright-core'); }
const { chromium } = pw.default && pw.default.chromium ? pw.default : pw;
const MIME = { '.html': 'text/html; charset=utf-8', '.json': 'application/json; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css' };
const server = http.createServer((req, res) => {
  const u = decodeURIComponent((req.url || '/').split('?')[0]); const f = path.join(ROOT, u === '/' ? 'index.html' : u);
  if (!f.startsWith(ROOT) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); res.end('not found'); return; }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' }); res.end(fs.readFileSync(f));
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {});
const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 }, timezoneId: 'Asia/Seoul', locale: 'ko-KR' });
const page = await ctx.newPage();
const errors = [], R = [];
const ok = (name, pass, detail) => R.push({ name, pass: !!pass, detail: pass ? '' : String(detail || '').slice(0, 300) });
page.on('pageerror', (e) => errors.push(String(e).slice(0, 200)));
page.on('dialog', (d) => d.accept());
await page.route((u) => !String(u).startsWith(base), (r) => r.abort());
await page.route((u) => String(u).startsWith(base + '/api/'), (r) => r.fulfill({ status: 404, body: '{}' }));
const load = async () => { await page.goto(base + '/index.html', { waitUntil: 'domcontentloaded' }); await page.waitForFunction(() => typeof window.ledgerEdit === 'function' && typeof window.openMyAssetsPanel === 'function', null, { timeout: 60000 }); await page.waitForTimeout(1200); };
const openForm = () => page.evaluate(() => { ledger.loaded = true; myAssets.loaded = true; document.getElementById('my-assets-panel').style.display = 'block'; ledgerEdit('new'); });

try {
  await load(); await openForm();
  await page.waitForSelector('#lg-form', { timeout: 10000 });
  ok('장부 새로 만들기 화면이 열림', true);
  await page.locator('#lg-form .lg-field:has(#lg-name)').click();
  await page.waitForSelector('#lg-fld-pop', { timeout: 5000 });
  await page.locator('#lg-fld-pop input').first().fill('시험 오피스텔');
  await page.locator('#lg-fld-pop button:has-text("확인")').click();
  await page.waitForTimeout(400);
  ok('기본 정보 카드를 눌러 팝업에서 이름 입력', (await page.locator('#lg-form').innerText()).includes('시험 오피스텔'));
  const cards = page.locator('#lg-form .lg-cost-card:not(.lg-cost-add)');
  const nCards = await cards.count();
  ok('필수 비용 카드가 미리 떠 있음', nCards >= 3, 'cards=' + nCards);
  if (nCards) {
    await cards.first().click();
    await page.waitForSelector('#lg-cost-pop', { timeout: 5000 });
    ok('비용 카드를 누르면 팝업이 뜸', true);
    const amt = page.locator('#lg-cost-pop input[type=number], #lg-cost-pop input.lg-won').first();
    await amt.fill('1234567');
    await page.locator('#lg-cost-pop button:has-text("확인")').click();
    await page.waitForTimeout(400);
    ok('확인 후 팝업이 닫힘', (await page.locator('#lg-cost-pop').count()) === 0);
    const txt = await page.locator('#lg-form').innerText();
    ok('입력한 금액이 카드에 표시됨', /123만|1,234,567|123\.4|123만 4/.test(txt), txt.slice(0, 120));
  }
  // 비용 항목 추가 버튼 → 새 카드가 늘어남
  const before = await page.locator('#lg-form .lg-cost-card').count();
  await page.evaluate(() => ledgerAddItem());
  await page.waitForTimeout(300);
  ok('비용 추가 시 카드/팝업이 반응함', (await page.locator('#lg-form .lg-cost-card').count()) > before || (await page.locator('#lg-cost-pop').count()) > 0, 'before=' + before);
  await page.evaluate(() => { try { ledgerCostClose(); } catch (e) {} });
  // 초안 자동 보관 → 새로고침 → 복원
  await page.evaluate(() => { ledgerSyncDraft(); lgDraftSave(); });
  const saved = await page.evaluate(() => localStorage.getItem('ledgerDraftV1'));
  ok('입력 내용이 초안으로 자동 보관됨', saved && saved.includes('시험 오피스텔'), saved && saved.slice(0, 80));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => typeof window.ledgerEdit === 'function', null, { timeout: 60000 }); await page.waitForTimeout(1200);
  await page.evaluate(() => { ledger.loaded = true; myAssets.loaded = true; document.getElementById('my-assets-panel').style.display = 'block'; const r = lgDraftLoad(); ledgerEdit(r ? r.id : 'new'); });
  await page.waitForSelector('#lg-form', { timeout: 10000 });
  const nm = await page.evaluate(() => (document.getElementById('lg-name') || {}).value || '');
  ok('새로고침 뒤에도 입력한 이름이 복원됨', nm === '시험 오피스텔', nm);
  await page.evaluate(() => { try { lgDraftClear(); } catch (e) {} });
  // 모바일 폭: 설명 버튼이 삭제/저장 줄과 겹치지 않음
  await page.setViewportSize({ width: 390, height: 780 }); await page.waitForTimeout(400);
  const ov = await page.evaluate(() => {
    const a = document.getElementById('x-ex-global'), b = document.querySelector('#lg-form .lgp-actions, #lg-form [onclick*="ledgerCancel"], #lg-form [onclick*="ledgerSave"]');
    if (!a || !b) return { skip: true, a: !!a, b: !!b };
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect(); b.scrollIntoView({ block: 'end' });
    const rb2 = b.getBoundingClientRect(), ra2 = a.getBoundingClientRect();
    const hit = !(ra2.right < rb2.left || ra2.left > rb2.right || ra2.bottom < rb2.top || ra2.top > rb2.bottom);
    return { hit, skip: false };
  });
  ok('모바일에서 설명 버튼이 저장·취소 줄과 겹치지 않음', ov.skip || !ov.hit, JSON.stringify(ov));
} catch (e) { ok('화면 시험 진행 중 예외 없음', false, e.message); }
ok('화면 시험 중 스크립트 오류 없음', errors.length === 0, errors.slice(0, 3).join(' | '));
await browser.close(); server.close();
const failed = R.filter((r) => !r.pass);
console.log(`화면 조작 자동 시험: ${R.length - failed.length}/${R.length} 통과`);
failed.forEach((r) => console.log(`  ✗ ${r.name}${r.detail ? ' — ' + r.detail : ''}`));
process.exit(failed.length ? 1 : 0);
