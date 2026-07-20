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
   ⚠️ 정확도/속도 개선 (2차):
      - temperature: 0 고정 → 같은 입력이면 항상 같은 결과가 나오도록 재현성을 높임.
      - Redis 캐싱 → 동일한 텍스트/이미지(해시 동일)를 다시 보내면 Gemini를 재호출하지
        않고 즉시 반환. 오타 수정 후 재시도하거나 같은 물건을 다시 붙여넣을 때 빠름.
      - 숫자 정합성 자동검증 → 최저가율/보증금율/㎡당단가처럼 다른 필드로부터 재계산 가능한
        값들을 서버에서 직접 계산해 AI가 준 값과 크게 다르면 warnings에 담아 화면에 경고.
   ⚠️ 타임아웃 재발 대응 (3차, 텍스트 1만자 내외에서도 "시간 내에 끝나지 못했습니다" 경고가
      자꾸 뜬다는 신고로 조사): 스키마 A(물건정보+가격+임차인+매각통계)와 B(건축물+등기+권리분석)
      두 덩어리로만 나눴을 때도, 각 덩어리 안에 배열형 필드(tenantOccupants, officialTrades,
      registryItems 등)가 많으면 응답 생성(출력 토큰)이 오래 걸려 52초를 넘기는 경우가 있었음.
      그래서 A를 다시 A1(물건 기본정보·가격, 배열은 짧은 rounds만)/A2(임차인·매각통계·실거래,
      가장 무거운 배열들)로, B를 B1(건축물정보)/B2(등기이력·권리분석, registryStory 서술형 포함)로
      나눠 4개 호출을 동시에 보냄 - 개별 호출당 만들어야 하는 출력이 줄어 지연이 짧아짐.
      동시에, 부가기능이던 "경량 스키마C 교차검증"(핵심필드 재추출 비교)은 호출 수를 4개에서
      5개로 늘리면 무료 티어의 분당 요청수(RPM) 한도에 더 빨리 걸릴 수 있어 제거함 - 매번
      성공하는 게 이중 검증보다 우선이라고 판단.
════════════════════════════════════ */
import crypto from 'crypto';

// ⚠️ 무료 티어 RPM 한도 때문에 gemini-2.5-flash(신규 사용자 접근 불가) → gemini-3.1-flash-lite
//    순으로 임시로 바꿔봤었는데, 완성도 우선 + 결제(빌링) 활성화로 방향을 정해서 원래의
//    최상위 플래그십 모델로 되돌림. 결제를 켜면 무료 티어의 RPM 제약 자체가 유료 티어 한도로
//    바뀌어서(사용량 기반 과금, Billing info 참고) 지금 겪은 "15~20초 후 재시도" 오류가 사실상
//    해소됨.
const GEMINI_MODEL = 'gemini-3.5-flash';
// Vercel 함수 자체의 실행 제한 시간을 늘림 (기본값은 너무 짧아서, 스키마가 큰 요청은
// Gemini 응답이 오기 전에 함수가 먼저 죽어버릴 수 있음). Hobby 플랜에서도 60초까지 가능.
export const maxDuration = 60;
// 캡처 이미지(여러 장)를 첨부하면 base64 페이로드가 커질 수 있어 기본 바디 제한을 올려둠
// (parse-registry.js의 PDF 업로드와 동일한 패턴).
export const config = {
  api: { bodyParser: { sizeLimit: '12mb' } },
};

// ── 스키마 A1: 물건 기본정보 / 가격 (배열은 짧은 rounds 하나뿐 - 상대적으로 가벼움) ──
const SCHEMA_A1 = {
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
    caseCautions: { type: 'STRING' },
    siteRightsArea: { type: 'STRING' },
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
  },
};

