/* 아파트 낙찰사례를 과거 시점으로 되돌려 앱 계산(종합 평가 보정 포함)을 다시 돌리는 도구(2026-11-07): window.__vc.
   사례마다 낙찰일 35일 전(주 단위로 묶음) 자료로 computeBidBoardRow를 돌려 보정 전/후 예상매도가와 예상 낙찰가용 시세(wbBase)를 돌려줌. 이 값으로 낙찰가 모델을 다시 학습·채점. */
(function () {
  const RD = Date;
  const labelOf = (addr) => bidBoardRegionLabel(addr);
  window.__vc = {
    RD,
    // 사례 → 지역코드: 같은 시도·시군구 표기를 가진 경매물건 중 가장 가까운 것의 코드(사례에는 법정동코드가 없음)
    assign(cases) {
      const by = {};
      auctionList.forEach((a) => { if (a.propType === 'apt' && a.lat && a.lon && a.bCode) (by[labelOf(a.addr)] = by[labelOf(a.addr)] || []).push({ lat: a.lat, lon: a.lon, l: String(a.bCode).slice(0, 5) }); });
      const out = {};
      cases.forEach((c) => {
        const L = by[labelOf(c.addrJibun)]; if (!L || !c.lat || !c.lon) return;
        let best = null, bd = 1e9; for (const p of L) { const d = (p.lat - c.lat) ** 2 + (p.lon - c.lon) ** 2; if (d < bd) { bd = d; best = p.l; } }
        if (best) (out[best] = out[best] || []).push(c.id);
      });
      return out;
    },
    async processCases(lawd, cases, daysBefore) {
      const wasLoaded = !!dataCache[lawd];
      if (!wasLoaded) {
        const d = await fetchHouseDataCached(lawd);
        if (!d || d.error || !Array.isArray(d.apt)) throw new Error('지역 자료를 못 받음 ' + lawd);
        await ingestRegionHouseData(d, '', lawd);
      }
      const origList = allAptList, region = origList.filter((ap) => ap.lawdCd === lawd && (ap.buildingType || 'apt') === 'apt'), rentFull = rentCacheByLawd[lawd];
      region.forEach((ap) => { if (!ap.__ot) ap.__ot = ap.trades; });
      const wk = (sale) => { const t = new RD(sale + 'T00:00:00+09:00').getTime() - daysBefore * 864e5; const d = new RD(t); d.setUTCHours(0, 0, 0, 0); const dow = (d.getUTCDay() + 6) % 7; return d.getTime() - dow * 864e5; };
      const groups = {}; cases.forEach((c) => { const k = wk(c.saleDate); (groups[k] = groups[k] || []).push(c); });
      const rows = [];
      for (const k of Object.keys(groups).sort()) {
        const C = +k;
        class FD extends RD { constructor(...a) { if (a.length === 0) super(C); else super(...a); } static now() { return C; } }
        try {
          window.Date = FD;
          const list = [];
          region.forEach((ap) => { const tr = ap.__ot.filter((t) => new RD(t.year, t.month - 1, t.day).getTime() < C); if (tr.length) list.push(Object.assign({}, ap, { trades: tr, latest: tr[0] })); });
          allAptList = list; buildAptMatchIndex();
          if (rentFull) rentCacheByLawd[lawd] = rentFull.filter((r) => { const ds = String(r.deal_date || ''); return ds.length < 8 || new RD(+ds.slice(0, 4), +ds.slice(4, 6) - 1, +ds.slice(6, 8)).getTime() < C; });
          auctionWonEstCache = {}; regionPpmIdxCache = {}; try { calcPriceGrades(); } catch (e) {}
          groups[k].forEach((c) => {
            const ap = list.find((x) => x.dong === c.dong && String(x.bunji) === String(c.bunji)), l = (ap && ap.latest) || {};
            const a2 = { id: 'asofc_' + c.id, propType: 'apt', addr: c.addrJibun, dong: c.dong, bunji: c.bunji, name: (ap && ap.name) || c.buildingName || '', pyung: c.areaM2 / 3.305785, floor: c.floor, lat: c.lat, lon: c.lon,
              bCode: lawd + '10100', bidDate: c.saleDate, minBid: String(Math.round((c.minBidPrice || 0) / 10000)), appraisal: String(Math.round((c.appraisalPrice || 0) / 10000)), buildYear: parseInt(l.build_year) || null };
            let row = null, err = null; try { row = computeBidBoardRow(a2); } catch (e) { err = String(e.message || e).slice(0, 80); }
            rows.push({ id: c.id, lawd, cutoff: new RD(C).toISOString().slice(0, 10), sale: row && (row.saleApp != null ? row.saleApp : row.sale), stk: row && row.saleStack ? row.sale : null, wb: row && row.wbBase ? row.wbBase.est : null, wbRule: row && row.wbBase ? row.wbBase.rule : null, by: row && (row.saleSimBy || ''), n6: row && row.ownStats ? row.ownStats.n6 : null, err });
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
      return rows;
    }
  };
})();
