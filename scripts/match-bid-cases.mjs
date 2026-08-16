/* ════════════════════════════════════
   낙찰사례 - 매도사례 자동매칭 (주기적 실행 스크립트, 2026-08 신규)
   지금까지는 앱 화면의 "🔍 매도사례 매칭"/"🔄 실패건 재시도" 버튼을 사람이 직접
   눌러야만 실행됐음. 낙찰 후 실제 매도까지 보통 3~4개월씩 걸리고, 그 사이 계속
   새 실거래가 등록되므로 "예전엔 매도사례가 없었지만 지금은 있을 수 있는" 건들이
   시간이 지날수록 늘어남 - 이 스크립트는 그 재조회를 사람 개입 없이 주기적으로
   대신 해줌.

   ⚠️ 마진(estMargin/estRoi/estTotalCost) 계산은 여기서 하지 않음 - 취득세/등기비/
   명도비/중개수수료 등 세금 로직은 index.html에만 있고(계속 개정되는 세율을
   한 곳에서만 관리하기 위해 일부러 그렇게 둠), 이 스크립트에 그대로 복사하면
   나중에 index.html 세율이 바뀔 때마다 여기도 같이 고쳐야 해서 둘이 어긋날
   위험이 생김. 대신 이 스크립트는 resaleMatch(매도일자·금액 등)까지만 채워
   저장하고, index.html이 앱을 열 때 resaleMatch는 있는데 estMargin이 비어있는
   건을 발견하면 그 자리에서 즉시(외부 API 호출 없이 순수 계산만) 마진을 채워
   다시 저장함 (autoFillMissingBidCaseMargins 참고) - 세금 로직은 항상 한 곳
   (index.html)에서만 관리됨.

   - index.html의 scoreResaleCandidate/matchResaleForBidCase/toDateNum과 동일한
     매칭 로직을 그대로 이식했고, 브라우저 전용 kakao.maps.services.Geocoder
     호출만 이미 다른 웜업 스크립트들이 쓰는 카카오 REST API(KAKAO_REST_API_KEY,
     새 키 불필요·기존 키 재사용)로 교체했음.
   - 카카오 API 일일 할당량 초과(429 반복 또는 400+code:-10)를 감지하면 남은
     대상을 헛되이 호출하지 않고 즉시 중단함(warmup-locations.mjs와 동일 패턴).
   - 실행당 처리 상한(MAX_BIDCASE_MATCH_PER_RUN)을 둬서, 낙찰사례가 한꺼번에
     많이 밀려도 카카오/국토부 API 하루 할당량을 이 스크립트가 혼자 다 쓰지
     않도록 함 - 상한에 걸려 못 끝낸 나머지는 다음 실행(다음 주기)에 이어서 처리됨.
════════════════════════════════════ */
const KAKAO_REST_KEY = process.env.KAKAO_REST_API_KEY?.trim();
const SITE_URL = (process.env.SITE_URL?.trim()) || 'https://1234auction.vercel.app';
const DELAY_MS = 400; // 카카오 REST 호출 사이 간격 (레이트리밋 안전 마진)
const MAX_PER_RUN = parseInt(process.env.MAX_BIDCASE_MATCH_PER_RUN || '120', 10);
const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ── 카카오 API 일일 할당량 초과 감지 (warmup-locations.mjs와 동일 패턴) ── */
let consecutive429 = 0;
const MAX_CONSECUTIVE_429 = 5;
let quotaExhausted = false;
async function kakaoFetch(url) {
  if (quotaExhausted) return null;
  let res;
  try {
    res = await fetch(url, { headers: { Authorization: `KakaoAK ${KAKAO_REST_KEY}` } });
  } catch (e) {
    console.error('❌ 카카오 API 네트워크 오류:', e.message);
    return null;
  }
  if (res.status === 429) {
    consecutive429++;
    console.error(`⚠️  카카오 API 호출 제한(429) 감지 (연속 ${consecutive429}회)`);
    if (consecutive429 >= MAX_CONSECUTIVE_429 && !quotaExhausted) stopForQuota('호출 제한(429)이 계속 걸림');
    return null;
  }
  if (res.status === 400) {
    let body = null;
    try { body = await res.json(); } catch (e) { /* ignore */ }
    if (body && (body.code === -10 || /API limit has been exceeded/i.test(body.message || ''))) {
      stopForQuota('일일 호출 할당량 초과 (code -10)');
      return null;
    }
    return null;
  }
  consecutive429 = 0;
  if (!res.ok) return null;
  try { return await res.json(); } catch (e) { return null; }
}
function stopForQuota(reason) {
  if (quotaExhausted) return;
  quotaExhausted = true;
  console.error(`\n🛑 ${reason} → 여기서 중단합니다. 이미 처리된 건은 저장되어 있으니, 할당량이 초기화된 뒤(보통 자정) 다음 실행에서 이어집니다.\n`);
}
async function kakaoAddressSearch(query) {
  const url = `https://dapi.kakao.com/v2/local/search/address.json?query=${encodeURIComponent(query)}`;
  const json = await kakaoFetch(url);
  const doc = json?.documents?.[0];
  if (!doc) return null;
  return { lat: parseFloat(doc.y), lon: parseFloat(doc.x) };
}
async function kakaoCoordToLawdCd(lat, lon) {
  const url = `https://dapi.kakao.com/v2/local/geo/coord2regioncode.json?x=${lon}&y=${lat}`;
  const json = await kakaoFetch(url);
  const b = (json?.documents || []).find(d => d.region_type === 'B');
  if (!b || !b.code || b.code.length < 10) return null;
  return b.code.slice(0, 5);
}