// ── 스키마 A2: 임차인 현황 / 매각통계 / 국토부 실거래 / 공시가격 (가장 무거운 배열들) ──
const SCHEMA_A2 = {
  type: 'OBJECT',
  properties: {
    officialPriceCurrent: { type: 'STRING' },
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

// ── 스키마 B1: 건축물정보(건축HUB 성격의 표제부/층별개요) ──
const SCHEMA_B1 = {
  type: 'OBJECT',
  properties: {
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
    // ── 용도지역 / 농지취득자격증명 판단용 ──
    landCategory: { type: 'STRING' }, // 지목 (전/답/과수원/대/임야 등)
    zoningType: { type: 'STRING' }, // 용도지역 (제2종일반주거지역, 계획관리지역, 농림지역 등)
    farmlandCertRequired: { type: 'BOOLEAN' }, // 농지취득자격증명원 필요 여부
  },
};

// ── 스키마 B2: 등기 이력 / 권리분석(경매 교육자료 기반) - registryStory 서술형이 있어 A1만큼 무거움 ──
const SCHEMA_B2 = {
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
    registryStory: { type: 'STRING' },
    riskSummary: { type: 'STRING' },
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

// 탱크옥션 등 경매정보지 상세페이지 하단에는 추출에 전혀 필요 없는 순수 UI/내비게이션성
// 문구(학교 목록 "교육환경", 등기소·세무서·주민센터 연락처 "행정기관", 지도/거리뷰 링크
// 모음, 면책 문구, 우측 메뉴 등)가 붙어 있는데, 물건에 따라 이 부분만 수천 자에 달해서
// Gemini가 응답을 만드는 데 걸리는 시간이 길어지고 45초 제한에 자꾸 걸리는 원인이 됨.
// 이런 문구가 시작되는 지점부터는 통째로 잘라내고, 그 앞의 실제로 필요한 내용(사건정보·
// 가격·임차인·등기·매각사례·건축물정보 등)만 Gemini에 보냄.
const TRAILING_NOISE_MARKERS = ['행정기관', '교육환경', '본 정보는 대법원 경매정보', '☰'];
function trimAuctionText(text) {
  if (!text) return text;
  let cutAt = -1;
  for (const marker of TRAILING_NOISE_MARKERS) {
    const idx = text.indexOf(marker);
    if (idx !== -1 && (cutAt === -1 || idx < cutAt)) cutAt = idx;
  }
  if (cutAt === -1) return text;
  return text.slice(0, cutAt).trim();
}

const PROMPT_A_RULES = `
- caseNo는 페이지 맨 위 제목에 있는 사건번호 단 하나만 쓰세요 (예: "2025타경52046"). 하단 관련물건 목록의 번호는 무시하세요.
- court(관할법원)와 courtTel(법원 전화번호)은 사건정보 영역에 "법원" 또는 "관할법원"이라는 이름으로 표시된 값을
  그대로 담으세요 (예: "수원지방법원 안산지원"처럼 본원+지원이 함께 표기되어 있으면 그대로 두세요).
  전화번호는 담당계 전화번호가 별도로 있으면 그것을, 없으면 법원 대표번호를 담으세요. 페이지에 보이지 않으면 null로 두세요.
- addrJibun은 이 물건의 지번주소만 담으세요. 반드시 "시/도 시/군/구 동 번지"까지만 담고,
  층수·호수·건물동번호는 절대 addrJibun에 포함하지 마세요.
  예: 소재지가 "경기도 안산시 상록구 본오동 718-12 2층202호"라면
  addrJibun은 "경기도 안산시 상록구 본오동 718-12" 까지만 (뒤의 "2층202호"는 제외).
  소재지가 "서울특별시 강남구 개포동 12 개포자이 101동 3층302호"라면
  addrJibun은 "서울특별시 강남구 개포동 12" 까지만 (뒤의 "개포자이 101동 3층302호"는 제외).
- dong(동)과 bunji(번지)는 addrJibun에서 "동"과 "번지" 부분만 따로 뽑으세요.
  예: "경기도 안산시 상록구 본오동 718-12" → dong: "본오동", bunji: "718-12"
  (시/도/구 이름이나 층수·호수·건물동번호는 dong·bunji에 포함하지 마세요. 번지에 "-"로 이어진 본번-부번은 그대로 유지하세요.)
- aptDong(아파트 동/건물번호)은 소재지에서 "101동", "가동"처럼 "동"으로 끝나는 건물 구분 표시만 뽑으세요.
  연립다세대나 단독주택처럼 동 구분이 없으면 반드시 null로 두세요.
  ⚠️ 절대로 "OOO호"(호수) 형태의 값을 aptDong에 넣지 마세요 - "동"이 아니라 "호"로 끝나는 값은 무조건
  unitNo(호수) 필드에만 들어가야 하고, aptDong은 그 경우 null이어야 합니다.
  예: "본오동 830-16 3층302호"에는 건물 동번호 표시가 없으므로 aptDong은 null, unitNo만 "302호".
- roadName/roadMainNum/roadSubNum은 도로명주소(예: "경기 안산시 상록구 본원로 115")에서
  도로명("본원로")과 건물번호의 본번(115)·부번을 분리하세요. 부번이 없으면 roadSubNum은 null.
  도로명주소 자체가 없으면 세 필드 모두 null로 두고 절대 지어내지 마세요.
- 소재지 문자열(예: "경기도 안산시 상록구 본오동 830-16 3층302호")에서 "3층302호" 부분을 찾아
  unitFloor(숫자만, 예: 3)와 unitNo(호수 문자열 그대로, 예: "302호")로 분리하세요. 이런 표시가 없으면 둘 다 null.
- disposalMethod(처분방식, 예: "토지·건물 일괄매각")와 specialConditions(특수조건, 예: "임차권등기,대항력 있는 임차인,공시가 1억이하")는
  본문에 명시된 문구를 그대로 담으세요.
- caseCautions(사건의 주의사항)는 사이트가 "주의사항"이라는 제목이나 별도 강조 박스/배지로 표시한 경고성
  문구(예: "본 물건은 재매각 물건입니다", "농지취득자격증명원 미제출시 보증금 미반환", "대항력 있는 임차인 있음",
  "최선순위 설정일자보다 대항요건을 먼저 갖춘 임차인 있음" 등)를 원문 그대로 담으세요.
  specialConditions와 내용이 겹칠 수 있지만, 페이지에 "주의사항"이라는 이름의 별도 섹션이 있으면 그 내용을 우선하세요.
  그런 별도 섹션이 없으면 null로 두세요.
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

// 429(RESOURCE_EXHAUSTED, 무료 티어 분당 요청수 초과) 응답에는 대개
// error.details[]에 google.rpc.RetryInfo 타입 항목이 있고, retryDelay가
// "12.589028474s" 같은 문자열로 들어있다. 있으면 그 시간만큼, 없으면 기본값을 기다린다.
function parseRetryDelayMs(errData) {
  const details = errData?.error?.details;
  if (!Array.isArray(details)) return null;
  const retryInfo = details.find((d) => typeof d['@type'] === 'string' && d['@type'].includes('RetryInfo'));
  const raw = retryInfo?.retryDelay;
  if (!raw) return null;
  const sec = parseFloat(String(raw).replace('s', ''));
  if (!isFinite(sec) || sec <= 0) return null;
  return Math.ceil(sec * 1000) + 500; // 약간의 여유를 더함
}

// Gemini가 "high demand"/"overloaded"(구글 서버 혼잡, 503 UNAVAILABLE)로 거절하는 경우가
// 있는데, 대부분 몇 초 안에 풀리는 일시적 현상이라 1초 후 최대 2회까지 자동 재시도한다.
// 무료 티어의 "분당 요청수(RPM)" 한도(429 RESOURCE_EXHAUSTED)에 걸린 경우도 대부분
// 짧게는 십수 초 안에 풀리는 일시적 현상이라, Gemini가 알려주는 재시도 대기시간만큼
// 기다렸다가 한 번 더 시도한다(과도한 대기로 Vercel 60초 제한을 넘지 않도록 1회만).
// (API 키 오류·잘못된 요청 같은 재시도해도 안 풀리는 오류는 즉시 그대로 던짐)
// imageParts: [{ inline_data: { mime_type, data } }, ...] - 캡처 이미지가 없으면 빈 배열.
// temperature: 기본 0(재현성 우선).
async function callGemini(apiKey, promptText, schema, imageParts, attempt, temperature) {
  attempt = attempt || 1;
  imageParts = imageParts || [];
  temperature = temperature === undefined || temperature === null ? 0 : temperature;
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${apiKey}`;
  let geminiRes;
  try {
    // Vercel Hobby maxDuration이 60초라, 여유(파싱·응답조립)를 좀 남기고 55초까지 기다림
    // (스키마를 4개로 더 쪼갠 이후에도 개별 호출이 예상보다 오래 걸리는 경우를 위한 마지막 여유분)
    geminiRes = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{ parts: [{ text: promptText }, ...imageParts] }],
        generationConfig: {
          responseMimeType: 'application/json',
          responseSchema: schema,
          // ⚠️ 3.x 계열은 thinkingBudget(토큰 수)이 아니라 thinkingLevel(단계형)로 사고 정도를
          //    조절함(2.5 계열의 thinkingBudget과 파라미터 자체가 다름 - 섞어 쓰면 무시되거나
          //    오류가 남). 'minimal'로 최대한 빠르게 응답하게 함 - 스키마가 출력 형식을 강제하고
          //    판단 규칙도 프롬프트에 구체적으로 적혀 있어 충분함.
          thinkingConfig: { thinkingLevel: 'minimal' },
          temperature,
        },
      }),
      signal: AbortSignal.timeout(55000),
    });
  } catch (e) {
    if (e.name === 'TimeoutError' || e.name === 'AbortError') {
      throw new Error('AI 분석이 시간 내에 끝나지 못했습니다. 페이지 내용이 너무 길 수 있으니(특히 하단 학교·행정기관·지도 링크 등은 빼고) 필요한 부분만 남겨서 다시 시도해 주세요. 방금 실패했다면 곧바로 재시도하지 말고 1분 정도 기다렸다가 다시 시도해 주세요(무료 API 분당 요청수 한도에 걸려 있을 수 있습니다).');
    }
    throw e;
  }
  const data = await geminiRes.json();
  if (!geminiRes.ok) {
    const status = data.error?.status || '';
    const msg = data.error?.message || 'Gemini API 호출 실패';
    const isOverloaded = geminiRes.status === 503 || status === 'UNAVAILABLE'
      || /overloaded|high demand/i.test(msg);
    const isQuotaExceeded = geminiRes.status === 429 || status === 'RESOURCE_EXHAUSTED';
    if (isOverloaded && attempt < 3) {
      await sleep(1000 * attempt);
      return callGemini(apiKey, promptText, schema, imageParts, attempt + 1, temperature);
    }
    if (isQuotaExceeded && attempt < 2) {
      const waitMs = parseRetryDelayMs(data) ?? 15000;
      await sleep(waitMs);
      return callGemini(apiKey, promptText, schema, imageParts, attempt + 1, temperature);
    }
    if (isQuotaExceeded) {
      throw new Error('AI 판독기 요청이 무료 사용량 한도(분당 요청수)에 잠시 걸렸습니다. 15~20초 후 다시 시도해 주세요.');
    }
    throw new Error(msg);
  }
  const jsonText = data.candidates?.[0]?.content?.parts?.[0]?.text;
  if (!jsonText) {
    throw new Error('Gemini 응답에서 결과를 찾을 수 없습니다.');
  }
  return JSON.parse(jsonText);
}

