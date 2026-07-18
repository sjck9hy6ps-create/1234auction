/* ════════════════════════════════════
   경매정보지(탱크옥션 등) 텍스트/캡처 이미지 → 구조화된 JSON 추출
   - 클라이언트가 경매 상세페이지에서 복사한 텍스트를 그대로 넘기거나,
     복사가 막혀 있는 페이지는 화면 캡처 이미지(여러 장 가능)를 넘기면
     Gemini API로 필수 항목들을 뽑아서 JSON으로 돌려줍니다. 텍스트와 이미지를
     동시에 보낼 수도 있습니다(둘 다 참고해서 추출).
   - 텍스트/이미지에 없는 값은 null로 두도록 프롬프트에 명시 (추측 금지)
   ⚠️ 예전엔 스키마 전체(60개+ 필드)를 한 번의 Gemini 호출로 처리했는데,
      Hobby 플랜의 maxDuration 상한(60초)보다 응답이 오래 걸려 타임아웃이 잦았음
      (같은 물건도 매번 성공/실패가 갈릴 정도로 시간이 아슬아슬했음).
      그래서 스키마를 "물건·가격·임차인" / "건축물·등기" 두 그룹으로 나눠
      Promise.all로 동시에 호출 → 전체 소요시간이 "둘의 합"이 아니라
      "더 오래 걸리는 쪽 하나" 수준으로 줄어들도록 함.
════════════════════════════════════ */
const GEMINI_MODEL = 'gemini-3.5-flash';
// Vercel 함수 자체의 실행 제한 시간을 늘림 (기본값은 너무 짧아서, 스키마가 큰 요청은
// Gemini 응답이 오기 전에 함수가 먼저 죽어버릴 수 있음). Hobby 플랜에서도 60초까지 가능.
export const maxDuration = 60;
// 캡처 이미지(여러 장)를 첨부하면 base64 페이로드가 커질 수 있어 기본 바디 제한을 올려둠
// (parse-registry.js의 PDF 업로드와 동일한 패턴).
export const config = {
  api: { bodyParser: { sizeLimit: '12mb' } },
};