/* ── 아래 네 함수는 index.html의 동명 함수와 완전히 동일한 로직 (DOM/kakao SDK
   의존 없이 순수 계산만 하므로 그대로 이식 가능함) ── */
function stripVillaDongSuffix(name) {
  var n = String(name || '').trim();
  var m = n.match(/^(.+?)[\s]*((?:\d{1,4})|(?:[가나다라마바사아자차카타파하]{1,2})|(?:[A-Za-z](?:[.,·]?[A-Za-z]){0,3}))동$/);
  if (!m) return n;
  var base = m[1].trim();
  return base.length >= 2 ? base : n;
}
function normalizeBunjiStr(s) {
  return String(s || '').trim().replace(/[‐－ㅡ]/g, '-')
    .split('-').map(function (part) { return part.replace(/^0+(?=\d)/, ''); }).join('-');
}
function toDateNum(s) {
  if (!s) return null;
  var digits = String(s).replace(/[^0-9]/g, '');
  if (digits.length < 8) return null;
  return parseInt(digits.slice(0, 8), 10);
}
function guessPropTypeFromCase(c) {
  var t = (c.propertyType || '').trim();
  if (t.indexOf('아파트') !== -1) return 'apt';
  if (t.indexOf('오피스텔') !== -1) return 'officetel';
  if (t.indexOf('상가') !== -1 || t.indexOf('토지') !== -1) return 'other';
  return 'villa';
}
function scoreResaleCandidate(c, row, areaTolerance) {
  var rowName = (row.danji || '').trim();
  var rowNameBase = stripVillaDongSuffix(rowName);
  var buildingNameBase = stripVillaDongSuffix(c.buildingName || '');
  var nameExact = !!(c.buildingName && rowName && (rowName === c.buildingName || (buildingNameBase && rowNameBase && rowNameBase === buildingNameBase)));
  var bunjiExact = !!(c.dong && c.bunji && row.dong === c.dong && normalizeBunjiStr(row.bunji) === normalizeBunjiStr(c.bunji));
  var nameContains = !!(c.buildingName && rowName && c.dong && row.dong === c.dong
    && c.buildingName.length >= 2 && rowName.length >= 2
    && (rowName.indexOf(c.buildingName) !== -1 || c.buildingName.indexOf(rowName) !== -1));
  if (!nameExact && !bunjiExact && !nameContains) return null;
  var floorApprox = false;
  if (c.floor !== null && c.floor !== undefined) {
    var rowFloor = parseInt(row.floor);
    if (!Number.isFinite(rowFloor)) return null;
    if (rowFloor !== c.floor) {
      if (Math.abs(rowFloor - c.floor) > 1) return null;
      floorApprox = true;
    }
  }
  if (c.areaM2) {
    var rowArea = Number(row.size) || 0;
    if (!rowArea || Math.abs(rowArea - c.areaM2) > areaTolerance) return null;
  }
  var approx = !nameExact && !bunjiExact;
  if (floorApprox) approx = true;
  var buildingScore = nameExact ? 0 : (bunjiExact ? 1 : 2);
  return { row: row, floorApprox: floorApprox, approx: approx, score: buildingScore + (floorApprox ? 0.5 : 0) };
}
/* index.html의 matchResaleForBidCase와 동일하되, 지오코딩만 카카오 REST 호출로 교체 */
async function matchResaleForBidCase(c) {
  if (!c.addrJibun) return { matched: false, reason: '주소 정보 없음' };
  const geo = await kakaoAddressSearch(c.addrJibun);
  if (quotaExhausted) return { matched: false, reason: '할당량 초과로 중단' };
  if (!geo) return { matched: false, reason: '주소를 좌표로 찾지 못함' };
  await sleep(DELAY_MS);
  const lawdCd = await kakaoCoordToLawdCd(geo.lat, geo.lon);
  if (quotaExhausted) return { matched: false, reason: '할당량 초과로 중단' };
  if (!lawdCd) return { matched: false, reason: '지역코드 확인 실패' };
  let dbData;
  try {
    const res = await fetch(`${SITE_URL}/api/get-house?lawdCd=${lawdCd}`, { signal: AbortSignal.timeout(30000) });
    dbData = await res.json();
  } catch (e) {
    return { matched: false, reason: '실거래 데이터 조회 실패: ' + e.message };
  }
  if (!dbData || dbData.error || !Array.isArray(dbData.apt)) return { matched: false, reason: '실거래 데이터 조회 실패' };
  const saleDateNum = toDateNum(c.saleDate);
  if (!saleDateNum) return { matched: false, reason: '매각기일 정보 없음' };
  const propType = guessPropTypeFromCase(c);
  const areaTolerance = propType === 'villa' ? 6 : 4;
  const scored = [];
  dbData.apt.forEach(function (row) {
    const dateNum = toDateNum(row.deal_date);
    if (!dateNum || dateNum < saleDateNum) return;
    const cand = scoreResaleCandidate(c, row, areaTolerance);
    if (cand) { cand.dateNum = dateNum; scored.push(cand); }
  });
  if (!scored.length) return { matched: false, reason: '낙찰일 이후 매도사례 없음' };
  scored.sort(function (a, b) { return (a.score - b.score) || (a.dateNum - b.dateNum); });
  const best = scored[0];
  const m = best.row;
  return { matched: true, date: m.deal_date, amount: Number(m.price) || 0, floor: m.floor, area: Number(m.size) || 0, approx: best.approx };
}

