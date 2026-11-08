/* 세 가격(예상매도가·예상낙찰가·추천입찰가) 채점(2026-11-08): apt-case-data가 모은 rows.json들을 합쳐, 낙찰가 모델이 학습에 쓰지 않은 구간만 채점. 사용: node scripts/score-asof-three-prices.mjs <rows.json이 든 폴더> */
import fs from 'fs'; import path from 'path';
const dir = process.argv[2] || 'aptcases';
const files = []; (function walk(d) { for (const f of fs.readdirSync(d, { withFileTypes: true })) { const q = path.join(d, f.name); if (f.isDirectory()) walk(q); else if (f.name === 'rows.json') files.push(q); } })(dir);
const rows = files.flatMap((f) => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch (e) { return []; } });
const OUT = 'three-price-score';
console.log('합친 사례', rows.length, '파일', files.length);

// 🎯 세 가격 채점(2026-11-08): 낙찰가 모델이 학습에 쓰지 않은 구간(2025-10-30 이후)만. 예상매도가=낙찰 뒤 6개월 같은 단지·평형 시장 실거래 중위값, 예상낙찰가=실제 낙찰가, 추천가=낙찰 가능성 보정·실현 마진
const med = (a) => { const b = a.slice().sort((x, y) => x - y); const n = b.length; return n ? (n % 2 ? b[(n - 1) / 2] : (b[n / 2 - 1] + b[n / 2]) / 2) : null; };
const seg = (l) => (String(l).startsWith('11') ? '서울' : (/^(41|28)/.test(String(l)) ? '경기·인천' : '지방'));
const OOS = '2025-10-30';
const oos = rows.filter((r) => !r.err && r.saleDate >= OOS);
const rep = {};
['전체', '서울', '경기·인천', '지방'].forEach((g) => {
  const R = oos.filter((r) => g === '전체' || seg(r.lawd) === g), o = { n: R.length };
  const S = R.filter((r) => r.mkt > 0 && r.saleFinal > 0), e1 = S.map((r) => r.saleFinal / r.mkt - 1), e0 = S.filter((r) => r.sale > 0).map((r) => r.sale / (S.find((x) => x.id === r.id).mkt) - 1);
  o.매도가 = { n: S.length, 오차: +(med(e1.map(Math.abs)) * 100).toFixed(2), 쏠림: +(med(e1) * 100).toFixed(2), 보정전오차: +(med(e0.map(Math.abs)) * 100).toFixed(2) };
  const W = R.filter((r) => r.wbP > 0 && r.act > 0), e2 = W.map((r) => r.wbP / r.act - 1);
  o.낙찰가 = { n: W.length, 오차: +(med(e2.map(Math.abs)) * 100).toFixed(2), 쏠림: +(med(e2) * 100).toFixed(2), 예상가이하낙찰: +(100 * W.filter((r) => r.act <= r.wbP).length / (W.length || 1)).toFixed(1) };
  const Pq = R.filter((r) => r.rec > 0 && r.act > 0 && r.probRec != null);
  const win = (r) => (r.rec >= r.act ? 1 : 0), br = (f) => Pq.length ? +(Pq.reduce((s, r) => s + (f(r) - win(r)) ** 2, 0) / Pq.length).toFixed(4) : null;
  const bins = {}; Pq.forEach((r) => { const k = Math.min(4, Math.floor(r.probRec * 5)); (bins[k] = bins[k] || []).push(r); });
  o.추천가확률 = { n: Pq.length, 예측평균: Pq.length ? +(Pq.reduce((s, r) => s + r.probRec, 0) / Pq.length).toFixed(3) : null, 실제낙찰: Pq.length ? +(Pq.reduce((s, r) => s + win(r), 0) / Pq.length).toFixed(3) : null, brier보정: br((r) => r.probRec), brier원래: br((r) => r.probRaw ?? r.probRec), 구간: Object.keys(bins).sort().map((k) => ({ 예측: +(bins[k].reduce((s, r) => s + r.probRec, 0) / bins[k].length).toFixed(2), 실제: +(bins[k].reduce((s, r) => s + win(r), 0) / bins[k].length).toFixed(2), n: bins[k].length })) };
  const Wn = R.filter((r) => r.rec > 0 && r.act > 0 && r.rec >= r.act && r.mkt > 0 && r.saleFinal > 0 && r.margin != null), net = Wn.map((r) => (r.marginRaw != null ? r.marginRaw : r.margin) + (r.mkt - r.saleFinal));   // 보정 전 마진 + (낙찰 뒤 시장가 - 예상매도가): 낙찰 조건 보정이 들어간 마진을 쓰면 보정분을 두 번 셈
  o.추천가낙찰시 = { n: Wn.length, 예상마진중앙: Wn.length ? Math.round(med(Wn.map((r) => r.margin))) : null, 실현마진중앙: Wn.length ? Math.round(med(net)) : null, 손해비율: Wn.length ? +(100 * net.filter((x) => x < 0).length / Wn.length).toFixed(1) : null, 천만미만비율: Wn.length ? +(100 * net.filter((x) => x < 1000).length / Wn.length).toFixed(1) : null };
  rep[g] = o;
});
console.log('📊 세 가격 채점(학습에 안 쓴 ' + OOS + ' 이후):', JSON.stringify(rep, null, 1));
fs.writeFileSync('three-price-score.json', JSON.stringify(rep));
