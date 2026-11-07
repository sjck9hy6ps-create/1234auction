/* 빌라 앱 종단 검증 도구(2026-11-07): window.__vv. 실제 빌라 거래(2026년~)마다 '그 거래 30일 전까지의 자료만'으로 앱의 villaSaleEst가 낸 예상매도가를 돌려줌(정답 = 그 거래 실제가).
   villaSaleEst(a)는 a.bidDate−30일을 기준일로 쓰므로 bidDate에 거래일을 넣으면 시점이 맞고, 그 이후 거래는 자동으로 빠짐(자료를 되돌릴 필요 없음). */
(function () {
  window.__vv = {
    regions() {
      const set = {};
      auctionList.forEach((a) => { if (a.propType === 'villa' && !a.isBacktest && parseFloat(a.pyung) > 0) { const l = bidBoardLawdOf(a); if (l && /^(11|28|41)/.test(l)) set[l] = (set[l] || 0) + 1; } });
      return set;
    },
    async processRegion(lawd, fromYmd, cap) {
      const wasLoaded = !!dataCache[lawd];
      if (!wasLoaded) {
        const d = await fetchHouseDataCached(lawd);
        if (!d || d.error || !Array.isArray(d.apt)) throw new Error('지역 자료를 못 받음 ' + lawd);
        await ingestRegionHouseData(d, '', lawd);
      }
      const ents = allAptList.filter((ap) => ap.lawdCd === lawd && (ap.buildingType || 'apt') === 'villa');
      const subj = [];
      ents.forEach((ap) => (ap.trades || []).forEach((t) => {
        if (t.dealing_type === '직거래' || !(t.area >= 15 && t.area <= 150)) return;
        const ymd = t.year * 10000 + t.month * 100 + t.day; if (ymd < fromYmd) return;
        const p = parseInt(t.amount); if (!p) return;
        subj.push({ ap, t, ymd, p });
      }));
      subj.sort((x, y) => x.ymd - y.ymd || x.p - y.p);
      const step = Math.max(1, Math.ceil(subj.length / cap)), pick = subj.filter((_, i) => i % step === 0);
      const rows = [];
      pick.forEach((s, k) => {
        const l = s.ap.latest || {}, dong = s.ap.dong || l.dong || s.t.dong, bunji = l.bunji || s.ap.bunji || s.t.bunji || '';
        const ds = String(s.ymd), a = { id: 'vasof_' + lawd + '_' + k, addr: dong + ' ' + bunji, dong, bunji, name: l.name || '', pyung: s.t.area / 3.305785, floor: s.t.floor, buildYear: parseInt(s.t.build_year) || null,
          bidDate: ds.slice(0, 4) + '-' + ds.slice(4, 6) + '-' + ds.slice(6, 8), _lawd: lawd, propType: 'villa' };
        let ve = null, err = null; try { ve = villaSaleEst(a); } catch (e) { err = String(e.message || e).slice(0, 80); }
        rows.push({ lawd, dong, bunji, d: s.ymd, area: s.t.area, floor: s.t.floor, by: parseInt(s.t.build_year) || null, price: s.p, app: ve ? ve.est : null, lvl: ve ? ve.lvl : null, n1: ve ? ve.n1 : null, n2: ve ? ve.n2 : null, bs: ve ? !!ve.bs : null, err });
      });
      if (!wasLoaded) {
        delete dataCache[lawd]; delete rentCacheByLawd[lawd]; try { mergedLawdCds.delete(lawd); } catch (e) {}
        try { const vi = lawdCdVisitOrder.indexOf(lawd); if (vi !== -1) lawdCdVisitOrder.splice(vi, 1); } catch (e) {}
        try { rebuildMergedLists(); } catch (e) {}
      }
      return { rows, eligible: subj.length };
    }
  };
})();