// ── 스키마 A: 물건 기본정보 / 가격 / 임차인 / 매각통계 ──
const SCHEMA_A = {
  type: 'OBJECT',
  properties: {
    caseNo: { type: 'STRING' },
    court: { type: 'STRING' },
    courtTel: { type: 'STRING' },
    propertyType: { type: 'STRING' },
    auctionType: { type: 'STRING' },
    decisionDate: { type: 'STRING' },
    progressDays: { type: 'INTEGER' },
    distributionDeadline: { type: 'STRING' },
    isFirstProceeding: { type: 'BOOLEAN' },
    addrJibun: { type: 'STRING' },
    addrRoad: { type: 'STRING' },
    dong: { type: 'STRING' },
    bunji: { type: 'STRING' },
    // 아파트 단지 내 건물 동번호 (예: "101동"). 단지명(buildingDongName)과는 별도 필드.
    aptDong: { type: 'STRING' },
    roadName: { type: 'STRING' },
    roadMainNum: { type: 'INTEGER' },
    roadSubNum: { type: 'INTEGER' },
    unitFloor: { type: 'INTEGER' },
    unitNo: { type: 'STRING' },
    disposalMethod: { type: 'STRING' },
    specialConditions: { type: 'STRING' },
    siteRightsArea: { type: 'STRING' },
    officialPriceCurrent: { type: 'STRING' },
    saleDate: { type: 'STRING' },
    rounds: {
      type: 'ARRAY',
      items: {
        type: 'OBJECT',
        properties: {
          round: { type: 'INTEGER' },
          date: { type: 'STRING' },
          minPrice: { type: 'NUMBER' },
          result: { type: 'STRING' },
        },
      },
    },
    viewsToday: { type: 'INTEGER' },
    viewsTotal: { type: 'INTEGER' },
    viewsAvg2w: { type: 'INTEGER' },
    appraisalPrice: { type: 'NUMBER' },
    minBidPrice: { type: 'NUMBER' },
    minBidRate: { type: 'NUMBER' },
    deposit: { type: 'NUMBER' },
    depositRate: { type: 'NUMBER' },
    owner: { type: 'STRING' },
    debtor: { type: 'STRING' },
    creditor: { type: 'STRING' },
    claimAmount: { type: 'NUMBER' },
    appraiser: { type: 'STRING' },
    priceDate: { type: 'STRING' },
    registrationDate: { type: 'STRING' },
    landArea: { type: 'STRING' },
    landPrice: { type: 'NUMBER' },
    buildingArea: { type: 'STRING' },
    buildingPrice: { type: 'NUMBER' },
    unitPricePerM2: { type: 'NUMBER' },
    unitPricePerPyung: { type: 'NUMBER' },
    priceRatioLandBuilding: { type: 'STRING' },
    locationDesc: { type: 'STRING' },
    tenantTerminationDate: { type: 'STRING' },
    tenantDistributionDeadline: { type: 'STRING' },
    tenantOccupants: {
      type: 'ARRAY',
      items: {
        type: 'OBJECT',
        properties: {
          name: { type: 'STRING' },
          occupancyPart: { type: 'STRING' },
          deposit: { type: 'NUMBER' },
          rent: { type: 'NUMBER' },
          hasStanding: { type: 'BOOLEAN' },
          moveInDate: { type: 'STRING' },
          fixedDate: { type: 'STRING' },
          distributionDate: { type: 'STRING' },
          note: { type: 'STRING' },
        },
      },
    },
    tenantNote: { type: 'STRING' },
    salesStats: {
      type: 'OBJECT',
      properties: {
        m1: { type: 'STRING' },
        m3: { type: 'STRING' },
        m6: { type: 'STRING' },
        m12: { type: 'STRING' },
      },
    },
    officialTrades: {
      type: 'ARRAY',
      items: {
        type: 'OBJECT',
        properties: {
          date: { type: 'STRING' },
          amount: { type: 'NUMBER' },
          area: { type: 'STRING' },
          floor: { type: 'STRING' },
        },
      },
    },
    officialPriceByYear: { type: 'STRING' },
  },
};

// ── 스키마 B: 건축물정보 / 등기 이력 / 권리분석(경매 교육자료 기반) ──
const SCHEMA_B = {
  type: 'OBJECT',
  properties: {
    registryTotalClaim: { type: 'NUMBER' },
    registryItems: {
      type: 'ARRAY',
      items: {
        type: 'OBJECT',
        properties: {
          date: { type: 'STRING' },
          type: { type: 'STRING' },
          holder: { type: 'STRING' },
          amount: { type: 'STRING' },
          note: { type: 'STRING' },
          extinguished: { type: 'BOOLEAN' },
          // ── 권리분석용 추가 필드 ──
          isBaseRight: { type: 'BOOLEAN' }, // 이 항목이 말소기준권리 그 자체인지
          willBeAssumed: { type: 'BOOLEAN' }, // 인수(true)/소멸(false), 본문에 명시된 경우만 채움
        },
      },
    },
    // ── 말소기준권리 (경매 권리분석의 출발점) ──
    baseRightType: { type: 'STRING' }, // 예: "근저당권", "가압류", "담보가등기", "임의경매개시결정"
    baseRightDate: { type: 'STRING' }, // YYYY-MM-DD
    baseRightHolder: { type: 'STRING' },
    // ── 특수권리(순위와 무관하게 매수인에게 인수될 수 있는 위험 권리) ──
    specialRights: {
      type: 'OBJECT',
      properties: {
        hasLien: { type: 'BOOLEAN' }, // 유치권 신고 여부
        lienNote: { type: 'STRING' },
        hasLegalSuperficies: { type: 'BOOLEAN' }, // 법정지상권 성립 여지
        legalSuperficiesNote: { type: 'STRING' },
        hasGraveRights: { type: 'BOOLEAN' }, // 분묘기지권
        graveRightsNote: { type: 'STRING' },
        isIllegalBuilding: { type: 'BOOLEAN' }, // 위반건축물 여부
        illegalBuildingNote: { type: 'STRING' },
      },
    },
    // ── 용도지역 / 농지취득자격증명 판단용 ──
    landCategory: { type: 'STRING' }, // 지목 (전/답/과수원/대/임야 등)
    zoningType: { type: 'STRING' }, // 용도지역 (제2종일반주거지역, 계획관리지역, 농림지역 등)
    farmlandCertRequired: { type: 'BOOLEAN' }, // 농지취득자격증명원 필요 여부
    registryStory: { type: 'STRING' },
    riskSummary: { type: 'STRING' },
    buildingDongName: { type: 'STRING' },
    buildingAddr: { type: 'STRING' },
    households: { type: 'INTEGER' },
    buildingLandArea: { type: 'STRING' },
    coverageRatio: { type: 'NUMBER' },
    buildingFootprint: { type: 'STRING' },
    floorAreaRatio: { type: 'NUMBER' },
    totalFloorArea: { type: 'STRING' },
    mainUse: { type: 'STRING' },
    permitDate: { type: 'STRING' },
    startDate: { type: 'STRING' },
    approvalDate: { type: 'STRING' },
    parking: { type: 'STRING' },
    floorsAbove: { type: 'INTEGER' },
    floorsBelow: { type: 'INTEGER' },
    elevator: { type: 'STRING' },
    floorDetails: {
      type: 'ARRAY',
      items: {
        type: 'OBJECT',
        properties: {
          floor: { type: 'STRING' },
          area: { type: 'STRING' },
          structure: { type: 'STRING' },
          use: { type: 'STRING' },
        },
      },
    },
  },
};