async function main() {
  if (!KAKAO_REST_KEY) {
    console.error('❌ KAKAO_REST_API_KEY 환경변수가 없습니다. GitHub 저장소 Secrets에 추가해 주세요.');
    process.exit(1);
  }
  console.log('⚖️  낙찰사례 매도사례 자동매칭 시작:', new Date().toISOString());
  const listRes = await fetch(`${SITE_URL}/api/auction?kind=bidCases`);
  const bidCaseList = await listRes.json();
  if (!Array.isArray(bidCaseList)) { console.error('❌ 낙찰사례 목록을 불러오지 못했습니다.'); process.exit(1); }

  // 앱의 "🔍 매도사례 매칭"(새 건)과 "🔄 실패건 재시도"(과거 실패건)를 한 조건으로 합침 -
  // resaleMatch가 없는 매각 완료 건은 새 건이든 예전에 실패했던 건이든 다시 시도할 가치가 있음
  // (시간이 지날수록 매도사례가 새로 등록될 수 있으므로).
  let targets = bidCaseList.filter(c => c.status === '매각' && c.finalBidPrice && !c.resaleMatch);
  console.log(`🎯 재시도 대상: ${targets.length}건 (실행당 상한 ${MAX_PER_RUN}건)`);
  if (targets.length > MAX_PER_RUN) {
    targets = targets.slice(0, MAX_PER_RUN);
    console.log(`   ⚠️ 상한 초과 - 이번 실행은 ${MAX_PER_RUN}건만 처리하고 나머지는 다음 실행에 이어집니다.`);
  }
  if (!targets.length) { console.log('처리할 대상이 없습니다.'); return; }

  let matchedCount = 0, failedCount = 0, savedFailCount = 0;
  for (let i = 0; i < targets.length; i++) {
    if (quotaExhausted) break;
    const c = targets[i];
    console.log(`(${i + 1}/${targets.length}) ${c.caseNo || '(사건번호 미상)'} ${c.addrJibun || ''}`);
    let result;
    try {
      result = await matchResaleForBidCase(c);
    } catch (e) {
      result = { matched: false, reason: e.message };
    }
    if (quotaExhausted) break; // 할당량 초과로 중단된 시도는 matchAttempted를 찍지 않고 다음 실행에 그대로 재시도
    c.matchAttempted = true;
    if (result.matched) {
      c.resaleMatch = { date: result.date, amount: result.amount, floor: result.floor, area: result.area, approx: result.approx || false };
      c.matchFailReason = null;
      // estMargin/estRoi/estTotalCost는 여기서 계산하지 않음 (파일 상단 설명 참고) -
      // index.html이 다음에 열릴 때 자동으로 채워짐.
      matchedCount++;
      console.log(`   ✅ 매칭됨: ${result.date} · ${result.amount}만원${result.approx ? ' (근사매칭)' : ''}`);
    } else {
      c.resaleMatch = null;
      c.matchFailReason = result.reason;
      failedCount++;
      console.log(`   ⏭️  매칭 안됨: ${result.reason}`);
    }
    try {
      await fetch(`${SITE_URL}/api/auction?kind=bidCases`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(c),
      });
    } catch (e) {
      savedFailCount++;
      console.error('   ❌ 저장 실패:', e.message);
    }
    await sleep(DELAY_MS);
  }
  console.log(`\n⚖️  매칭 종료: 매칭됨 ${matchedCount} / 매칭안됨 ${failedCount} / 저장실패 ${savedFailCount} (총 시도 ${matchedCount + failedCount})`);
}

main().catch(e => {
  console.error('💥 낙찰사례 매칭 스크립트 전체 실패:', e);
  process.exit(1);
});
