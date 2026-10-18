/* 앱 종단 검증 도구(2026-10-19): 페이지에 window.__v를 심음. 지역 하나의 거래 자료를 불러와 과거 시점(cutoff)으로 되돌린 뒤 앱의 computeBidBoardRow로 경매 아파트의 예상매도가를 계산하고,
   그 시점 이후 windowDays 안에 실제로 거래된 같은 단지·같은 평형(±3㎡) 가격(정답)과 함께 돌려줌. 계산이 끝나면 그 지역 자료를 메모리에서 내림(앱의 입찰후보 계산과 같은 방식). */
(function () {
  const RD = Date;
  window.__v = {
    RD,
    regions() {
      const set = {};
      auctionList.forEach((a) => { if (a.propType === 'apt' && !a.isBacktest && a.lat && a.lon && parseFloat(a.pyung) > 0) { const l = bidBoardLawdOf(a); if (l) set[l] = (set[l] || 0) + 1; } });
      return set;
    },
    async processRegion(lawd, cutoffs, windowDays, cap) {
      const subjects = auctionList.filter((a) => a.propType === 'apt' && !a.isBacktest && a.lat && a.lon && parseFloat(a.pyung) > 0 && bidBoardLawdOf(a) === lawd);
      if (!subjects.length) return { rows: [], eligible: 0 };
      const wasLoaded = !!dataCache[lawd];
      if (!wasLoaded) {
        const d = await fetchHouseDataCached(lawd);
        if (!d || d.error || !Array.isArray(d.apt)) throw new Error('지역 자료를 못 받음 ' + lawd);
        await ingestRegionHouseData(d, '', lawd);
      }
      const origList = allAptList, region = origList.filter((ap) => ap.lawdCd === lawd), rentFull = rentCacheByLawd[lawd];
      region.forEach((ap) => { if (!ap.__ot) ap.__ot = ap.trades; });
      // 정답(되돌리기 전 전체 자료): cutoff마다 이후 windowDays 안의 같은 단지·같은 평형 중개 거래가
      const truth = {};
      subjects.forEach((a) => {
        const bj = fullBunjiFromAddr(a.addr, a.dong, a.bunji), area = parseFloat(a.pyung) * 3.305785, own = ownComplexEntries(a, bj, 'apt');
        cutoffs.forEach((c) => {
          const C = new RD(c + 'T00:00:00+09:00').getTime(), end = C + windowDays * 864e5, tr = [];
          own.forEach((ap) => (ap.__ot || ap.trades || []).forEach((t) => {
            if (t.dealing_type === '직거래' || Math.abs(t.area - area) > 3) return;
            const d = new RD(t.year, t.month - 1, t.day).getTime();
            if (d >= C && d < end) tr.push({ d, p: parseInt(t.amount) });
          }));
          if (tr.length) { tr.sort((x, y) => x.d - y.d); (truth[a.id] = truth[a.id] || {})[c] = tr.map((x) => x.p); }
        });
      });
      const rows = []; let eligible = 0;
      const byId = {}; subjects.forEach((a) => { byId[a.id] = a; });
      for (const c of cutoffs) {
        const ids = Object.keys(truth).filter((id) => truth[id][c]).sort();
        eligible += ids.length;
        const step = Math.max(1, Math.ceil(ids.length / cap)), pick = ids.filter((_, i) => i % step === 0);
        if (!pick.length) continue;
        const C = new RD(c + 'T00:00:00+09:00').getTime();
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
          pick.forEach((id) => {
            const a = byId[id], a2 = Object.assign({}, a, { id: 'asof_' + a.id, bidDate: new RD(C + 35 * 864e5).toISOString().slice(0, 10) });
            let row = null, err = null; try { row = computeBidBoardRow(a2); } catch (e) { err = String(e.message || e).slice(0, 80); }
            rows.push({ cutoff: c, id, lawd, cls: row && row.regionCls, sale: row && row.sale, by: row && (row.saleSimBy || ''), n6: row && row.ownStats ? row.ownStats.n6 : null, weak: !!(row && row.saleFb && row.saleFb.weak), pyung: a.pyung, floor: a.floor, truth: truth[id][c], err });
          });
        } finally {
          window.Date = RD; allAptList = origList; buildAptMatchIndex();
          if (rentFull) rentCacheByLawd[lawd] = rentFull;
        }
      }
      // 지역 자료 내림(앱의 입찰후보 계산과 같은 정리)
      if (!wasLoaded) {
        delete dataCache[lawd]; delete rentCacheByLawd[lawd]; try { mergedLawdCds.delete(lawd); } catch (e) {}
        try { const vi = lawdCdVisitOrder.indexOf(lawd); if (vi !== -1) lawdCdVisitOrder.splice(vi, 1); } catch (e) {}
        try { rebuildMergedLists(); } catch (e) { allAptList = origList.filter((ap) => ap.lawdCd !== lawd); buildAptMatchIndex(); }
      }
      return { rows, eligible };
    }
  };
})();