// ════════════════════════════════════
// Redis 캐싱 (Upstash) - get-house.js와 동일한 REST 호출 패턴
// 같은 텍스트/이미지(해시 동일)를 다시 보내면 Gemini를 다시 호출하지 않고 즉시 반환.
// TTL 24시간: 같은 물건 텍스트가 하루 안에 바뀔 일은 거의 없고, 사용자가 내용을
// 수정해서 다시 붙여넣으면 해시가 달라져 자연히 캐시가 무효화됨.
// ════════════════════════════════════
const REDIS_URL = process.env.UPSTASH_REDIS_URL;
const REDIS_TOKEN = process.env.UPSTASH_REDIS_TOKEN;
const CACHE_TTL_SECONDS = 24 * 60 * 60;

function computeCacheKey(trimmedText, imageParts) {
  const h = crypto.createHash('sha256');
  h.update(trimmedText || '');
  (imageParts || []).forEach((p) => {
    if (p?.inline_data?.data) h.update(p.inline_data.data);
  });
  return `auctionparse_${h.digest('hex')}`;
}

async function getCachedParseResult(key) {
  if (!REDIS_URL || !REDIS_TOKEN) return null;
  try {
    const r = await fetch(`${REDIS_URL}/get/${key}`, {
      headers: { Authorization: `Bearer ${REDIS_TOKEN}` },
      signal: AbortSignal.timeout(3000),
    });
    if (!r.ok) return null;
    const data = await r.json();
    if (!data || !data.result) return null;
    return JSON.parse(data.result);
  } catch (e) {
    console.error('parse-auction Redis 캐시 조회 실패:', e.message);
    return null;
  }
}