// 텍스트 붙여넣기와 캡처 이미지 첨부 양쪽에 공통으로 적용되는 안내문.
// 이미지가 여러 장이면 스크롤을 나눠서 캡처한 같은 페이지라는 점, 그리고 하단 "다른 물건" 목록을
// 무시해야 한다는 점은 텍스트든 이미지든 동일하게 중요해서 하나로 통일함.
const HEADER = `다음은 경매정보 사이트(탱크옥션 등)에서 가져온 물건 "상세페이지" 정보입니다.
아래에 텍스트가 붙어 있거나, 상세페이지를 캡처한 스크린샷 이미지가 첨부되어 있거나, 혹은 둘 다일 수 있습니다.
이미지가 여러 장이면 위에서 아래로 스크롤하며 나눠 캡처한 것으로, 이어붙이면 하나의 페이지입니다.
이 페이지에는 본문(이 물건 자체의 정보) 외에도 하단에 "인근물건자료", "인근진행정보", "인근매각사례",
"동일지번매각", "인근반경검색", "인근공매진행", "경매최근열람" 같은 섹션이 있는데, 여기 나열된 사건번호나
주소는 전부 이 물건과 무관한 "다른" 물건들입니다. 반드시 페이지 맨 위 제목 줄
(예: "경매 2025타경52046" 처럼 "경매"라는 단어 바로 뒤에 나오는 사건번호 하나)에 있는 정보만
이 물건의 정보로 사용하고, 하단 목록/사이드바에 나오는 다른 사건번호·주소는 절대 사용하지 마세요.
공통 규칙:
- 텍스트/이미지에 명시되지 않은 값은 null(배열은 빈 배열)로 두세요. 절대 추측하거나 지어내지 마세요.
- 금액은 원 단위 숫자로 변환하세요 (예: "1억 3,300만" → 133000000, "9,310,000" → 9310000).
- 날짜는 가능하면 YYYY-MM-DD 형식으로 변환하세요.
- 이미지가 첨부된 경우, 글자가 흐리거나 잘려서 정확히 읽기 어려운 값은 절대 추측하지 말고 null로 두세요.`;

