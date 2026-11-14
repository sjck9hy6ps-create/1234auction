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
      // 좌표 없는 사례는 주소만으로 지역코드를 정함(2026-11-08): ①시군구 표기가 한 코드뿐이면 그 코드 ②아니면 시군구+구까지 쓴 표기 ③그래도 갈리면 법정동명
      const chain = (addr) => { const t = String(addr || '').trim().split(/\s+/); let k = labelOf(addr); for (let i = 2; i < t.length && /[시군구]$/.test(t[i]); i++) k += ' ' + t[i]; return k; };
      const mk = (fn) => { const m = {}; auctionList.forEach((a) => { if (a.propType === 'apt' && a.bCode) { const k = fn(a); (m[k] = m[k] || new Set()).add(String(a.bCode).slice(0, 5)); } }); return m; };
      const u1 = mk((a) => labelOf(a.addr)), u2 = mk((a) => chain(a.addr)), u3 = mk((a) => chain(a.addr) + '|' + (a.dong || ''));
      const pick = (m, k) => { const u = m[k]; return u && u.size === 1 ? [...u][0] : null; };
      // ④ 좌표 있는 사례가 같은 시군구+법정동에서 하나의 코드로만 연결되면 그 코드(경매물건이 없는 동 보완)
      const u4 = {};
      cases.forEach((c) => { if (c.lat && c.lon && c.dong) { const L = by[labelOf(c.addrJibun)]; if (!L) return; let best = null, bd = 1e9; for (const p of L) { const d = (p.lat - c.lat) ** 2 + (p.lon - c.lon) ** 2; if (d < bd) { bd = d; best = p.l; } } if (best) { const k = chain(c.addrJibun) + '|' + c.dong; (u4[k] = u4[k] || new Set()).add(best); } } });
      const out = {};
      cases.forEach((c) => {
        if (!c.lat || !c.lon) { const l = pick(u1, labelOf(c.addrJibun)) || pick(u2, chain(c.addrJibun)) || pick(u3, chain(c.addrJibun) + '|' + (c.dong || '')) || pick(u4, chain(c.addrJibun) + '|' + (c.dong || '')); if (l) (out[l] = out[l] || []).push(c.id); return; }
        const L = by[labelOf(c.addrJibun)]; if (!L) return;
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
            // 🎯 3개 가격 채점용(2026-11-08): 낙찰 뒤 6개월 같은 단지·평형(±3㎡) 시장 실거래 중위값(정답), 실제 낙찰가, 예상 낙찰가·추천가·낙찰 가능성
            let mkt = null, mktN = 0;
            try {
              const s0 = new RD(c.saleDate + 'T00:00:00+09:00').getTime(), s1 = s0 + 183 * 864e5;
              const ap0 = (region.find((x) => x.latest && x.latest.dong === c.dong && String(x.latest.bunji) === String(c.bunji))) || null;   // 단지 객체엔 동·번지가 latest 안에만 있음
              if (ap0) { const am = (ap0.__ot || []).filter((t) => Math.abs((+t.area || 0) - c.areaM2) <= 3 && !t.cancelled).map((t) => ({ ms: new RD(t.year, t.month - 1, t.day).getTime(), p: parseInt(String(t.amount).replace(/,/g, ''), 10) })).filter((t) => t.ms >= s0 && t.ms <= s1 && t.p > 0).map((t) => t.p).sort((x, y) => x - y); mktN = am.length; if (am.length) mkt = am.length % 2 ? am[(am.length - 1) / 2] : (am[am.length / 2 - 1] + am[am.length / 2]) / 2; }
            } catch (e) {}
            const w = row && row.winbid;
            rows.push({ id: c.id, saleDate: c.saleDate, act: Math.round((c.finalBidPrice || 0) / 1e4), minB: row ? row.minBid : null, fails: row ? row.fails : null, mkt, mktN, wbP: w ? w.price : null, wbPred: w ? w.pred : null, wbEst: w ? w.est : null, rec: row ? row.recBid : null, stkRaw: row && row.saleStack ? Math.round(row.sale / (1 + (row.saleStack.corr || 0))) : null, corr: row && row.saleStack ? (row.saleStack.corr || 0) : null, margin: row ? row.margin : null, marginRaw: row ? (row.pick && row.pick.ev && row.pick.ev.netRaw != null ? row.pick.ev.netRaw : row.margin) : null, shift: row && row.pick && row.pick.ev ? row.pick.ev.shift : null, recAggr: row ? row.recAggr : null, verdict: row ? row.verdict : null, nd: row && row.verdict === 'nodata' ? (row.reasons || []).slice(0, 2).join(' | ') : null, ndLoaded: row ? !!row.loaded : null, ndLat: !!(c.lat && c.lon), ndSale: row ? !!row.sale : null, ndMin: row ? !!row.minBid : null, probRec: w ? w.probRec : null, probRaw: w ? w.probRecRaw : null, saleFinal: row ? row.sale : null, lawd, cutoff: new RD(C).toISOString().slice(0, 10), sale: row && (row.saleApp != null ? row.saleApp : row.sale), stk: row && row.saleStack ? row.sale : null, wb: row && row.wbBase ? row.wbBase.est : null, wbRule: row && row.wbBase ? row.wbBase.rule : null, by: row && (row.saleSimBy || ''), n6: row && row.ownStats ? row.ownStats.n6 : null, go: !!(row && row.visit && row.visit.go), err });
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
