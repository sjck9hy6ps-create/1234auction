/* ── DB rows → apt 그룹 ── */
function groupDBRows(rows, sigungu, lawdCd) {
  const aptMap = {};
  if (!rows || !Array.isArray(rows)) return [];

  rows.forEach(function(row) {
    const name = (row.danji || '').trim();
    if (!name) return;

    const road = (row.road_name || '').trim();
    const key  = name + '||' + road;

    if (!aptMap[key]) {
      aptMap[key] = {
        trades: [],
        lat: row.lat || null,   // ← 첫 row의 좌표 저장
        lon: row.lon || null,
      };
    }

    // 좌표가 없다가 생기면 업데이트
    if (!aptMap[key].lat && row.lat) {
      aptMap[key].lat = row.lat;
      aptMap[key].lon = row.lon;
    }

    aptMap[key].trades.push({
      year:       parseInt(String(row.deal_date).slice(0, 4)) || 0,
      month:      parseInt(String(row.deal_date).slice(4, 6)) || 0,
      day:        parseInt(String(row.deal_date).slice(6, 8)) || 0,
      amount:     String(row.price || 0),
      area:       Number(row.size)       || 0,
      floor:      String(row.floor       || '-'),
      name:       name,
      road_name:  road,
      region:     row.region             || sigungu,
      bunji:      row.bunji              || '',
      build_year: String(row.build_year  || ''),
      buildingType: 'apt',
      houseType:  'apt',
      source:     row.source             || 'db',
      searchAddr: (row.region || sigungu) + ' ' + road,
    });
  });

  return Object.keys(aptMap).map(function(key) {
    const entry  = aptMap[key];
    const trades = entry.trades;
    trades.sort(function(a, b) {
      return (b.year*10000 + b.month*100 + b.day) - (a.year*10000 + a.month*100 + a.day);
    });
    return {
      latest:        trades[0],
      trades:        trades,
      lawdCd:        lawdCd,
      buildingType:  'apt',
      // ← DB 좌표를 apt 객체에 보존
      lat:           entry.lat,
      lon:           entry.lon,
      grade:         null,
      ppp:           0,
      indicators:    null,
      investScore:   null,
      disqualified:  false,
      dqReason:      '',
      scoreBreakdown:{},
      hasNewHigh:    false,
      newHighPyungs: [],
      count3M:    trades.filter(function(t) { return tradeDate(t) >= threeMonAgo; }).length,
      count3MTo1Y: trades.filter(function(t) {
        const d = tradeDate(t); return d < threeMonAgo && d >= oneYearAgo;
      }).length,
    };
  });
}

/* ── placeMarkers: DB 좌표 있으면 geocoding 스킵 ── */
function placeMarkers(aptList) {
  const centerLat = map.getCenter().getLat();
  const centerLon = map.getCenter().getLng();
  let idx = 0;

  function runBatch() {
    if (idx >= aptList.length) return;
    const apt  = aptList[idx++];
    const l    = apt.latest || {};
    const name = (l.name || '').trim();
    const road = (l.road_name || '').trim();
    const cacheKey = (name + '|' + road).toLowerCase();

    // ── ① DB 좌표 있으면 즉시 마커 ──
    if (apt.lat && apt.lon) {
      coordCache[cacheKey] = { lat: apt.lat, lon: apt.lon };
      if (getDistance(centerLat, centerLon, apt.lat, apt.lon) <= 15000) {
        createMarker(apt.lat, apt.lon, apt);
      }
      setTimeout(runBatch, 10);  // 빠르게 처리
      return;
    }

    // ── ② 캐시 있으면 사용 ──
    if (coordCache[cacheKey]) {
      createMarker(coordCache[cacheKey].lat, coordCache[cacheKey].lon, apt);
      setTimeout(runBatch, 10);
      return;
    }

    // ── ③ geocoding (실시간 데이터 등 좌표 없는 경우) ──
    const region     = (l.region || lastSigungu).trim();
    const candidates = [];
    if (region && name) candidates.push(region + ' ' + name);
    if (region && road) candidates.push(region + ' ' + road);
    if (name) candidates.push(name);
    if (road) candidates.push(road);

    tryStepGeocode(candidates, function(lat, lon) {
      if (lat && lon) {
        coordCache[cacheKey] = { lat: lat, lon: lon };
        if (getDistance(centerLat, centerLon, lat, lon) <= 15000) {
          createMarker(lat, lon, apt);
        }
      }
      setTimeout(runBatch, 80);
    });
  }

  runBatch();
}