function buildPrompt(rules, text) {
  let p = HEADER + '\n\n추가 규칙:' + rules;
  if (text && String(text).trim()) {
    p += `\n\n--- 붙여넣은 텍스트 시작 ---\n${text}\n--- 붙여넣은 텍스트 끝 ---`;
  }
  return p;
}

const PROMPT_A_RULES = `
- caseNo는 페이지 맨 위 제목에 있는 사건번호 단 하나만 쓰세요 (예: "2025타경52046"). 하단 관련물건 목록의 번호는 무시하세요.
- addrJibun은 이 물건의 지번주소만 담으세요. 반드시 "시/도 시/군/구 동 번지"까지만 담고,
  층수·호수·건물동번호는 절대 addrJibun에 포함하지 마세요.
  예: 소재지가 "경기도 안산시 상록구 본오동 718-12 2층202호"라면
  addrJibun은 "경기도 안산시 상록구 본오동 718-12" 까지만 (뒤의 "2층202호"는 제외).
  소재지가 "서울특별시 강남구 개포동 12 개포자이 101동 3층302호"라면
  addrJibun은 "서울특별시 강남구 개포동 12" 까지만 (뒤의 "개포자이 101동 3층302호"는 제외).
- dong(동)과 bunji(번지)는 addrJibun에서 "동"과 "번지" 부분만 따로 뽑으세요.
  예: "경기도 안산시 상록구 본오동 718-12" → dong: "본오동", bunji: "718-12"
  (시/도/구 이름이나 층수·호수·건물동번호는 dong·bunji에 포함하지 마세요. 번지에 "-"로 이어진 본번-부번은 그대로 유지하세요.)
- aptDong(아파트 동/건물번호)은 소재지에서 "101동", "가동" 같은 건물 구분 표시만 뽑으세요.
  연립다세대나 단독주택처럼 동 구분이 없으면 null로 두세요.
- roadName/roadMainNum/roadSubNum은 도로명주소(예: "경기 안산시 상록구 본원로 115")에서
  도로명("본원로")과 건물번호의 본번(115)·부번을 분리하세요. 부번이 없으면 roadSubNum은 null.
  도로명주소 자체가 없으면 세 필드 모두 null로 두고 절대 지어내지 마세요.
- 소재지 문자열(예: "경기도 안산시 상록구 본오동 830-16 3층302호")에서 "3층302호" 부분을 찾아
  unitFloor(숫자만, 예: 3)와 unitNo(호수 문자열 그대로, 예: "302호")로 분리하세요. 이런 표시가 없으면 둘 다 null.
- disposalMethod(처분방식, 예: "토지·건물 일괄매각")와 specialConditions(특수조건, 예: "임차권등기,대항력 있는 임차인,공시가 1억이하")는
  본문에 명시된 문구를 그대로 담으세요.
- siteRightsArea(대지권 면적)는 "대지권" 항목의 면적(㎡·평 둘 다 있으면 그대로, 예: "34.19㎡(10.34평)")을 담되,
  전체 토지면적이 아니라 이 물건에 배정된 지분(대지권) 면적만 담으세요.
- rounds(입찰 회차 이력)는 표에 나온 순서대로 모두 담으세요.
- officialTrades(국토부 실거래가)는 표에 나온 개별 거래를 모두 담으세요.
- salesStats는 "최근1개월/3개월/6개월/12개월" 각 구간의 평균감정가/평균매각가/평균매각가율/평균입찰인수/예상매각가를 한 문장으로 요약해서 m1/m3/m6/m12에 넣으세요.
- officialPriceByYear는 연도별 공시가격을 "2021년 8,790만 / 2022년 8,930만 / ..." 같은 한 줄 텍스트로 요약하세요.
- officialPriceCurrent는 그 중 가장 최근 연도/월 기준 공시가격 한 건만 "83,700,000원 (2025.01 기준)" 형식으로 뽑으세요.
- tenantOccupants(임차인 현황)는 표/목록에 나온 임차인을 한 명씩 객체로 나눠서 모두 담으세요.
  대항력 "있음"이면 hasStanding: true, "없음"이면 false, 언급이 없으면 null.
  전입/확정/배당요구 날짜는 각각 moveInDate/fixedDate/distributionDate에, "임차권등기자", "경매신청인" 같은
  표시는 note에 담으세요.`;

