/* 아파트 앱 종단 검증(실거래 기준) 도구(2026-11-07): window.__v2. 경매 물건이 아니라 '실제 아파트 거래'를 대상으로 함 - 시점(cutoff)으로 되돌린 자료로 앱의 getAuctionWonEstimates가 낸 예상매도가를
   그 시점 이후 windowDays 안에 실제로 거래된 그 거래의 가격(정답)과 비교. 서울처럼 경매 물건이 적은 지역도 수천 건으로 잴 수 있음. 지역 자료는 앱의 입찰후보 계산과 같은 방식으로 받고 내림. */
(function () {
  const RD = Date;
  window.__v2 = {
    RD,
    lawds(prefix) {
      const set = {};
      auctionList.forEach((a) => { if (a.propType === 'apt' && a.lat && a.lon) { const l = bidBoardLawdOf(a); if (l && l.startsWith(prefix)) set[l] = { lat: a.lat, lon: a.lon }; } });
      return set;
    },
    async processRegionTrades(lawd, tmpl, cutoffs, windowDays, cap) {
      const wasLoaded = !!dataCache[lawd];
      if (!wasLoaded) {
        const d = await fetchHouseDataCached(lawd);
        if (!d || d.error || !Array.isArray(d.apt)) throw new Error('지역 자료를 못 받음 ' + lawd);
        await ingestRegionHouseData(d, '', lawd);
      }
      const origList = allAptList, region = origList.filter((ap) => ap.lawdCd === lawd && (ap.buildingType || 'apt') === 'apt'), rentFull = rentCacheByLawd[lawd];
      region.forEach((ap) => { if (!ap.__ot) ap.__ot = ap.trades; });
      const rows = []; let eligible = 0;
      for (const c of cutoffs) {
        const C = new RD(c + 'T00:00:00+09:00').getTime(), end = C + windowDays * 864e5, subj = [];
        region.forEach((ap) => (ap.__ot || []).forEach((t) => {
          if (t.dealing_type === '직거래' || !(t.area >= 30 && t.area <= 200)) return;
          const d = new RD(t.year, t.month - 1, t.day).getTime(); if (d < C || d >= end) return;
          const p = parseInt(t.amount); if (!p) return; subj.push({ ap, t, p });
        }));
        const ky = (z) => String(z.ap.dong || '') + '|' + String(z.ap.bunji || '') + '|' + String(z.ap.name || ''); subj.sort((x, y) => ky(x).localeCompare(ky(y)) || x.p - y.p);
        eligible += subj.length;
        const step = Math.max(1, Math.ceil(subj.length / cap)), pick = subj.filter((_, i) => i % step === 0);
        if (!pick.length) continue;
        class FD extends RD { constructor(...a) { if (a.length === 0) super(C); else super(...a); } static now() { return C; } }
        try {
          window.Date = FD;
          const list = [];
          region.forEach((ap) => {
            const tr = ap.__ot.filter((t) => new RD(t.year, t.month - 1, t.day).getTime() < C);
            if (tr.length) list.push(Object.assign({}, ap, { trades: tr, latest: tr[0] }));
          });
          allAptList = list; buildAptMatchIndex();
          if (rentFull) rentCacheByLawd[lawd] = rentFull.filter((r) => { const ds = String(r.deal_date || ''); return ds.length < 8 || new RD(+ds.slice(0, 4), +ds.slice(4, 6) - 1, +ds.slice(6, 8)).getTime() < C; });
          auctionWonEstCache = {}; regionPpmIdxCache = {}; try { calcPriceGrades(); } catch (e) {}
          // 지역·동 시세 흐름(㎡당 중위값: 최근 3개월 ÷ 이전 3~6개월, 최근 6개월 ÷ 6~12개월) - 시점 기준 자료만 사용
          const medx = (x) => { if (!x.length) return null; x = x.slice().sort((m, n) => m - n); const q = x.length >> 1; return x.length % 2 ? x[q] : (x[q - 1] + x[q]) / 2; };
          const mom = {}, momOf = (key, arr) => {
            const r3 = [], p3 = [], r6 = [], p6 = [], r12 = [];
            arr.forEach((z) => { const ag = (C - z.td) / 864e5 / 30.4;
              if (ag <= 3) r3.push(z.ppm); else if (ag <= 6) p3.push(z.ppm);
              if (ag <= 6) r6.push(z.ppm); else if (ag <= 12) p6.push(z.ppm);
              if (ag <= 12) r12.push(z.ppm); });
            const f = (a, b) => (a.length >= 5 && b.length >= 5) ? Math.log(medx(a) / medx(b)) : null;
            mom[key] = { m3: f(r3, p3), m6: f(r6, p6), v3: r3.length, v12: r12.length };
          };
          const byDong = {}, allL = [];
          list.forEach((ap) => ap.trades.forEach((t) => { if (t.dealing_type === '직거래' || !(t.area > 0)) return; const td = new RD(t.year, t.month - 1, t.day).getTime(), pp = parseInt(t.amount); if (!pp || (C - td) / 864e5 / 30.4 > 12) return;
            const z = { td, ppm: pp / t.area }; allL.push(z); const dk = String(ap.dong || ''); (byDong[dk] = byDong[dk] || []).push(z); }));
          momOf('L', allL); Object.keys(byDong).forEach((dk) => momOf('D' + dk, byDong[dk]));
          pick.forEach((s, k) => {
            const l = s.ap.latest || {}, dong = s.ap.dong || l.dong || s.t.dong, bunji = l.bunji || s.ap.bunji || s.t.bunji || '', nm = l.name || s.ap.name || '';
            const a2 = { id: 'asoft_' + lawd + '_' + c + '_' + k, propType: 'apt', addr: '서울특별시 ' + dong + ' ' + bunji, dong, bunji, name: nm, pyung: s.t.area / 3.305785, floor: s.t.floor, lat: s.ap.lat || l.lat || tmpl.lat, lon: s.ap.lon || l.lon || tmpl.lon,
              bCode: lawd + '10100', bidDate: new RD(C + 35 * 864e5).toISOString().slice(0, 10), minBid: '10000', appraisal: '20000', buildYear: parseInt(s.t.build_year) || null };
            let row = null, err = null; try { row = computeBidBoardRow(a2); } catch (e) { err = String(e.message || e).slice(0, 80); }
            const os = (row && row.ownStats) || {}, ml = mom.L || {}, md = mom['D' + (s.ap.dong || '')] || {}, rd = (v, d) => v == null || isNaN(v) ? null : +(+v).toFixed(d == null ? 4 : d);
            const feat = row ? { base: row.saleBase || null, sfl: row.saleFlow ? rd(row.saleFlow.adj) : null, sfc: row.saleFlow && row.saleFlow.fc ? rd(row.saleFlow.fc.adj) : null, tur: row.saleTurn ? rd(row.saleTurn.factor) : null, jrf: row.saleJr ? rd(row.saleJr.factor) : null, jrr: row.saleJr ? rd(row.saleJr.ratio) : null,
              fbT: row.saleFb ? (row.saleFb.tier || '') : '', fbN: row.saleFb ? row.saleFb.n : null, fl: row.saleFloorAdj ? rd(row.saleFloorAdj.factor) : null, cap: row.saleCapBy ? 1 : 0, wb: row.wbBase || null,
              n3: os.n3, n12: os.n12, n36: os.n36, l3: os.last3, pw1: os.pw1, pw2: os.pw2, pw2f: os.pw2f, p3m: os.p3med, q40: os.p6q40, m12: os.med12, m36: os.med36, lp: os.lastP, lag: os.lastAgeM, dsp: rd(os.disp6), v6: os.v6, vp6: os.vPrev6, mxF: os.maxF, tr: os.trend ? os.trend.pct : null, jm: os.jeonse ? rd(os.jeonse.ratio) : null,
              lm3: rd(ml.m3), lm6: rd(ml.m6), lv3: ml.v3, lv12: ml.v12, dm3: rd(md.m3), dm6: rd(md.m6), dv3: md.v3, dv12: md.v12, by: a2.buildYear || null } : null;
            rows.push({ cutoff: c, id: a2.id, lawd, cls: row && row.regionCls, sale: row && (row.saleApp != null ? row.saleApp : row.sale), stk: row && row.saleStack ? row.sale : null, by: row && (row.saleSimBy || ''), n6: row && row.ownStats ? row.ownStats.n6 : null, weak: !!(row && row.saleFb && row.saleFb.weak), pyung: a2.pyung, floor: a2.floor, truth: [s.p], err, f: feat, dong: s.ap.dong || '', tdate: new RD(s.t.year, s.t.month - 1, s.t.day).toISOString().slice(0, 10) });
          });
        } finally {
          window.Date = RD; allAptList = origList; buildAptMatchIndex();
          if (rentFull) rentCacheByLawd[lawd] = rentFull;
        }
      }
      if (!wasLoaded) {
        delete dataCache[lawd]; delete rentCacheByLawd[lawd]; try { mergedLawdCds.delete(lawd); } catch (e) {}
        try { const vi = lawdCdVisitOrder.indexOf(lawd); if (vi !== -1) lawdCdVisitOrder.splice(vi, 1); } catch (e) {}
        try { rebuildMergedLists(); } catch (e) { allAptList = origList.filter((ap) => ap.lawdCd !== lawd); buildAptMatchIndex(); }
      }
      return { rows, eligible };
    }
  };
})();
