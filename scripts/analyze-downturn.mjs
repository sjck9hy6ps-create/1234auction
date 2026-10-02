// ════════════════════════════════════════════════════════════
// 하락장 검증 분석 (읽기 전용 - DB를 전혀 수정하지 않고 결과를 로그로만 출력)
//
// 앱의 "매도 시점 흐름 반영"(index.html calcForwardTrend)은 2025~2026년(대부분 상승기) 데이터로만
// 검증돼서 상승분만 반영하고 있음. 하락장에서도 쓸 수 있는지 보려고, 2022년 급락·2023~24년 회복이
// 들어있는 2020-10 ~ 2024-12 아파트 실거래로 같은 방식의 백테스트를 돌림:
//   - 단위: 단지+평형(지역|동|단지|전용면적 반올림)
//   - 기준값: 기준일 직전 3개월 평단가 중앙값(앱 비교물건이 이미 "현재 시세"에 맞춰진 것과 같은 조건)
//   - 정답: 기준일 이후 4개월(낙찰→매도 기간) 실거래 평단가 중앙값
//   - 신호: 대장(동 내 평단가·거래량 백분위 평균 1위)/인기 상위3/동 전체/시군구 전체/자기 단지의
//     최근 3개월 vs 그 앞 6개월 변동률
//   - 국면: 시군구 전체 변동률로 하락(< -2%)/보합/상승(> +2%) 구분
//   - 기준일 2021-03 ~ 2024-06 분기별 14개 - 짝수 번째로 계수를 정하고 홀수 번째로만 채점(상승·하락
//     국면이 양쪽에 다 들어가게)
// ════════════════════════════════════════════════════════════
import { supabase, LAWD_CODES } from './shared.mjs';