const PROMPT_B_RULES = `
- registryItems(건물등기)는 접수일 순서대로 모두 담으세요.
- registryStory: registryItems에 담긴 등기 이력(소유권이전, 근저당, 임차권, 경매개시 등)을 바탕으로,
  이 부동산이 언제 지어지고 소유자가 어떻게 바뀌었는지, 그때마다 어떤 금액이 오갔는지(매매가/채권금액/대출),
  그리고 어떤 권리가 왜 소멸되었는지를 시간 순서대로 3~6문장 정도의 자연스러운 한국어 이야기 문단으로 정리하세요.
  등기부에 없는 내용은 추측하지 말고, 알 수 있는 사실만 서술하세요. 등기 정보가 전혀 없으면 null.
- buildingDongName(아파트/건물 단지명)은 순수 단지명만 담으세요 (예: "래미안", "개포자이").
  "101동", "가동" 같은 건물 동번호는 절대 buildingDongName에 포함하지 마세요. 단지명 자체가 확인되지 않으면 "이름없음"으로 두세요.

── 권리분석 (경매 권리분석 교육자료 기준, 반드시 아래 규칙대로 판단) ──
- "말소기준권리"란 (근)저당권, (가)압류, 담보가등기, 강제경매개시결정등기, 임의경매개시결정등기,
  전세권(배당요구 또는 임의경매신청을 한 경우) 중 등기부에 접수일이 가장 빠른 권리 하나를 말합니다.
  본문에 "말소기준권리" 또는 "말소기준등기"라는 문구와 함께 특정 권리가 명시되어 있으면 그 값을 그대로
  baseRightType/baseRightDate/baseRightHolder에 채우세요. 그런 명시가 없다면 registryItems을 접수일 순으로
  살펴 위 6가지 유형 중 가장 빠른 것을 찾아 채우세요. 판단 근거가 전혀 없으면 세 필드 모두 null로 두세요.
- registryItems 각 항목의 isBaseRight는 그 항목이 위에서 정한 말소기준권리와 동일한 등기이면 true,
  아니면 false로 표시하세요.
- registryItems 각 항목의 willBeAssumed(매수인 인수 여부)는, 본문(등기부현황 표, 매각물건명세서, 주의사항 등)에
  "인수" 또는 "소멸"이라고 명시적으로 표기되어 있는 경우에만 그대로 true(인수)/false(소멸)로 옮기세요.
  본문에 명시적 표기가 없다면 절대로 스스로 인수/소멸을 판단하지 말고 null로 두세요
  (법률적 최종 판단은 사람이 직접 등기부를 보고 내려야 합니다).
- specialRights: 본문의 "주의사항", "특수조건", "매각물건명세서 비고" 등에 아래 단어가 언급되어 있는지 확인하세요.
  · 유치권 → hasLien, 관련 문구를 lienNote에 원문 그대로.
  · 법정지상권(또는 "관습법상 법정지상권", "토지 건물 소유자 상이") → hasLegalSuperficies, legalSuperficiesNote.
  · 분묘(분묘기지권) → hasGraveRights, graveRightsNote.
  · 위반건축물(또는 "무허가 증축", "불법 확장") → isIllegalBuilding, illegalBuildingNote.
  각 항목은 본문에 해당 단어가 나오면 true, "해당사항 없음"처럼 명시적으로 부인하면 false, 아예 언급이 없으면 null로 두세요.
  절대로 본문에 없는 내용을 추측해서 true/false로 채우지 마세요.
- landCategory(지목)는 표제부·토지대장에 나온 지목(전, 답, 과수원, 대, 임야, 잡종지 등)을 그대로 담으세요.
- zoningType(용도지역)은 본문의 "토지이용계획", "국토이용정보" 등에 표기된 용도지역명
  (예: "제2종일반주거지역", "계획관리지역", "농림지역", "자연녹지지역")을 그대로 담으세요. 언급이 없으면 null.
- farmlandCertRequired(농지취득자격증명원 필요 여부)는 landCategory가 농지(전/답/과수원 등)에 해당하면서
  zoningType이 녹지지역·관리지역·농림지역·자연환경보전지역 중 하나이면 true로, landCategory가 농지가 아니거나
  zoningType이 도시지역의 주거·상업·공업지역이면 false로 판단하세요. 지목이나 용도지역 정보가 부족해 판단할 수
  없으면 반드시 null로 두세요 (섣불리 추측 금지).`;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Gemini가 "high demand"/"overloaded"(구글 서버 혼잡, 503 UNAVAILABLE)로 거절하는 경우가
