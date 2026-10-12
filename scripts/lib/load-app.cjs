/* 앱 계산식을 Node에서 그대로 불러오는 도구(2026-10-12) - public/index.html의 스크립트를 가짜 DOM에서 실행해
   solveAuctionBidFromRecord(비용·세금·대출 계산)·rightsWaterfall(권리분석) 같은 함수를 직접 호출할 수 있게 함.
   규칙을 바꾸기 전에 과거 낙찰 사례로 검증(scripts/backtest/run-rule.cjs)할 때 씀. APP_HTML 환경변수로 다른 버전(예: git show 결과)도 불러올 수 있음 */
const vm = require('vm'), fs = require('fs'), path = require('path');
function loadApp(opts) {
    opts = opts || {};
    const file = process.env.APP_HTML || path.join(__dirname, '..', '..', 'public', 'index.html');
    const html = fs.readFileSync(file, 'utf8');
    const mains = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]).filter((x) => x.length > 1000);
    const stub = () => new Proxy(function () {}, { get: (t, k) => (k === Symbol.toPrimitive ? () => '' : k === 'length' ? 0 : k === 'then' ? undefined : stub()), apply: () => stub(), construct: () => stub(), set: () => true });
    const store = {};
    const ctx = { console, setTimeout: () => 0, setInterval: () => 0, clearTimeout() {}, clearInterval() {}, requestAnimationFrame: () => 0,
        fetch: () => Promise.reject(new Error('nofetch')), performance: { now: () => Date.now() }, Date, Math, JSON,
        localStorage: { getItem: (k) => store[k] || null, setItem(k, v) { store[k] = String(v); }, removeItem(k) { delete store[k]; } },
        document: stub(), navigator: { userAgent: 'node', language: 'ko' }, location: { href: '', search: '', hash: '', origin: 'x', pathname: '/' },
        indexedDB: undefined, IntersectionObserver: function () {}, ResizeObserver: function () {}, MutationObserver: function () {}, Image: function () {}, XMLHttpRequest: function () {} };
    ctx.addEventListener = () => {}; ctx.removeEventListener = () => {}; ctx.window = ctx; ctx.self = ctx; ctx.globalThis = ctx;
    vm.createContext(ctx);
    for (const m of mains) { try { vm.runInContext(m, ctx, { filename: 'app.js' }); } catch (e) { if (opts.verbose) console.error(e); } }
    if (opts.myAssets) { ctx.myAssets.items = opts.myAssets.filter((x) => x && x.id !== 'profile'); ctx.myAssets.profile = opts.myAssets.filter((x) => x && x.id === 'profile')[0] || null; ctx.myAssets.loaded = true; }
    return ctx;
}
module.exports = { loadApp };