async function setCachedParseResult(key, payload) {
  if (!REDIS_URL || !REDIS_TOKEN) return;
  try {
    const r = await fetch(`${REDIS_URL}/set/${key}?EX=${CACHE_TTL_SECONDS}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${REDIS_TOKEN}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(3000),
    });
    if (!r.ok) {
      const errText = await r.text();
      console.error('parse-auction Redis 캐시 저장 실패:', errText);
    }
  } catch (e) {
    console.error('parse-auction Redis 캐시 저장 실패:', e.message);
  }
}

// ════════════════════════════════════
// 개발호재 검색 (재개발/재건축/신속통합기획 등) - mode: 'devNews'
// ⚠️ Hobby 플랜 12개 함수 한도 때문에 새 api 파일을 만들 수 없어 이 파일에 mode 분기로 얹음.
// ⚠️ 처음엔 Gemini의 google_search 그라운딩 도구로 구현했었는데, 무료 티어 API 키에서는
//    그라운딩 자체가 막혀 있어("quota exceeded") 결제 활성화 없이는 동작하지 않았음.
//    그래서 완전 무료인 네이버 뉴스검색 API(개발자센터에서 Client ID/Secret만 발급받으면
//    카드 등록 없이 사용 가능)로 교체함. Vercel에 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET
//    환경변수를 추가해야 동작함(https://developers.naver.com/apps/#/register 에서
//    "검색" API를 선택해 애플리케이션 등록 후 발급).
// ════════════════════════════════════
const DEV_NEWS_CACHE_TTL_SECONDS = 24 * 60 * 60; // 1일 - 뉴스는 감정가/최저가보다 훨씬 자주 갱신될 수 있어 AI추출 캐시보다 짧게
const NAVER_NEWS_ENDPOINT = 'https://openapi.naver.com/v1/search/news.json';

function computeDevNewsCacheKey(address) {
  const h = crypto.createHash('sha256');
  h.update(String(address || '').trim());
  return `devnews_${h.digest('hex')}`;
}

// 지번/도로명 주소 문자열에서 "동(읍/면/가/리)"과 "구(시/군)" 단위 지명만 뽑아냄.
// 번지(숫자로 시작하는 토큰)가 나오기 전까지의 토큰만 지명 후보로 보고, 뒤에서부터
// 훑으며 "동/읍/면/가/리"로 끝나는 첫 토큰을 dongName, "시/군/구"로 끝나는 첫 토큰을
// gunguName으로 삼음(단, "인천광역시"처럼 시/도 단위는 제외).
function parseAddressLocationParts(address) {
  const tokens = String(address || '').trim().split(/\s+/).filter(Boolean);
  const locTokens = [];
  for (let i = 0; i < tokens.length; i++) {
    if (/^\d/.test(tokens[i])) break; // "424-76" 같은 번지 시작 지점에서 중단
    locTokens.push(tokens[i]);
  }
  if (!locTokens.length) locTokens.push(...tokens.slice(0, 3));
  const isSido = (t) => /(특별시|광역시|특별자치시|특별자치도)$/.test(t);
  let dongName = null;
  let gunguName = null;
  for (let j = locTokens.length - 1; j >= 0; j--) {
    const t = locTokens[j];
    if (!dongName && /(동|읍|면|가|리)$/.test(t) && !isSido(t)) { dongName = t; continue; }
    if (!gunguName && /(시|군|구)$/.test(t) && !isSido(t)) { gunguName = t; }
  }
  return { dongName, gunguName };
}

function stripNaverHtml(s) {
  return String(s || '')
    .replace(/<[^>]+>/g, '')
    .replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&#39;/g, "'");
}

async function searchNaverNews(query, clientId, clientSecret) {
  const url = `${NAVER_NEWS_ENDPOINT}?query=${encodeURIComponent(query)}&display=10&sort=date`;
  const r = await fetch(url, {
    headers: { 'X-Naver-Client-Id': clientId, 'X-Naver-Client-Secret': clientSecret },
    signal: AbortSignal.timeout(8000),
  });
  if (!r.ok) {
    const errText = await r.text().catch(() => '');
    throw new Error(`네이버 뉴스검색 실패(${r.status}): ${errText || query}`);
  }
  const data = await r.json();
  return Array.isArray(data.items) ? data.items : [];
}

async function getCachedDevNews(key) {
  if (!REDIS_URL || !REDIS_TOKEN) return null;
  try {
    const r = await fetch(`${REDIS_URL}/get/${key}`, {
      headers: { Authorization: `Bearer ${REDIS_TOKEN}` },
      signal: AbortSignal.timeout(3000),
    });
    if (!r.ok) return null;
    const data = await r.json();
    if (!data || !data.result) return null;
    return JSON.parse(data.result);
  } catch (e) {
    console.error('devNews Redis 캐시 조회 실패:', e.message);
    return null;
  }
}

async function setCachedDevNews(key, payload) {
  if (!REDIS_URL || !REDIS_TOKEN) return;
  try {
    const r = await fetch(`${REDIS_URL}/set/${key}?EX=${DEV_NEWS_CACHE_TTL_SECONDS}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${REDIS_TOKEN}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(3000),
    });
    if (!r.ok) {
      const errText = await r.text();
      console.error('devNews Redis 캐시 저장 실패:', errText);
    }
  } catch (e) {
    console.error('devNews Redis 캐시 저장 실패:', e.message);
  }
}