// 있는데, 대부분 몇 초 안에 풀리는 일시적 현상이라 1초 후 최대 2회까지 자동 재시도한다.
// (API 키 오류·잘못된 요청 같은 재시도해도 안 풀리는 오류는 즉시 그대로 던짐)
// imageParts: [{ inline_data: { mime_type, data } }, ...] - 캡처 이미지가 없으면 빈 배열.
async function callGemini(apiKey, promptText, schema, imageParts, attempt) {
  attempt = attempt || 1;
  imageParts = imageParts || [];
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${apiKey}`;
  const geminiRes = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      contents: [{ parts: [{ text: promptText }, ...imageParts] }],
      generationConfig: {
        responseMimeType: 'application/json',
        responseSchema: schema,
        thinkingConfig: { thinkingLevel: 'minimal' },
      },
    }),
    signal: AbortSignal.timeout(45000),
  });
  const data = await geminiRes.json();
  if (!geminiRes.ok) {
    const status = data.error?.status || '';
    const msg = data.error?.message || 'Gemini API 호출 실패';
    const isOverloaded = geminiRes.status === 503 || status === 'UNAVAILABLE'
      || /overloaded|high demand/i.test(msg);
    if (isOverloaded && attempt < 3) {
      await sleep(1000 * attempt);
      return callGemini(apiKey, promptText, schema, imageParts, attempt + 1);
    }
    throw new Error(msg);
  }
  const jsonText = data.candidates?.[0]?.content?.parts?.[0]?.text;
  if (!jsonText) {
    throw new Error('Gemini 응답에서 결과를 찾을 수 없습니다.');
  }
  return JSON.parse(jsonText);
}

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST only' });
  const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
  if (!GEMINI_API_KEY) {
    return res.status(500).json({ error: 'GEMINI_API_KEY 환경변수가 없습니다. Vercel 프로젝트 설정에 추가해 주세요.' });
  }
  const { text, images } = req.body || {};
  const hasText = text && String(text).trim();
  const hasImages = Array.isArray(images) && images.length > 0;
  if (!hasText && !hasImages) {
    return res.status(400).json({ error: '분석할 텍스트 또는 이미지가 없습니다.' });
  }

  const imageParts = hasImages
    ? images
        .filter((img) => img && img.data)
        .map((img) => ({ inline_data: { mime_type: img.mimeType || 'image/jpeg', data: img.data } }))
    : [];

  const promptA = buildPrompt(PROMPT_A_RULES, text);
  const promptB = buildPrompt(PROMPT_B_RULES, text);

  try {
    // 스키마를 둘로 나눠 동시에 호출 - 전체 소요시간이 "둘의 합"이 아니라
    // "더 오래 걸리는 쪽 하나" 수준으로 줄어듦 (Hobby 플랜 60초 제한 안에 들어오도록)
    const [resultA, resultB] = await Promise.all([
      callGemini(GEMINI_API_KEY, promptA, SCHEMA_A, imageParts),
      callGemini(GEMINI_API_KEY, promptB, SCHEMA_B, imageParts),
    ]);
    const merged = { ...resultA, ...resultB };
    return res.status(200).json({ detail: merged });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}
