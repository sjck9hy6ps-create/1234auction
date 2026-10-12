/* 규칙 검증 틀(2026-10-12) - "이 규칙으로 입찰했다면 과거에 얼마 벌고 얼마 잃었나"를 앱의 실제 비용·세금·대출 계산으로 돌려 봄.
   준비: ① python scripts/backtest/prep-rows.py bidcases-R.csv.gz rows.json  ② curl -s https://<앱>/api/auction?kind=bidCases -o bc.json  ③ curl ...?kind=myAssets -o ma.json
   실행: node scripts/backtest/run-rule.cjs rows.json bc.json ma.json [규칙파일.cjs]
   규칙파일은 { groups(ctx, a, E, M, h0, solve) → [[그룹이름, 입찰 상한(만원)], ...] } 를 내보냄(기본: 아래 DEFAULT - 순이익 1천만 기준 vs 순이익률 10/12%).
   결과: 그룹별 후보 수·상한 이하 낙찰 수·되판 확인 수·손해 비율·순이익 중앙값(실제 낙찰가로 산 경우 / 상한가로 산 경우).
   ⚠️ 되판 기록이 확인된 건만 셈(못 판 물건은 빠져 실제보다 좋게 나옴) - 규칙끼리 비교용 */
const fs = require('fs'), { loadApp } = require('../lib/load-app.cjs');
const [rowsF, bcF, maF, ruleF] = process.argv.slice(2);
if (!rowsF || !bcF) { console.error('사용: node run-rule.cjs rows.json bc.json [ma.json] [rule.cjs]'); process.exit(1); }
const ctx = loadApp({ myAssets: maF && fs.existsSync(maF) ? JSON.parse(fs.readFileSync(maF)) : null });
const bc = {}; JSON.parse(fs.readFileSync(bcF)).forEach((c) => (bc[c.id] = c));
const rows = JSON.parse(fs.readFileSync(rowsF));
const DEFAULT = { groups(ctx, a, E, M, h0, solve) {
    const b1k = solve(a, E, 1000, h0); if (!b1k) return [];
    if (b1k >= M) return [['기존: 순이익 1천만+', b1k]];
    const g = []; for (const q of [0.10, 0.12, 0.15]) { const b = solve(a, E, E * q, h0); if (b && b >= M) g.push(['순이익률 ' + Math.round(q * 100) + '%', b]); } return g;
} };
const rule = ruleF ? require(require('path').resolve(ruleF)) : DEFAULT;
const solve = (a, t, m, h) => { const r = ctx.solveAuctionBidFromRecord(Object.assign({}, a, { target: t, compTargetMargin: m, holdAuto: h })); return r && r.bid > 0 ? r.bid : null; };
const netAt = (a, S, P, h) => { const pts = []; for (const m of [-3000, -1500, 0, 1500, 3000]) { const b = solve(a, S, m, h); if (b) pts.push([b, m]); } if (pts.length < 2) return null; pts.sort((x, y) => x[0] - y[0]); let i = 1; while (i < pts.length - 1 && P > pts[i][0]) i++; const [b0, n0] = pts[i - 1], [b1, n1] = pts[i]; return n0 + (n1 - n0) * (P - b0) / ((b1 - b0) || 1); };
const holdOf = (n) => (n <= 2 ? 10 : (n <= 5 ? 7 : 6)), q = (a, p) => { a = a.slice().sort((x, y) => x - y); return a[Math.floor((a.length - 1) * p)]; };
const out = {};
for (const [id, E, A, M, S, rm, n12, area, fl] of rows) {
    const c = bc[id]; if (!c || !c.addrJibun) continue;
    const py = area / 3.3058, a = { id: 'b', addr: c.addrJibun, propType: c.propertyType && /다세대|연립/.test(c.propertyType) ? 'villa' : 'apt', floor: fl || 5, pyung: py, appraisal: Math.round(c.appraisalPrice / 10000), minBid: M, bidDate: c.saleDate };
    a.repair = ctx.effRepairFee(a, a.propType, py, null);
    const h0 = holdOf(n12 || 0), hh = rm > 0 ? Math.max(3, Math.min(12, Math.ceil(rm))) : h0;
    for (const [g, cap] of rule.groups(ctx, a, E, M, h0, solve)) {
        const o = { won: A > 0 && A <= cap };
        if (o.won && S > 0) { const x = netAt(a, S, A, hh), y = netAt(a, S, cap, hh); o.n1 = x != null && Math.abs(x) < S ? x : null; o.n2 = y != null && Math.abs(y) < S ? y : null; }
        (out[g] = out[g] || []).push(o);
    }
}
for (const g of Object.keys(out).sort()) {
    const G = out[g], W = G.filter((x) => x.won), st = (k) => { const v = W.map((x) => x[k]).filter((x) => x != null); return v.length ? { n: v.length, 손해: Math.round(v.filter((x) => x < 0).length / v.length * 100) + '%', 중앙: Math.round(q(v, 0.5)) + '만', 하위25: Math.round(q(v, 0.25)) + '만' } : null; };
    console.log(g, '| 후보', G.length, '상한 이하 낙찰', W.length, '\n   실제 낙찰가로 산 경우', JSON.stringify(st('n1')), '\n   상한가로 산 경우  ', JSON.stringify(st('n2')));
}
