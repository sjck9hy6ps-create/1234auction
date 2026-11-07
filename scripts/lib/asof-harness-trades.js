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
        subj.sort((x, y) => (x.ap.dong + x.ap.bunji).localeCompare(y.ap.dong + y.ap.bunji) || x.p - y.p);
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
          pick.forEach((s, k) => {
            const l = s.ap.latest || {}, dong = s.ap.dong || l.dong || s.t.dong, bunji = l.bunji || s.ap.bunji || s.t.bunji || '', nm = l.name || s.ap.name || '';
            const a2 = { id: 'asoft_' + lawd + '_' + c + '_' + k, propType: 'apt', addr: '서울특별시 ' + dong + ' ' + bunji, dong, bunji, name: nm, pyung: s.t.area / 3.305785, floor: s.t.floor, lat: s.ap.lat || l.lat || tmpl.lat, lon: s.ap.lon || l.lon || tmpl.lon,
              bCode: lawd + '10100', bidDate: new RD(C + 35 * 864e5).toISOString().slice(0, 10), minBid: '10000', appraisal: '20000', buildYear: parseInt(s.t.build_year) || null };
            let row = null, err = null; try { row = computeBidBoardRow(a2); } catch (e) { err = String(e.message || e).slice(0, 80); }
            rows.push({ cutoff: c, id: a2.id, lawd, cls: row && row.regionCls, sale: row && row.sale, by: row && (row.saleSimBy || ''), n6: row && row.ownStats ? row.ownStats.n6 : null, weak: !!(row && row.saleFb && row.saleFb.weak), pyung: a2.pyung, floor: a2.floor, truth: [s.p], err });
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