const FROM = 20200601, TO = 20241231;
const DAY = 86400000;
const dnum = (yyyymmdd) => { const s = String(yyyymmdd); return Date.UTC(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8)) / DAY; };
const addM = (d, m) => { const x = new Date(d * DAY); return Date.UTC(x.getUTCFullYear(), x.getUTCMonth() + m, x.getUTCDate()) / DAY; };
const med = (a) => { const s = a.slice().sort((x, y) => x - y); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

// ── 1. 데이터 적재(지역별 페이지네이션) ──
const regions = [...new Set(LAWD_CODES.map(r => r.name))];
const units = new Map(); // key -> [[day, ppp], ...]
let total = 0;
async function loadRegion(region) {
  let from = 0;
  for (;;) {
    let data, error;
    for (let a = 1; a <= 3; a++) {
      ({ data, error } = await supabase.from('house_trades').select('dong,danji,deal_date,price,size,dealing_type')
        .eq('region', region).gte('deal_date', FROM).lte('deal_date', TO).order('id').range(from, from + 999));
      if (!error) break;
      await new Promise(r => setTimeout(r, 2000 * a));
    }
    if (error) { console.error('적재 실패', region, error.message); return; }
    for (const r of data) {
      if (r.dealing_type === '직거래' || !r.price || !r.size || !r.danji) continue;
      const k = `${region}|${r.dong}|${r.danji}|${Math.round(r.size)}`;
      if (!units.has(k)) units.set(k, []);
      units.get(k).push([dnum(r.deal_date), r.price / (r.size / 3.305785)]);
      total++;
    }
    if (data.length < 1000) return;
    from += 1000;
  }
}
let idx = 0;
await Promise.all(Array.from({ length: 6 }, async () => { while (idx < regions.length) await loadRegion(regions[idx++]); }));
console.log(`적재: ${total.toLocaleString()}건, 단지·평형 ${units.size.toLocaleString()}개`);

// ── 2. 기준일별 표본 만들기 ──
const cutoffs = [];
for (let y = 2021; y <= 2024; y++) for (const m of [3, 6, 9, 12]) { const d = Date.UTC(y, m - 1, 28) / DAY; if (d <= Date.UTC(2024, 5, 30) / DAY) cutoffs.push(d); }
const unitKeys = [...units.keys()];
const samples = [];
function medIn(list, a, b) { const v = []; for (const [d, p] of list) if (d > a && d <= b) v.push(p); return v.length ? [med(v), v.length] : [null, 0]; }

cutoffs.forEach((T, ti) => {
  const R0 = addM(T, -3), P0 = addM(T, -9), H1 = addM(T, 4);
  const st = new Map();
  for (const k of unitKeys) {
    const L = units.get(k);
    const [base, nb] = medIn(L, R0, T), [pri] = medIn(L, P0, R0), [act, na] = medIn(L, T, H1), [lvl, n9] = medIn(L, P0, T);
    st.set(k, { base, nb, mom: (base && pri) ? base / pri - 1 : null, act, na, lvl, n9 });
  }
  const cplx = new Map(); // region|dong|danji -> unit keys
  for (const k of unitKeys) { const c = k.split('|').slice(0, 3).join('|'); if (!cplx.has(c)) cplx.set(c, []); cplx.get(c).push(k); }
  const dongC = new Map();
  for (const c of cplx.keys()) { const d = c.split('|').slice(0, 2).join('|'); if (!dongC.has(d)) dongC.set(d, []); dongC.get(d).push(c); }
  const gm = (ks) => { const m = ks.map(k => st.get(k).mom).filter(v => v !== null); return m.length ? med(m) : null; };
  const dongInfo = new Map();
  for (const [d, cl] of dongC) {
    const info = cl.map(c => { const ks = cplx.get(c); const lv = ks.map(k => st.get(k).lvl).filter(Boolean); const cnt = ks.reduce((s, k) => s + st.get(k).n9, 0); return { c, lvl: lv.length ? med(lv) : null, cnt }; })
      .filter(x => x.cnt >= 3 && x.lvl);
    if (info.length < 2) continue;
    const pct = (key) => { const s = info.slice().sort((a, b) => b[key] - a[key]); const m = {}; s.forEach((x, i) => { m[x.c] = (s.length - i) / s.length; }); return m; };
    const pp = pct('lvl'), vv = pct('cnt');
    const leader = info.slice().sort((a, b) => ((pp[b.c] + vv[b.c]) - (pp[a.c] + vv[a.c])) || (b.cnt - a.cnt))[0].c;
    const popular = info.slice().sort((a, b) => b.cnt - a.cnt).slice(0, 3).map(x => x.c);
    dongInfo.set(d, { leader, lm: gm(cplx.get(leader)), pm: gm(popular.flatMap(c => cplx.get(c))), dm: gm(cl.flatMap(c => cplx.get(c))) });
  }
  const regU = new Map();
  for (const k of unitKeys) { const r = k.split('|')[0]; if (!regU.has(r)) regU.set(r, []); regU.get(r).push(k); }
  const rm = new Map(); for (const [r, ks] of regU) rm.set(r, gm(ks));
  for (const k of unitKeys) {
    const s = st.get(k);
    if (s.nb < 2 || s.na < 1) continue;
    const parts = k.split('|'); const d = parts.slice(0, 2).join('|'); const di = dongInfo.get(d);
    if (!di || parts.slice(0, 3).join('|') === di.leader) continue;
    samples.push({ ti, cap: /^(서울|경기|인천)/.test(parts[0]), y: Math.log(s.act / s.base), own: s.mom, lm: di.lm, pm: di.pm, dm: di.dm, rm: rm.get(parts[0]) });
  }
  console.log(`기준일 ${new Date(T * DAY).toISOString().slice(0, 7)}: 누적 표본 ${samples.length.toLocaleString()}`);
});

// ── 3. 평가 ──
const feats = {
  lm_pos: s => s.lm == null ? 0 : Math.max(0, Math.min(s.lm, 0.1)), lm_neg: s => s.lm == null ? 0 : Math.min(0, Math.max(s.lm, -0.1)),
  pm_pos: s => s.pm == null ? 0 : Math.max(0, Math.min(s.pm, 0.1)), pm_neg: s => s.pm == null ? 0 : Math.min(0, Math.max(s.pm, -0.1)),
  rm_pos: s => s.rm == null ? 0 : Math.max(0, Math.min(s.rm, 0.1)), rm_neg: s => s.rm == null ? 0 : Math.min(0, Math.max(s.rm, -0.1)),
  dm_neg: s => s.dm == null ? 0 : Math.min(0, Math.max(s.dm, -0.1)),
};
function fit(rows, keys) {
  const k = keys.length; const A = Array.from({ length: k }, () => new Array(k + 1).fill(0));
  for (const r of rows) { const x = keys.map(f => feats[f](r)); for (let i = 0; i < k; i++) { A[i][k] += x[i] * r.y; for (let j = 0; j < k; j++) A[i][j] += x[i] * x[j]; } }
  for (let i = 0; i < k; i++) A[i][i] += 1e-6 + rows.length * 1e-4;
  for (let c = 0; c < k; c++) { let p = c; for (let r = c + 1; r < k; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r; [A[c], A[p]] = [A[p], A[c]];
    for (let r = 0; r < k; r++) if (r !== c) { const f = A[r][c] / A[c][c]; for (let j = c; j <= k; j++) A[r][j] -= f * A[c][j]; } }
  return A.map((row, i) => row[k] / row[i]);
}
function score(rows, keys, beta) {
  const e = rows.map(r => (Math.exp(keys.reduce((s, f, i) => s + beta[i] * feats[f](r), 0) - r.y) - 1) * 100);
  const a = e.map(Math.abs);
  return { n: rows.length, med: med(a), mean: a.reduce((x, y) => x + y, 0) / a.length, bias: med(e), w5: a.filter(x => x <= 5).length / a.length * 100 };
}
const fmt = (o) => `n=${o.n} 중앙오차 ${o.med.toFixed(2)}% 평균 ${o.mean.toFixed(2)}% 쏠림 ${o.bias >= 0 ? '+' : ''}${o.bias.toFixed(2)}% ±5%이내 ${o.w5.toFixed(1)}%`;
const regime = (s) => s.rm == null ? '보합' : s.rm < -0.02 ? '하락' : s.rm > 0.02 ? '상승' : '보합';

for (const [seg, cap] of [['수도권', true], ['지방', false]]) {
  const all = samples.filter(s => s.cap === cap);
  const tr = all.filter(s => s.ti % 2 === 0), te = all.filter(s => s.ti % 2 === 1);
  console.log(`\n════ ${seg}: 학습 ${tr.length.toLocaleString()} / 채점 ${te.length.toLocaleString()} ════`);
  const prodBeta = cap ? 0.5 : 0.2, prodKey = cap ? 'lm_pos' : 'pm_pos';
  const models = [
    ['① 흐름 반영 안 함', [], []],
    ['② 현재 앱(상승분만, 고정계수)', [prodKey], [prodBeta]],
    ['③ 대장 상승+하락', ['lm_pos', 'lm_neg'], null],
    ['④ 인기단지 상승+하락', ['pm_pos', 'pm_neg'], null],
    ['⑤ 시군구 상승+하락', ['rm_pos', 'rm_neg'], null],
    ['⑥ 대장 상승 + 시군구 하락', ['lm_pos', 'rm_neg'], null],
    ['⑦ 인기 상승 + 시군구 하락', ['pm_pos', 'rm_neg'], null],
    ['⑧ 대장 상승 + 동 하락', ['lm_pos', 'dm_neg'], null],
  ];
  for (const [name, keys, fixed] of models) {
    const beta = fixed || (keys.length ? fit(tr, keys) : []);
    const bstr = keys.map((k, i) => `${k}=${beta[i].toFixed(2)}`).join(', ') || '-';
    console.log(`${name} [${bstr}]`);
    console.log(`   전체   ${fmt(score(te, keys, beta))}`);
    for (const rg of ['하락', '보합', '상승']) { const sub = te.filter(s => regime(s) === rg); if (sub.length > 200) console.log(`   ${rg}장 ${fmt(score(sub, keys, beta))}`); }
  }
  // 하락장에서 시군구가 X% 빠지면 나머지 단지는 다음 4개월 실제로 얼마나 빠졌나
  console.log(`  [시군구 최근 3개월 변동 → 다음 4개월 실제 변동(중앙값)]`);
  for (const [lo, hi] of [[-1, -0.05], [-0.05, -0.02], [-0.02, 0.02], [0.02, 0.05], [0.05, 1]]) {
    const v = all.filter(s => s.rm != null && s.rm >= lo && s.rm < hi).map(s => Math.exp(s.y) - 1);
    if (v.length > 200) console.log(`   ${(lo * 100).toFixed(0)}%~${(hi * 100).toFixed(0)}%: 표본 ${v.length.toLocaleString()} 다음 4개월 ${(med(v) * 100).toFixed(1)}% 하락비율 ${(v.filter(x => x < 0).length / v.length * 100).toFixed(0)}%`);
  }
}