async function handleDevNewsSearch(req, res) {
  const NAVER_CLIENT_ID = process.env.NAVER_CLIENT_ID;
  const NAVER_CLIENT_SECRET = process.env.NAVER_CLIENT_SECRET;
  if (!NAVER_CLIENT_ID || !NAVER_CLIENT_SECRET) {
    return res.status(500).json({
      error: 'NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 없습니다. '
        + 'https://developers.naver.com/apps/#/register 에서 "검색" API로 애플리케이션을 등록해 '
        + '발급받은 값을 Vercel 프로젝트 설정에 추가해 주세요.',
    });
  }
  const address = req.body && req.body.address ? String(req.body.address).trim() : '';
  if (!address) return res.status(400).json({ error: '주소가 필요합니다.' });
  const force = !!(req.body && req.body.force);
  const cacheKey = computeDevNewsCacheKey(address);
  if (!force) {
    const cached = await getCachedDevNews(cacheKey);
    if (cached) return res.status(200).json({ devNews: cached, cached: true });
  }
  const parts = parseAddressLocationParts(address);
  if (!parts.dongName && !parts.gunguName) {
    return res.status(400).json({ error: '주소에서 동/구 이름을 인식하지 못했습니다.' });
  }
  const gunguForBroaderQuery = parts.gunguName || parts.dongName;
  const queries = [];
  if (parts.dongName) {
    queries.push(parts.dongName + ' 재개발');
    queries.push(parts.dongName + ' 재건축');
  }
  queries.push(gunguForBroaderQuery + ' 신속통합기획');
  queries.push(gunguForBroaderQuery + ' 정비구역');

  try {
    const resultsPerQuery = await Promise.all(
      queries.map((q) => searchNaverNews(q, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET).catch((e) => {
        console.error('devNews 네이버 검색 실패:', q, e.message);
        return [];
      }))
    );
    const seen = new Set();
    let items = [];
    resultsPerQuery.forEach((list, idx) => {
      list.forEach((it) => {
        const link = it.originallink || it.link;
        if (!link || seen.has(link)) return;
        seen.add(link);
        let source = '';
        try { source = new URL(link).hostname.replace(/^www\./, ''); } catch (e) { /* ignore */ }
        items.push({
          title: stripNaverHtml(it.title),
          description: stripNaverHtml(it.description),
          link,
          pubDate: it.pubDate || null,
          source,
          matchedQuery: queries[idx],
        });
      });
    });
    items.sort((a, b) => {
      const ta = a.pubDate ? new Date(a.pubDate).getTime() : 0;
      const tb = b.pubDate ? new Date(b.pubDate).getTime() : 0;
      return tb - ta;
    });
    items = items.slice(0, 15);
    const payload = { items, fetchedAt: Date.now(), address, queries };
    setCachedDevNews(cacheKey, payload); // 응답을 늦추지 않도록 await 없이 fire-and-forget
    return res.status(200).json({ devNews: payload });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}

// ════════════════════════════════════
// 정확도 검증: (1) 숫자 정합성(다른 필드로부터 재계산), (2) 스키마C 교차검증
// 둘 다 "틀렸다"가 아니라 "확인이 필요하다"는 신호라서, 값을 고치지 않고 detail.warnings에
// 문자열로 담아 프론트에서 경고로만 보여줌 (최종 판단은 사람이 원문을 보고 함).
// ════════════════════════════════════
function extractLeadingNum(v) {
  if (v === null || v === undefined) return null;
  const m = String(v).replace(/,/g, '').match(/[\d.]+/);
  return m ? parseFloat(m[0]) : null;
}

function buildNumericWarnings(m) {
  const warnings = [];
  function pct(a, b) {
    return b ? (a / b) * 100 : null;
  }
  if (m.appraisalPrice && m.minBidPrice && m.minBidRate) {
    const computed = pct(m.minBidPrice, m.appraisalPrice);
    if (computed !== null && Math.abs(computed - m.minBidRate) > 3) {
      warnings.push(`최저가율(AI: ${m.minBidRate}%)이 감정가 대비 실제 계산값(${computed.toFixed(1)}%)과 차이가 큽니다. 감정가·최저가 금액을 확인해 주세요.`);
    }
  }
  if (m.minBidPrice && m.deposit && m.depositRate) {
    const computed = pct(m.deposit, m.minBidPrice);
    if (computed !== null && Math.abs(computed - m.depositRate) > 3) {
      warnings.push(`보증금율(AI: ${m.depositRate}%)이 최저가 대비 실제 계산값(${computed.toFixed(1)}%)과 차이가 큽니다. 보증금 금액을 확인해 주세요.`);
    }
  }
  const areaMatch = m.buildingArea ? String(m.buildingArea).match(/([\d.]+)\s*㎡/) : null;
  const buildingAreaNum = areaMatch ? extractLeadingNum(areaMatch[1]) : null;
  if (buildingAreaNum && m.buildingPrice && m.unitPricePerM2) {
    const computed = m.buildingPrice / buildingAreaNum;
    if (computed > 0 && Math.abs(computed - m.unitPricePerM2) / m.unitPricePerM2 > 0.25) {
      warnings.push('㎡당 단가가 "건물가격÷건물면적" 계산값과 25% 이상 차이납니다. 면적·가격 단위를 확인해 주세요.');
    }
  }
  return warnings;
}

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST only' });
  // 개발호재 검색(mode:'devNews')은 기존 경매정보지 추출(Gemini) 로직과 완전히 별개(네이버 뉴스검색
  // API 사용)라 GEMINI_API_KEY 확인보다 먼저 분기함
  if (req.body && req.body.mode === 'devNews') {
    return handleDevNewsSearch(req, res);
  }
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

  const rawText = hasText ? String(text) : '';
  const trimmedText = trimAuctionText(rawText);
  if (trimmedText.length < rawText.length) {
    console.log(`parse-auction: 하단 불필요 문구 제거 (${rawText.length}자 → ${trimmedText.length}자)`);
  }

  const cacheKey = computeCacheKey(trimmedText, imageParts);
  const cached = await getCachedParseResult(cacheKey);
  if (cached) {
    return res.status(200).json({ detail: cached, cached: true });
  }

  const promptA1 = buildPrompt(PROMPT_A_RULES, trimmedText);
  const promptA2 = buildPrompt(PROMPT_A_RULES, trimmedText);
  const promptB1 = buildPrompt(PROMPT_B_RULES, trimmedText);
  const promptB2 = buildPrompt(PROMPT_B_RULES, trimmedText);

  try {
    // 스키마를 4개(A1/A2/B1/B2)로 나눠 동시에 호출 - 전체 소요시간이 "넷의 합"이 아니라
    // "가장 오래 걸리는 하나" 수준으로 줄어듦 (Hobby 플랜 60초 제한 안에 들어오도록).
    // 각 호출은 프롬프트 규칙 텍스트를 통째로 재사용하지만(해당 스키마에 없는 필드에 대한
    // 규칙은 응답 형식이 스키마로 강제되므로 그냥 무시됨), 스키마 자체의 필드/배열 수가
    // 줄어들어 응답 생성(출력 토큰) 시간이 짧아지는 게 핵심.
    const [resultA1, resultA2, resultB1, resultB2] = await Promise.all([
      callGemini(GEMINI_API_KEY, promptA1, SCHEMA_A1, imageParts, 1, 0),
      callGemini(GEMINI_API_KEY, promptA2, SCHEMA_A2, imageParts, 1, 0),
      callGemini(GEMINI_API_KEY, promptB1, SCHEMA_B1, imageParts, 1, 0),
      callGemini(GEMINI_API_KEY, promptB2, SCHEMA_B2, imageParts, 1, 0),
    ]);
    const merged = { ...resultA1, ...resultA2, ...resultB1, ...resultB2 };
    // 방어적 보정: 프롬프트에서 aptDong에 "OOO호" 형태를 넣지 말라고 명시했지만, 간헐적으로
    // AI가 unitNo와 동일한 "호"로 끝나는 값을 aptDong에 잘못 채우는 경우가 있어(연립다세대에
    // 동 구분이 없는데도 호수를 동으로 오인) 서버에서 한 번 더 걸러냄.
    if (merged.aptDong && /호$/.test(String(merged.aptDong).trim())) {
      console.log(`parse-auction: aptDong이 "호"로 끝나 무효화함 (${merged.aptDong})`);
      merged.aptDong = null;
    }
    merged.warnings = buildNumericWarnings(merged);
    // 캐시에는 경고까지 포함한 최종 결과를 그대로 저장 - 캐시 히트 시 재계산 없이 즉시 반환.
    setCachedParseResult(cacheKey, merged); // 응답을 늦추지 않도록 await 없이 fire-and-forget
    return res.status(200).json({ detail: merged });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}
