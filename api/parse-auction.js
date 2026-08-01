/* ════════════════════════════════════
   경매정보지(탱크옥션 등) 텍스트/캡처 이미지 → 구조화된 JSON 추출
   - 클라이언트가 경매 상세페이지에서 복사한 텍스트를 그대로 넘기거나,
     복사가 막혀 있는 페이지는 화면 캡처 이미지(여러 장 가능)를 넘기면
     Claude API로 필수 항목들을 뽑아서 JSON으로 돌려줍니다. 텍스트와 이미지를
     동시에 보낼 수도 있습니다(둘 다 참고해서 추출).
   ⚠️ 2026-08 AI 제공자 교체: 원래 Gemini(gemini-3.5-flash) 무료 티어를 썼는데, 실측 하루
      한도가 RPD 20회(=물건 상세추출 기준 하루 10건)로 너무 낮아 "한도가 너무 자주 걸린다"는
      신고가 반복됨. Anthropic Claude API(claude-haiku-4-5)로 완전히 교체함 - 사용량 기반
      과금이라 Gemini 무료 티어 같은 하루 요청수 상한이 없고, 분당 한도(RPM/TPM)도 유료 티어라
      훨씬 넉넉함. 프롬프트(HEADER/PROMPT_A_RULES/PROMPT_B_RULES/CASELIST_HEADER)와 스키마
      (SCHEMA_A/B/CASELIST)는 AI 제공자와 무관한 내용이라 전부 그대로 재사용하고, 실제 API
      호출부(callGemini→callClaude)와 에러 분류·재시도 로직만 Claude 방식으로 새로 작성함.
      스키마는 여전히 Gemini 스타일 대문자 타입(OBJECT/STRING 등)로 정의돼 있고, Claude에
      보내기 직전 convertGeminiSchemaToJsonSchema()로 표준 JSON Schema(소문자 타입)로
      변환함(기존 스키마 정의를 그대로 재사용하기 위한 어댑터).
      ⚠️ 필요 환경변수가 GEMINI_API_KEY → ANTHROPIC_API_KEY로 바뀌었습니다. Vercel 프로젝트
      설정(Environment Variables)에 console.anthropic.com에서 발급받은 키를 ANTHROPIC_API_KEY로
      추가해야 동작합니다(기존 GEMINI_API_KEY는 더 이상 쓰이지 않으니 삭제해도 무방).
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
      그래서 한때 A를 다시 A1(물건 기본정보·가격, 배열은 짧은 rounds만)/A2(임차인·매각통계·실거래,
      가장 무거운 배열들)로, B를 B1(건축물정보)/B2(등기이력·권리분석, registryStory 서술형 포함)로
      나눠 4개 호출을 동시에 보내는 구조로 바꿨었음.
   ⚠️ 4→2 재통합 (4차, "하루 10건도 항상 분당/일일 한도에 걸린다" 신고로 재조사): Google AI
      Studio 사용량 대시보드로 실측한 결과, gemini-3.5-flash 무료 티어의 진짜 한도는 흔히
      알려진 것과 달리 RPM 5 / TPM 25만 / "RPD 20"으로 매우 낮았음(2025 세대 Flash 모델 대비
      최신 모델이라 무료 한도 자체가 훨씬 박함 - Gemini 2.5 Flash도 동일하게 RPD 20이라 모델을
      바꿔도 해결되지 않음을 확인). 추출 1건당 4개 호출을 쓰면 RPD 20 ÷ 4 = 하루 5건이
      물리적 한계라, 사용자가 원한 "하루 10건"과 애초에 맞을 수 없는 구조였음. 그래서 A1+A2를
      다시 하나의 스키마 A로, B1+B2를 하나의 스키마 B로 합쳐 호출 수를 4→2로 되돌림
      (RPD 20 ÷ 2 = 하루 10건 확보, RPM 5 대비로도 여유). 대신 개별 호출이 다시 무거워져
      52초 근처까지 걸리는 경우가 가끔 있을 수 있음 - callClaude의 55초 타임아웃과 친절한
      안내 메시지(내용을 줄여 재시도)로 대응함.
   ⚠️ 2026-08 활용도 확장(유료 전환 후): (1) 프롬프트 캐싱 적용 - 스키마(input_schema)와
      고정 지시문(HEADER+규칙, CASELIST_HEADER)에 cache_control을 붙여, 5분 내 동일한
      고정 부분으로 재호출되면 그 부분 입력 토큰이 최대 90% 저렴해짐(buildPrompt가 이제
      문자열이 아니라 [정적 블록(캐시대상), 동적 블록] 배열을 반환하도록 바뀜 - callClaude도
      배열 입력을 지원하도록 확장). (2) mode:'briefing' 신규 추가 - 물건 추출과 무관하게,
      index.html이 이미 계산해둔 값들(예상매도가·예상마진·임차인현황·등기스토리 등)을
      Claude에 한 번 더 넘겨 "3~4문장 요약+위험신호+입찰 권고"로 자연어 브리핑을 만들어줌
      (SCHEMA_BRIEFING/BRIEFING_HEADER/handleBriefing 참고, 1건당 호출 1회).
════════════════════════════════════ */
import crypto from 'crypto';

// claude-haiku-4-5: 구조화된 정보 추출 용도로 충분히 정확하면서 빠르고 저렴한 모델.
// 물건 상세페이지 추출처럼 스키마가 큰 요청도 안정적으로 처리 가능.
const CLAUDE_MODEL = 'claude-haiku-4-5-20251001';
// mode:'taxUpdate'(최신 세율 조사) 전용 모델 - 실시간 웹검색 후 여러 세목(취득세·양도세·
// 종부세·재산세·부가세)을 교차 확인해야 하는 리서치 성격 작업이라, 자주 호출되는 물건추출과
// 달리 속도보다 정확도가 훨씬 중요함. 버튼 클릭 시에만 드물게(하루 몇 번) 호출되므로 비용
// 부담도 적어 상위 모델을 씀.
const TAX_RESEARCH_MODEL = 'claude-sonnet-5';
const ANTHROPIC_API_VERSION = '2023-06-01';
const ANTHROPIC_MESSAGES_URL = 'https://api.anthropic.com/v1/messages';
// Vercel 함수 자체의 실행 제한 시간을 늘림 (기본값은 너무 짧아서, 스키마가 큰 요청은
// Claude 응답이 오기 전에 함수가 먼저 죽어버릴 수 있음). Hobby 플랜에서도 60초까지 가능.
export const maxDuration = 60;
// 캡처 이미지(여러 장)를 첨부하면 base64 페이로드가 커질 수 있어 기본 바디 제한을 올려둠
// (parse-registry.js의 PDF 업로드와 동일한 패턴).
export const config = {
  api: { bodyParser: { sizeLimit: '12mb' } },
};

// ── 스키마 A: 물건 기본정보 / 가격 / 임차인 현황 / 매각통계 / 국토부 실거래 (예전엔 A1/A2로
//    쪼갰었는데, 무료 티어 일일 요청수(RPD) 한도가 실측 20건으로 매우 낮아 호출 수 자체를
//    줄여야 해서 다시 하나로 합침 - 파일 상단 "4→2 재통합" 설명 참고) ──
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
    // 소유자란에 "OOO 외N" 또는 지분 표기(예: "권영태 외3", "1/3", "지분")가 보이면
    // 공유지분 물건(지분경매)일 가능성이 높음 - 공유자 우선매수권 등 별도 법리가
    // 적용되므로 권리분석 화면에 경고 배지를 띄우기 위해 별도 필드로 뽑아둠.
    isCoOwnership: { type: 'BOOLEAN' },
    coOwnerCount: { type: 'INTEGER' },
    debtor: { type: 'STRING' },
    creditor: { type: 'STRING' },
    claimAmount: { type: 'NUMBER' },
    // 미납관리비(체납관리비) - 특수조건/주의사항/비고란에 "미납관리비", "체납관리비",
    // "관리비 연체" 등의 표현과 금액이 언급된 경우에만 채움(단위: 원). 공용부분 체납관리비는
    // 판례상 낙찰자가 인수하는 것으로 알려져 있어, 채무자=소유자 여부와 결합해 명도난이도
    // 판단·필요자금 계산에 씀(클라이언트 로직). 개월수만 언급되고 금액이 없으면 null로 둠
    // (금액 추정 금지 - 실제 금액이 명시된 경우에만 채움).
    unpaidManagementFee: { type: 'NUMBER' },
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
    // ↓↓↓ 예전 SCHEMA_A2(임차인 현황 / 매각통계 / 국토부 실거래 / 공시가격)에 있던 필드들 ↓↓↓
    officialPriceCurrent: { type: 'STRING' },
    tenantTerminationDate: { type: 'STRING' },
    tenantDistributionDeadline: { type: 'STRING' },
    // 소액임차인 최우선변제 판단 기준일. "임차인 전입일"이 아니라 "말소기준등기(주로
    // 최선순위 근저당) 설정일"이며, 사이트에 "소액기준일"이라는 라벨로 별도 표기되는
    // 경우가 많음(예: "말소기준일 : ... 소액기준일 : ... 배당요구종기일 : ...").
    minorTenantBaseDate: { type: 'STRING' },
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
          // 이 임차인이 배당요구를 했는지 여부 - 대항력이 있어도 배당요구를 안 했으면
          // 보증금 전액이 인수 대상으로 확정되므로 인수보증금 계산의 핵심 분기값.
          distributionRequested: { type: 'BOOLEAN' },
          // 사이트가 예상/실제 배당액을 제공하는 경우(예: 예상배당표)만 채우고,
          // 확인 안 되면 비워둘 것 - 미배당액(=인수액) 추정에 사용.
          distributionAmount: { type: 'NUMBER' },
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

// ── 스키마 B: 건축물정보(건축HUB 성격의 표제부/층별개요) / 등기 이력 / 권리분석 (예전엔
//    B1/B2로 쪼갰었는데, SCHEMA_A와 같은 이유로 다시 하나로 합침) ──
const SCHEMA_B = {
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
    // ↓↓↓ 예전 SCHEMA_B2(등기 이력 / 권리분석)에 있던 필드들 ↓↓↓
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
        lienClaimAmount: { type: 'NUMBER' }, // 유치권 신고 채권액(공사대금 등)
        lienDisputed: { type: 'BOOLEAN' }, // 채권자 등이 유치권 배제신청서를 제출했는지
        hasLegalSuperficies: { type: 'BOOLEAN' }, // 법정지상권 성립 여지
        legalSuperficiesNote: { type: 'STRING' },
        hasGraveRights: { type: 'BOOLEAN' }, // 분묘기지권
        graveRightsNote: { type: 'STRING' },
        isIllegalBuilding: { type: 'BOOLEAN' }, // 위반건축물 여부
        illegalBuildingNote: { type: 'STRING' },
        // 사용승인을 받지 못한 채 공사가 중단된 상태(완공 안 된 물건) - 위반건축물과는
        // 별개 개념(이미 지어진 건물의 적법성 문제가 아니라 애초에 미완공)이라 별도 필드.
        isUnderConstruction: { type: 'BOOLEAN' },
        underConstructionNote: { type: 'STRING' },
      },
    },
    // 임차인 등 이해관계인이 "대항력 포기" 등 권리를 포기하는 확약서를 법원에 제출한
    // 사실이 있으면 인수 위험이 실제로는 낮아질 수 있어 별도로 뽑아둠(매각물건명세서
    // "주요변동"란에 자주 등장).
    hasWaiverDocument: { type: 'BOOLEAN' },
    waiverNote: { type: 'STRING' },
    // 이 물건/채무자와 관련된 별도 소송(지급명령, 본안소송 등) - 매각물건명세서나
    // 경매정보 사이트의 "관련사건" 섹션에 나오면 그대로 옮겨 담을 것.
    relatedCases: {
      type: 'ARRAY',
      items: {
        type: 'OBJECT',
        properties: {
          court: { type: 'STRING' },
          caseNo: { type: 'STRING' },
          caseType: { type: 'STRING' }, // 예: "지급명령", "소유권이전등기말소청구"
          result: { type: 'STRING' },
        },
      },
    },
    registryStory: { type: 'STRING' },
    riskSummary: { type: 'STRING' },
  },
};

// ════════════════════════════════════
// 낙찰사례 목록 일괄 추출 (mode:'caseList') - 지역별 낙찰가/마진 통계 기능용.
// 경매정보 사이트(탱크옥션 등) "검색결과 목록" 화면을 통째로 복사해 붙여넣으면, 여러 건을
// 한 번의 Claude 호출로 구조화해서 뽑아냄 (물건 1건짜리 상세페이지 추출(SCHEMA_A/B)과는
// 완전히 다른 스키마·프롬프트 - 목록 화면은 사건마다 필드가 세로로 쌓여 반복되는 형태라
// 상세페이지 프롬프트를 재사용할 수 없음). 비용을 아끼기 위해 호출 1개로 처리하고, 하루
// 사용량 예산(DAILY_CLAUDE_CALL_BUDGET)에서도 실제 소모량인 1회만 정확히 차감함(상세페이지
// 추출의 2회와 구분 - 자세한 설명은 DAILY_CLAUDE_CALL_BUDGET 선언부 참고).
// ════════════════════════════════════
const SCHEMA_CASELIST = {
  type: 'OBJECT',
  properties: {
    cases: {
      type: 'ARRAY',
      items: {
        type: 'OBJECT',
        properties: {
          caseNo: { type: 'STRING' },
          court: { type: 'STRING' },
          propertyType: { type: 'STRING' },
          addrJibun: { type: 'STRING' },
          dong: { type: 'STRING' },
          bunji: { type: 'STRING' },
          buildingName: { type: 'STRING' },
          areaM2: { type: 'NUMBER' },
          floor: { type: 'INTEGER' },
          unitNo: { type: 'STRING' },
          specialConditions: { type: 'STRING' },
          appraisalPrice: { type: 'NUMBER' },
          minBidPrice: { type: 'NUMBER' },
          finalBidPrice: { type: 'NUMBER' },
          bidRate: { type: 'NUMBER' },
          minBidRate: { type: 'NUMBER' },
          status: { type: 'STRING' },
          saleDate: { type: 'STRING' },
        },
      },
    },
  },
};

const CASELIST_HEADER = `다음은 경매정보 사이트(탱크옥션 등)의 "물건 검색결과 목록" 페이지에서 그대로 복사한 텍스트입니다.
여러 건의 경매 물건이 각각 아래와 같은 형태로 줄바꿈되어 반복됩니다(실제 사이트 화면 구조상 항목들이
세로로 쌓여서 나타납니다):

  [물건종류]                예: 다세대주택
  [사건번호]                 예: 2025-52569(1)  ← 괄호 안 회차번호가 있으면 그대로 포함
  [지번주소 + 층/호]          예: 경기도 안산시 단원구 와동 110-5 4층401호  ← floor:4, unitNo:"401호"
  ([도로명주소])              예: (경기 안산시 단원구 사세충열로4안길 6-1)
  [면적정보]                 예: 건물 59.9㎡(18.12평), 대지권 31.98㎡(9.674평)
  [특이사항 한 줄]            예: 토지·건물 일괄매각  임차권등기, 대항력 있는 임차인, 공시가 1억이하  (없을 수도 있음)
  [금액들 - 순서대로 감정가, 최저입찰가, (매각된 경우만) 낙찰가]
                            예: 141,000,000 / 33,854,000 / 33,900,000
                            ⚠️ 금액이 2개만 있으면 [감정가, 최저입찰가] 순서이고 아직 낙찰 전(진행중)입니다.
                            금액이 3개면 [감정가, 최저입찰가, 낙찰가] 순서입니다.
  [진행상태]                 예: 매각(허가) / 유찰 / 진행 / 변경 / 취하 등
  [퍼센트 2개]               예: (24%)(24%) → 순서대로 [최저가율], [낙찰가율]로 보이지만 사이트마다 순서가
                            다를 수 있으니, 반드시 직접 계산해서(최저가/감정가*100, 낙찰가/감정가*100)
                            minBidRate/bidRate에 채우세요 (이건 추측이 아니라 검증된 계산입니다).
  [담당계]                   예: 안산4계
  [매각기일 (시간)]           예: 26.07.16 (10:30) → saleDate는 "2026-07-16"으로 변환
  [조회수]                   예: 조회: 231  ← 추출 불필요, 무시

각 물건 블록마다 위 항목들을 읽어 cases 배열에 객체 하나씩 담아주세요.
공통 규칙:
- 명시되지 않은 값은 null로 두세요. 위에서 설명한 minBidRate/bidRate 계산 외에는 추측·지어내기 금지입니다.
- 금액은 원 단위 숫자로 변환하세요 (쉼표 제거, "1억 3,300만" 같은 표기는 133000000으로 변환).
- addrJibun은 시/도부터 번지까지만 담고 층수·호수는 제외하세요. dong/bunji는 그 안에서 동/번지만 따로 뽑으세요.
  예: "경기도 안산시 단원구 와동 110-5" → dong: "와동", bunji: "110-5"
- areaM2는 "건물" 면적의 ㎡ 앞 숫자만 담으세요 (대지권 면적은 무시).
- floor는 지번주소 뒤의 "N층" 표기에서 숫자만 뽑으세요. 지하층(예: "지1층")은 -1로 담으세요.
- unitNo(호수)는 지번주소 뒤의 "N호" 표기를 문자열 그대로 담으세요 (예: "302호", 지하 유닛의 "비03호"도 그대로). 표기가 없으면 null.
- status는 "매각(허가)"처럼 붙어있으면 "매각"으로 정규화하고, 유찰/진행/변경/취하 등은 그대로 담으세요.
- 어떤 물건 블록이 파싱하기에 정보가 너무 부족하면(사건번호나 주소를 알 수 없으면) 그 블록은 통째로 건너뛰세요.
- 목록에 없는 항목(다른 페이지, 광고, 메뉴 등)은 절대 포함하지 마세요.`;

async function handleCaseListExtraction(req, res) {
  const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY;
  if (!ANTHROPIC_API_KEY) {
    return res.status(500).json({ error: 'ANTHROPIC_API_KEY 환경변수가 없습니다. Vercel 프로젝트 설정에 추가해 주세요.' });
  }
  const text = req.body && req.body.text ? String(req.body.text).trim() : '';
  if (!text) return res.status(400).json({ error: '분석할 목록 텍스트가 없습니다.' });
  const trimmed = trimAuctionText(text);
  const cacheKey = 'auctioncaselist_' + crypto.createHash('sha256').update(trimmed).digest('hex');
  const cached = await getCachedParseResult(cacheKey);
  if (cached) return res.status(200).json({ cases: cached, cached: true });

  const dailyKey = `auctionparse_daily_${todayKstDateStr()}`;
  const usedToday = await getDailyExtractCount(dailyKey);
  if (usedToday + CLAUDE_CALLS_PER_CASELIST_EXTRACT > DAILY_CLAUDE_CALL_BUDGET) {
    return res.status(429).json({
      error: `오늘 AI 자동추출 사용량 안전한도(비용 급증 방지용, 하루 ${DAILY_CLAUDE_CALL_BUDGET}회)에 다 찼습니다. 한국시간 자정에 초기화됩니다. (물건 상세추출은 1건당 2회, 낙찰사례 목록 추출은 1건당 1회를 소모합니다 - 지금까지 ${usedToday}회 사용)`,
      dailyLimitReached: true,
      usedToday,
      limit: DAILY_CLAUDE_CALL_BUDGET,
    });
  }
  // CASELIST_HEADER(고정 지시문)는 어떤 목록을 붙여넣든 완전히 동일한 텍스트라 캐싱 대상으로
  // 분리함 - 붙여넣은 목록 텍스트만 별도(캐싱 안 되는) 블록으로 둠.
  const promptBlocks = [
    { type: 'text', text: CASELIST_HEADER, cache_control: { type: 'ephemeral' } },
    { type: 'text', text: '\n\n--- 붙여넣은 목록 텍스트 시작 ---\n' + trimmed + '\n--- 붙여넣은 목록 텍스트 끝 ---' },
  ];
  try {
    const result = await callClaude(ANTHROPIC_API_KEY, promptBlocks, SCHEMA_CASELIST, [], 1, 0);
    const cases = Array.isArray(result.cases) ? result.cases : [];
    setCachedParseResult(cacheKey, cases); // fire-and-forget
    incrementDailyExtractCount(dailyKey, CLAUDE_CALLS_PER_CASELIST_EXTRACT); // fire-and-forget
    return res.status(200).json({ cases });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}

// ════════════════════════════════════
// AI 투자 브리핑 (mode:'briefing') - 2026-08 신규.
// - 물건 추출(SCHEMA_A/B)이나 낙찰사례 통계와 달리, 이 기능은 새로 뭔가를 "추출"하지 않음.
//   index.html이 이미 계산해둔 값들(예상매도가·목표매도가·예상마진·목표마진·목표입찰가·
//   임차인 현황·등기 스토리·특수조건·낙찰사례 표본 수 등)을 그대로 JSON으로 넘기면,
//   Claude가 그걸 종합해서 "3~4문장 핵심 요약 + 위험신호 목록 + 입찰 관련 한 줄 권고"로
//   정리해줌. 즉 계산은 여전히 클라이언트(index.html)가 하고, Claude는 "숫자를 사람이
//   읽기 편한 판단 브리핑으로 번역"하는 역할만 함 - 새로운 사실을 지어내지 말라고 명시함.
// - 입력 데이터가 매번 달라서(물건마다 값이 다름) 캐싱 효과가 거의 없어 프롬프트 캐싱은
//   적용하지 않음(고정 지시문 BRIEFING_HEADER 자체는 짧아 캐싱 최소 토큰 기준에도 못 미침).
// - 물건 1건당 호출 1회(CLAUDE_CALLS_PER_BRIEFING)만 소모.
// ════════════════════════════════════
const SCHEMA_BRIEFING = {
  type: 'OBJECT',
  properties: {
    summary: { type: 'STRING' },
    riskFlags: { type: 'ARRAY', items: { type: 'STRING' } },
    recommendation: { type: 'STRING' },
  },
};

const BRIEFING_HEADER = `당신은 경매 투자자에게 물건 하나를 3초 안에 파악할 수 있도록 브리핑해주는 조수입니다.
아래 JSON은 이 경매 물건에 대해 이미 계산·수집되어 있는 값들입니다(금액 단위는 원).
이 데이터에 없는 사실은 절대 지어내지 마세요 - 오직 주어진 값을 근거로 판단·요약만 하세요.

작성 규칙:
- summary: 이 물건이 어떤 물건이고(유형·위치·규모), 감정가 대비 최저가·예상매도가·예상마진이
  어느 정도 수준인지를 3~4문장의 자연스러운 한국어로 요약하세요. 아이패드에서 짧게 훑어볼
  용도이니 문장은 간결하게, 이미 아는 숫자를 나열만 하지 말고 "그래서 어떤 상황인지" 판단이
  드러나게 쓰세요.
- riskFlags: 이 데이터에서 확인되는 위험 신호를 짧은 문장(각 20자 내외)의 배열로 담으세요.
  예: 대항력 있는 임차인 존재, 인수 여부 불명(willBeAssumed가 없는 등기 항목), 미납관리비 존재,
  낙찰사례 표본이 3건 미만이라 예상마진 신뢰도가 낮음, 목표입찰가가 감정가에 근접해 마진이 얇음 등.
  해당하는 게 없으면 빈 배열로 두세요. 데이터에 없는 위험을 추측해서 만들지 마세요.
- recommendation: 입찰 여부·가격에 대한 한두 문장짜리 실용적인 권고. "적극 추천" 같은 단정적
  투자 조언이 아니라, 이 데이터가 보여주는 근거를 바탕으로 한 조건부 판단으로 쓰세요
  (예: "예상마진 표본이 적어 참고용으로만 보고 실거래를 더 확인한 뒤 입찰가를 정하는 게 안전합니다").`;

async function handleBriefing(req, res) {
  const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY;
  if (!ANTHROPIC_API_KEY) {
    return res.status(500).json({ error: 'ANTHROPIC_API_KEY 환경변수가 없습니다. Vercel 프로젝트 설정에 추가해 주세요.' });
  }
  const data = req.body && req.body.data && typeof req.body.data === 'object' ? req.body.data : null;
  if (!data) return res.status(400).json({ error: '브리핑을 만들 물건 데이터가 없습니다.' });

  const inputStr = JSON.stringify(data);
  const cacheKey = 'auctionbrief_' + crypto.createHash('sha256').update(inputStr).digest('hex');
  const cached = await getCachedParseResult(cacheKey);
  if (cached) return res.status(200).json({ briefing: cached, cached: true });

  const dailyKey = `auctionparse_daily_${todayKstDateStr()}`;
  const usedToday = await getDailyExtractCount(dailyKey);
  if (usedToday + CLAUDE_CALLS_PER_BRIEFING > DAILY_CLAUDE_CALL_BUDGET) {
    return res.status(429).json({
      error: `오늘 AI 자동추출 사용량 안전한도(비용 급증 방지용, 하루 ${DAILY_CLAUDE_CALL_BUDGET}회)에 다 찼습니다. 한국시간 자정에 초기화됩니다. (지금까지 ${usedToday}회 사용)`,
      dailyLimitReached: true,
      usedToday,
      limit: DAILY_CLAUDE_CALL_BUDGET,
    });
  }

  const promptText = BRIEFING_HEADER + '\n\n--- 물건 데이터(JSON) ---\n' + inputStr;
  try {
    const result = await callClaude(ANTHROPIC_API_KEY, promptText, SCHEMA_BRIEFING, [], 1, 0.3);
    setCachedParseResult(cacheKey, result); // fire-and-forget
    incrementDailyExtractCount(dailyKey, CLAUDE_CALLS_PER_BRIEFING); // fire-and-forget
    return res.status(200).json({ briefing: result });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}

// ════════════════════════════════════
// 최신 세율 조사 (mode:'taxUpdateResearch' → mode:'taxUpdateExtract') - 2026-08 신규.
// index.html의 TAX_CONFIG(취득세·재산세·종부세·양도소득세·부가세 계산에 쓰이는 모든 세율·
// 구간·공제액)를 최신 상태로 갱신하기 위한 기능. 세법·시행령이 자주 바뀌고(다주택 중과,
// 조정대상지역 지정, 공정시장가액비율 등) Claude의 학습 데이터만으로는 최신 여부를 장담할 수
// 없어서, 반드시 실시간 웹검색으로 근거를 찾은 뒤에 답하도록 2단계로 나눔:
//   1단계(mode:'taxUpdateResearch' → callClaudeWebSearch): web_search 툴을 주고 "지금 기준으로
//     각 세목이 어떤지, TAX_CONFIG 기본값과 비교해 뭐가 바뀌었는지"를 자유 형식으로 조사하게
//     함 - Claude가 스스로 검색 횟수·검색어를 정하고, 국세청·위택스·행안부 등 공신력 있는
//     출처를 찾아 인용까지 함.
//   2단계(mode:'taxUpdateExtract' → callClaude, tool_choice 강제): 1단계의 텍스트 답변을
//     구조화된 JSON(TAX_CONFIG와 동일한 모양)으로 변환함. 이 단계에서는 새로 검색하지 않고
//     1단계 답변만 근거로 삼음.
// ⚠️ 2026-08 실동작 테스트에서 두 단계를 한 서버리스 함수 호출 안에서 순차 실행했더니(구
// handleTaxUpdate), 1단계 웹검색만으로도 Anthropic 응답이 55초(postAnthropicMessages의
// AbortSignal 한도)를 넘겨 타임아웃이 났음 - Vercel Hobby maxDuration이 60초라 "검색 여러
// 번 도는 리서치" + "구조화 추출"을 한 호출에 몰아넣을 여유가 없었음. 그래서 프론트엔드
// (index.html의 updateTaxRates)가 두 번의 별도 HTTP 요청으로 나눠 호출하도록 바꿈 - 각
// 요청은 Claude 호출을 딱 1번만 하므로 각자 60초 예산을 온전히 씀.
// ⚠️ 확신 없는 필드는 스키마에서 required로 강제하지 않았음 - 2단계 프롬프트에서도 "모르면
// 그 필드는 아예 비워두라"고 명시해, 프론트엔드가 "제공된 필드만 검증 후 부분 반영"할 수
// 있게 함(전체를 통째로 덮어쓰지 않음 - index.html의 sanitizeAndMergeTaxConfig 참고).
// 리서치(1단계)는 웹검색 비용이 별도로 붙고(건당 $10/1000회) 구조화 추출(2단계)은 일반 호출과
// 같아서, 하루 사용량 안전한도에는 단계별로 1회씩 계산함(실제 웹검색 횟수는 별도 청구 -
// Anthropic 콘솔에서 확인 가능).
// ════════════════════════════════════
const CLAUDE_CALLS_PER_TAX_UPDATE_STEP = 1;

const SCHEMA_TAX_UPDATE = {
  type: 'OBJECT',
  properties: {
    reportSummary: { type: 'STRING' },
    changesDetected: { type: 'ARRAY', items: { type: 'STRING' } },
    missingTaxesNote: { type: 'STRING' },
    lowConfidenceNote: { type: 'STRING' },
    sources: {
      type: 'ARRAY',
      items: { type: 'OBJECT', properties: { title: { type: 'STRING' }, url: { type: 'STRING' } } },
    },
    config: {
      type: 'OBJECT',
      properties: {
        acquisition: {
          type: 'OBJECT',
          properties: {
            baseTierLowMax: { type: 'NUMBER' },
            baseTierMidMax: { type: 'NUMBER' },
            heavyRateAdjusted2: { type: 'NUMBER' },
            heavyRateAdjusted3plus: { type: 'NUMBER' },
            heavyRateNonAdjusted3: { type: 'NUMBER' },
            heavyRateNonAdjusted4plus: { type: 'NUMBER' },
            eduTaxAddPct: { type: 'NUMBER' },
            nongTaxAdd8: { type: 'NUMBER' },
            nongTaxAdd12: { type: 'NUMBER' },
            nongTaxAddBase85: { type: 'NUMBER' },
            otherPropertyRatePct: { type: 'NUMBER' },
          },
        },
        propertyTax: {
          type: 'OBJECT',
          properties: {
            ratio1HouseTiers: {
              type: 'ARRAY',
              items: { type: 'OBJECT', properties: { maxWon: { type: 'NUMBER' }, ratio: { type: 'NUMBER' } } },
            },
            ratioMultiHouse: { type: 'NUMBER' },
            brackets: {
              type: 'ARRAY',
              items: { type: 'OBJECT', properties: { maxWon: { type: 'NUMBER' }, rate: { type: 'NUMBER' } } },
            },
            eduTaxRate: { type: 'NUMBER' },
            urbanTaxRate: { type: 'NUMBER' },
          },
        },
        compTax: {
          type: 'OBJECT',
          properties: {
            deduction1HouseManwon: { type: 'NUMBER' },
            deductionOtherManwon: { type: 'NUMBER' },
            ratio: { type: 'NUMBER' },
            levyRate: { type: 'NUMBER' },
            brackets: {
              type: 'ARRAY',
              items: {
                type: 'OBJECT',
                properties: { minManwon: { type: 'NUMBER' }, rate: { type: 'NUMBER' }, dedManwon: { type: 'NUMBER' } },
              },
            },
          },
        },
        incomeTax: {
          type: 'OBJECT',
          properties: {
            brackets: {
              type: 'ARRAY',
              items: {
                type: 'OBJECT',
                properties: { minManwon: { type: 'NUMBER' }, rate: { type: 'NUMBER' }, dedManwon: { type: 'NUMBER' } },
              },
            },
            localTaxRate: { type: 'NUMBER' },
            basicDeductionManwon: { type: 'NUMBER' },
            shortRateUnder1y: { type: 'NUMBER' },
            shortRateUnder2y: { type: 'NUMBER' },
            longTermDeductionPerYear: { type: 'NUMBER' },
            longTermDeductionMax: { type: 'NUMBER' },
            heavySurcharge2House: { type: 'NUMBER' },
            heavySurcharge3House: { type: 'NUMBER' },
          },
        },
        vat: {
          type: 'OBJECT',
          properties: { rate: { type: 'NUMBER' }, nationalHousingAreaM2: { type: 'NUMBER' } },
        },
      },
    },
  },
};

// 1단계 리서치 프롬프트에 넣을 "현재 앱이 쓰고 있는 기본값" 설명 - Claude가 이 값과 비교해서
// 뭐가 바뀌었는지 짚어줄 수 있게 함(값을 모르면 그냥 최신 정보만 조사해도 됨).
const TAX_UPDATE_CURRENT_DEFAULTS = `
- 취득세: 6억↓ 1%, 6억~9억 1~3%(선형), 9억↑ 3%. 다주택 중과: 조정대상지역 2주택 8%·3주택↑ 12%,
  비조정대상지역 3주택 8%·4주택↑ 12%(+지방교육세0.4%p, 전용85㎡초과 시 농특세 0.6~1.0%p 가산).
- 재산세: 공정시장가액비율 1주택 43~45%(공시가격 구간별)·다주택/법인 60%. 과세표준 6천만↓0.1%,
  1.5억↓0.15%, 3억↓0.25%, 3억↑0.4%(4단계 누진) + 지방교육세(재산세액20%) + 도시지역분(과세표준0.14%).
- 종합부동산세: 공제 1세대1주택 12억/그외 9억, 공정시장가액비율 60%, 과세표준(만원) 3천↓0.5%,
  6천↓0.7%, 1.2억↓1.0%, 2.5억↓2.0%, 5억↓3.0%, 9.4억↓4.0%, 9.4억↑5.0%(2주택이하 기준, 누진공제
  포함) + 농어촌특별세(종부세액20%).
- 양도소득세/종합소득세(매매사업자): 8단계 누진세율 6~45%(1400만/5000만/8800만/1.5억/3억/5억/10억
  구간) + 지방소득세(소득세액10%). 개인 양도세는 보유1년미만 70%·2년미만 60% 단기세율, 2년↑ 장기
  보유특별공제(연2%,최대30%)+기본공제(연250만)+8단계 누진세율. 조정대상지역 다주택 양도세 중과:
  2주택 +20%p·3주택↑ +30%p(2026.5.9 유예 종료, 재시행 중이라고 알려짐 - 이 유예/재시행 상태가
  최신 기준으로도 맞는지 꼭 확인).
- 부가가치세: 매매사업자가 국민주택규모(전용 85㎡) 초과 주택을 사고팔 때 건물분에 10%.`;

function buildTaxUpdateResearchPrompt() {
  const todayStr = todayKstDateStr();
  return `당신은 한국 부동산 세법 리서치 담당자입니다. 오늘은 ${todayStr}(한국시간)입니다.
아래는 "1234auction"이라는 경매 투자 분석 앱이 현재 코드에 내장해 둔 세율 기본값입니다:
${TAX_UPDATE_CURRENT_DEFAULTS}

web_search 툴을 사용해 국세청(nts.go.kr), 위택스(wetax.go.kr), 국토교통부·행정안전부 보도자료,
법제처 국가법령정보센터 등 공신력 있는 출처를 찾아, 위 다섯 세목(취득세/재산세/종합부동산세/
양도소득세·종합소득세/부가가치세)이 오늘(${todayStr}) 기준으로 실제로 어떤지 조사해 주세요.
특히 아래를 중점적으로 확인하세요:
- 다주택자 취득세·양도세 중과 제도가 여전히 시행 중인지, 세율이나 주택수 기준이 바뀌었는지
- 조정대상지역 지정 현황이 바뀌었는지(전국 확대/축소 등 큰 변화가 있었는지)
- 종합부동산세·재산세의 공정시장가액비율이나 세율 구간이 그 해 시행령으로 조정됐는지
- 양도소득세 중과 유예가 연장되거나 재시행되는 등 상태가 바뀌었는지
- 위 다섯 세목 외에, 경매·부동산 매매와 관련해 최근 새로 생기거나 크게 바뀐 세금·부담금이
  있는지(예: 특정 지역 한정 조치, 신설 부담금 등) - 있으면 반드시 언급하세요.
⚠️ 시간 제한이 있으니 검색은 최대 5회 이내로 아껴서 쓰세요 - 세목별로 따로따로 찾기보다,
한 번의 검색으로 여러 세목을 함께 다루는 요약·정리 페이지(국세청 보도자료, 세법 개정 종합
안내 등)를 우선적으로 찾는 게 효율적입니다. 검색 횟수를 다 쓰기 전에 충분히 확인됐다고
판단되면 그 시점에서 바로 답변을 정리해 마무리하세요.
찾은 내용을 근거(출처)와 함께 한국어로 정리해서 답해 주세요. 확실하지 않은 부분은 추측하지 말고
"확인 못함"이라고 솔직히 말하세요.`;
}

function buildTaxUpdateExtractPrompt(researchText) {
  return `아래는 한국 부동산 세율에 대한 리서치 결과 텍스트입니다. 이 내용을 근거로만 구조화된
데이터를 만들어 주세요 - 여기 없는 내용을 추측해서 채우지 마세요.

규칙:
- reportSummary: 리서치 결과를 2~4문장으로 요약(사용자가 앱 화면에서 바로 읽을 짧은 요약).
- changesDetected: 기존 앱 기본값과 달라진 부분이 있으면 "OO세 X% → Y%로 변경" 같은 짧은
  문장 배열로. 달라진 게 없으면 빈 배열.
- missingTaxesNote: 리서치 결과에서 앱이 놓치고 있는 세금·부담금이 언급됐으면 설명, 없으면 null.
- lowConfidenceNote: 리서치 결과 자체가 "확인 못함"이라고 밝힌 부분이 있으면 그 내용, 없으면 null.
- sources: 리서치에서 인용된 출처(제목+URL) 목록.
- config: 리서치 결과에서 구체적인 숫자(세율·구간·공제액)를 확인할 수 있었던 항목만 채우세요.
  확실하지 않거나 리서치 결과에 언급이 없는 필드는 통째로 생략하세요(0이나 추측값을 넣지
  마세요 - 생략하면 앱이 기존 기본값을 그대로 유지합니다). 확인된 항목만 정확히 채우면 됩니다.

--- 리서치 결과 ---
${researchText}`;
}

// 1단계: 웹검색 리서치만 수행 (Claude 호출 1회, 서버리스 함수 호출도 이것 하나뿐이라 60초
// 예산을 온전히 씀). 결과 텍스트+출처를 그대로 프론트엔드에 돌려주면, 프론트가 이어서
// mode:'taxUpdateExtract'를 호출해 2단계(구조화 추출)를 별도 요청으로 진행함.
async function handleTaxUpdateResearch(req, res) {
  const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY;
  if (!ANTHROPIC_API_KEY) {
    return res.status(500).json({ error: 'ANTHROPIC_API_KEY 환경변수가 없습니다. Vercel 프로젝트 설정에 추가해 주세요.' });
  }
  const dailyKey = `auctionparse_daily_${todayKstDateStr()}`;
  const usedToday = await getDailyExtractCount(dailyKey);
  if (usedToday + CLAUDE_CALLS_PER_TAX_UPDATE_STEP > DAILY_CLAUDE_CALL_BUDGET) {
    return res.status(429).json({
      error: `오늘 AI 자동추출 사용량 안전한도(비용 급증 방지용, 하루 ${DAILY_CLAUDE_CALL_BUDGET}회)에 다 찼습니다. 한국시간 자정에 초기화됩니다. (지금까지 ${usedToday}회 사용)`,
      dailyLimitReached: true,
      usedToday,
      limit: DAILY_CLAUDE_CALL_BUDGET,
    });
  }
  try {
    // max_uses를 8→5로 줄임: 검색을 많이 돌수록 Anthropic 응답이 느려져 55초 타임아웃에
    // 걸리는 경우가 실동작 테스트에서 확인됨 - 5회로도 위 다섯 세목을 커버할 수 있도록
    // 프롬프트(buildTaxUpdateResearchPrompt)에서 "여러 세목을 한 번에 다루는 페이지 우선"
    // 전략을 안내해둠.
    const research = await callClaudeWebSearch(ANTHROPIC_API_KEY, buildTaxUpdateResearchPrompt(), 5);
    incrementDailyExtractCount(dailyKey, CLAUDE_CALLS_PER_TAX_UPDATE_STEP); // fire-and-forget
    return res.status(200).json({ researchText: research.text, sources: research.sources });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}

// 2단계: 1단계에서 받은 리서치 텍스트를 구조화 JSON으로 추출 (Claude 호출 1회, 새로 검색하지
// 않아 훨씬 빠름). researchText는 프론트엔드가 1단계 응답을 그대로 되돌려줌.
async function handleTaxUpdateExtract(req, res) {
  const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY;
  if (!ANTHROPIC_API_KEY) {
    return res.status(500).json({ error: 'ANTHROPIC_API_KEY 환경변수가 없습니다. Vercel 프로젝트 설정에 추가해 주세요.' });
  }
  const researchText = req.body && req.body.researchText;
  if (!researchText || typeof researchText !== 'string') {
    return res.status(400).json({ error: '리서치 결과(researchText)가 없습니다. 1단계 조사를 먼저 완료해 주세요.' });
  }
  const dailyKey = `auctionparse_daily_${todayKstDateStr()}`;
  const usedToday = await getDailyExtractCount(dailyKey);
  if (usedToday + CLAUDE_CALLS_PER_TAX_UPDATE_STEP > DAILY_CLAUDE_CALL_BUDGET) {
    return res.status(429).json({
      error: `오늘 AI 자동추출 사용량 안전한도(비용 급증 방지용, 하루 ${DAILY_CLAUDE_CALL_BUDGET}회)에 다 찼습니다. 한국시간 자정에 초기화됩니다. (지금까지 ${usedToday}회 사용)`,
      dailyLimitReached: true,
      usedToday,
      limit: DAILY_CLAUDE_CALL_BUDGET,
    });
  }
  try {
    const extracted = await callClaude(ANTHROPIC_API_KEY, buildTaxUpdateExtractPrompt(researchText), SCHEMA_TAX_UPDATE, [], 1, 0);
    incrementDailyExtractCount(dailyKey, CLAUDE_CALLS_PER_TAX_UPDATE_STEP); // fire-and-forget
    // 2단계에서 나온 sources가 비어 있으면(추출 누락) 1단계에서 프론트가 넘겨준 출처로 대체
    const fallbackSources = Array.isArray(req.body.sources) ? req.body.sources : [];
    const sources = (Array.isArray(extracted.sources) && extracted.sources.length) ? extracted.sources : fallbackSources;
    return res.status(200).json({
      reportSummary: extracted.reportSummary || null,
      changesDetected: Array.isArray(extracted.changesDetected) ? extracted.changesDetected : [],
      missingTaxesNote: extracted.missingTaxesNote || null,
      lowConfidenceNote: extracted.lowConfidenceNote || null,
      sources: sources || [],
      config: extracted.config || {},
    });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}

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

// 예전엔 고정 지시문(HEADER+규칙)과 매번 바뀌는 붙여넣은 텍스트를 하나의 문자열로 합쳐서
// 보냈는데, 프롬프트 캐싱을 적용하려면 "고정 부분"과 "매번 다른 부분"을 서로 다른 콘텐츠
// 블록으로 나눠야 함(캐시는 블록 단위로 걸림). 그래서 문자열 하나 대신 배열을 반환하도록
// 바꿨고, 고정 지시문 블록에만 cache_control을 붙여 callClaude가 그대로 messages에 실어보냄.
function buildPrompt(rules, text) {
  const staticBlock = {
    type: 'text',
    text: HEADER + '\n\n추가 규칙:' + rules,
    cache_control: { type: 'ephemeral' },
  };
  const blocks = [staticBlock];
  if (text && String(text).trim()) {
    blocks.push({ type: 'text', text: `\n\n--- 붙여넣은 텍스트 시작 ---\n${text}\n--- 붙여넣은 텍스트 끝 ---` });
  }
  return blocks;
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
  표시는 note에 담으세요.
  · distributionRequested(배당요구 여부)는 "배당:있음"/"배당요구일"처럼 날짜나 "있음"이 명시되면 true,
    "배당:없음"이면 false, 언급이 없으면 null로 두세요.
  · distributionAmount(예상/실제 배당액)는 배당표나 예상배당 정보가 별도로 제공된 경우에만 숫자로 채우고,
    없으면 null (보증금(deposit)과 혼동하지 마세요 - 이건 "실제 받는/받을 금액"입니다).
- minorTenantBaseDate(소액기준일)는 "말소기준일 : ... 소액기준일 : ... 배당요구종기일 : ..."처럼 한 줄로
  묶여 표기되는 경우가 많으니 그 형식을 찾아 "소액기준일" 뒤의 날짜만 뽑으세요. 언급이 없으면 null.
- isCoOwnership(공유지분 여부)은 소유자(owner)란에 "OOO 외N", "지분", "각 N/100"처럼 여러 명이 나눠
  소유한 정황이 보이면 true로, 단독 소유가 명확하면 false로 표시하세요. coOwnerCount는 "외N"의 N+1처럼
  전체 공유자 수를 추정할 수 있으면 숫자로, 확실하지 않으면 null로 두세요.
- unpaidManagementFee(미납관리비)는 specialConditions·caseCautions 등에 "미납관리비", "체납관리비",
  "관리비 연체" 같은 표현과 함께 구체적인 금액(원)이 명시된 경우에만 그 숫자를 담으세요. 개월수만
  언급되고 금액이 없으면(예: "관리비 6개월 연체") 금액을 임의로 추정하지 말고 null로 두세요.`;

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
  · 유치권 → hasLien, 관련 문구를 lienNote에 원문 그대로. 신고 채권액(예: "공사대금 4억4천만원")이 있으면
    숫자만 lienClaimAmount에 담고, 채권자나 신청채권자 등이 "배제신청서를 제출"했다는 문구가 있으면
    lienDisputed: true로 표시하세요(배제신청 언급이 없으면 null).
  · 법정지상권(또는 "관습법상 법정지상권", "토지 건물 소유자 상이") → hasLegalSuperficies, legalSuperficiesNote.
  · 분묘(분묘기지권) → hasGraveRights, graveRightsNote.
  · 위반건축물(또는 "무허가 증축", "불법 확장") → isIllegalBuilding, illegalBuildingNote.
  · 건축 중단/미사용승인(예: "사용승인을 받지 않은 건물", "건축 중단된 상태") → isUnderConstruction,
    underConstructionNote. 이건 위반건축물과 다른 개념(완공 자체가 안 된 상태)이니 혼동하지 마세요.
  각 항목은 본문에 해당 단어가 나오면 true, "해당사항 없음"처럼 명시적으로 부인하면 false, 아예 언급이 없으면 null로 두세요.
  절대로 본문에 없는 내용을 추측해서 true/false로 채우지 마세요.
- hasWaiverDocument(확약서 제출 여부)는 "주요변동"이나 "주의사항" 등에 임차인·채권자가 "대항력을 포기",
  "우선변제권만 주장", "임차권등기를 말소하는 것에 동의" 같은 확약서·동의서를 제출했다는 문구가 있으면
  true로 하고 waiverNote에 원문을 옮기세요. 언급이 없으면 null.
- relatedCases(관련사건)는 "관련사건" 섹션에 나오는 별도 소송(지급명령, 본안소송 등)을 court/caseNo/
  caseType/result로 나눠 모두 담으세요. 그런 섹션이 없으면 빈 배열로 두세요.
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

// SCHEMA_A/B/CASELIST는 예전 Gemini responseSchema 형식(대문자 타입: OBJECT/STRING/NUMBER/
// INTEGER/BOOLEAN/ARRAY)으로 정의되어 있음. 스키마 자체(필드 구성)는 AI 제공자와 무관한
// 내용이라 그대로 재사용하고, Claude(Anthropic tool use)가 요구하는 표준 JSON Schema
// (소문자 타입)로 보내기 직전에 재귀적으로 변환만 함 - 300줄 넘는 스키마를 다시 옮겨적을
// 필요 없이 어댑터 함수 하나로 해결.
function convertGeminiSchemaToJsonSchema(node) {
  if (node === null || typeof node !== 'object') return node;
  if (Array.isArray(node)) return node.map(convertGeminiSchemaToJsonSchema);
  const out = {};
  for (const key of Object.keys(node)) {
    if (key === 'type' && typeof node[key] === 'string') {
      out.type = node[key].toLowerCase();
    } else {
      out[key] = convertGeminiSchemaToJsonSchema(node[key]);
    }
  }
  return out;
}

// Claude(Anthropic API)가 429로 거절하면 응답 헤더에 retry-after(초)가 담겨오는 경우가
// 많음. 있으면 그 시간만큼, 없으면 기본값을 기다린다.
function parseAnthropicRetryDelayMs(headers) {
  const raw = headers && headers.get ? headers.get('retry-after') : null;
  if (!raw) return null;
  const sec = parseFloat(raw);
  if (!isFinite(sec) || sec <= 0) return null;
  return Math.ceil(sec * 1000) + 500; // 약간의 여유를 더함
}

// Claude가 "overloaded_error"(529, 일시적 서버 과부하)로 거절하는 경우가 있는데, 대부분
// 몇~십몇 초 안에 풀리는 일시적 현상이라 최대 4회까지 자동 재시도한다(간격 1.5s→3s→4.5s→6s).
// 429(rate_limit_error, 분당 요청수/토큰수 한도)는 롤링 윈도우라 곧 풀리므로 retry-after
// 헤더(+지터)만큼 기다렸다가 최대 2회까지 재시도한다. Gemini 무료 티어와 달리 Claude는
// "하루 요청수(RPD)" 같은 절대 상한이 없어(사용량 기반 과금 + 분당 롤링 한도) 일일
// 한도 분류(classifyQuotaError) 로직 자체가 필요 없어짐 - 대신 비용 급증 방지용 자체
// 안전장치는 아래 DAILY_CLAUDE_CALL_BUDGET으로 별도 관리함.
// (API 키 오류·잘못된 요청 같은 재시도해도 안 풀리는 오류는 즉시 그대로 던짐)
// imageParts: [{ type:'image', source:{ type:'base64', media_type, data } }, ...] - 없으면 빈 배열.
// temperature: 기본 0(재현성 우선).
// promptInput: 보통은 문자열(예전 방식, 캐싱 없이 통짜로 보냄)이지만, 배열로 넘기면
//   [{type:'text', text, cache_control:{type:'ephemeral'}}, ...] 형태의 콘텐츠 블록을
//   그대로 messages에 실어보냄 - 프롬프트 캐싱(아래 설명) 적용 시 호출부에서 이 배열 형태로 넘김.
// ⚠️ 2026-08 프롬프트 캐싱 적용: 물건 상세추출(스키마 A/B)·낙찰사례 목록추출(CASELIST) 모두
//   "고정 지시문(HEADER+규칙 또는 CASELIST_HEADER)"과 "매번 달라지는 붙여넣은 텍스트"가
//   하나의 프롬프트에 섞여 있었는데, 고정 지시문 부분은 어떤 물건을 추출하든 완전히 동일한
//   텍스트라서 Anthropic 프롬프트 캐싱 대상으로 적합함. 호출부(buildCachedPropertyPrompt/
//   handleCaseListExtraction)에서 고정 지시문 블록에만 cache_control을 붙여 넘기면, 5분
//   이내에 같은 고정 지시문으로 또 호출될 때 그 부분의 입력 토큰이 최대 90% 저렴해짐.
//   스키마(input_schema) 자체도 모든 호출에서 완전히 동일하므로 tools 정의에도 동일하게
//   cache_control을 붙여둠 - 사실상 이번 요청에서 진짜 "새로 읽어야 할" 부분은 사용자가
//   붙여넣은 물건 텍스트뿐이라, 캐싱 대상(고정 지시문+스키마)이 프롬프트의 대부분을 차지함.
// 실제 fetch+재시도 로직만 떼어낸 공용 저수준 헬퍼 - callClaude(구조화 추출, tool_choice 강제)와
// callClaudeWebSearch(mode:'taxUpdate' 리서치용, web_search 툴 자동판단) 둘 다 이 함수를 통해
// 요청을 보내고, 응답 파싱(tool_use 꺼내기 vs 텍스트+출처 꺼내기)만 각자 다르게 함.
async function postAnthropicMessages(apiKey, body, attempt) {
  attempt = attempt || 1;
  let claudeRes;
  try {
    // Vercel Hobby maxDuration이 60초라, 여유(파싱·응답조립)를 좀 남기고 55초까지 기다림
    claudeRes = await fetch(ANTHROPIC_MESSAGES_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': ANTHROPIC_API_VERSION,
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(55000),
    });
  } catch (e) {
    if (e.name === 'TimeoutError' || e.name === 'AbortError') {
      throw new Error('AI 분석이 시간 내에 끝나지 못했습니다. 페이지 내용이 너무 길 수 있으니(특히 하단 학교·행정기관·지도 링크 등은 빼고) 필요한 부분만 남겨서 다시 시도해 주세요.');
    }
    throw e;
  }
  const data = await claudeRes.json();
  if (!claudeRes.ok) {
    const errType = data.error?.type || '';
    const msg = data.error?.message || 'Claude API 호출 실패';
    const isOverloaded = claudeRes.status === 529 || errType === 'overloaded_error';
    const isRateLimited = claudeRes.status === 429 || errType === 'rate_limit_error';
    if (isOverloaded && attempt < 5) {
      await sleep(1500 * attempt);
      return postAnthropicMessages(apiKey, body, attempt + 1);
    }
    if (isOverloaded) {
      throw new Error('AI 서버가 일시적으로 혼잡합니다(Anthropic 측 일시적 과부하). 보통 1분 이내에 풀리니, 잠시 후 다시 시도해 주세요.');
    }
    if (isRateLimited) {
      console.error(`parse-auction 429 (attempt ${attempt}):`, msg);
      if (attempt < 3) {
        const base = parseAnthropicRetryDelayMs(claudeRes.headers) ?? (8000 * attempt);
        const jitter = Math.floor(Math.random() * 1500);
        await sleep(base + jitter);
        return postAnthropicMessages(apiKey, body, attempt + 1);
      }
      throw new Error('AI 판독기 요청이 분당 요청수 한도에 계속 걸리고 있습니다. 1분 정도 기다렸다가 다시 시도해 주세요.');
    }
    throw new Error(msg);
  }
  return data;
}
async function callClaude(apiKey, promptInput, schema, imageParts, attempt, temperature) {
  imageParts = imageParts || [];
  temperature = temperature === undefined || temperature === null ? 0 : temperature;
  const jsonSchema = convertGeminiSchemaToJsonSchema(schema);
  const userContent = Array.isArray(promptInput)
    ? promptInput.slice()
    : [{ type: 'text', text: promptInput }];
  if (imageParts.length) userContent.push(...imageParts);
  const data = await postAnthropicMessages(apiKey, {
    model: CLAUDE_MODEL,
    max_tokens: 8192,
    temperature,
    messages: [{ role: 'user', content: userContent }],
    // 구조화된 JSON 출력을 강제하기 위해 tool use를 씀(Gemini의 responseSchema에 대응).
    // tool_choice로 이 도구를 무조건 쓰도록 강제해 일반 텍스트 응답이 섞이지 않게 함.
    // 스키마 자체가 모든 호출에서 동일하므로 cache_control로 캐싱 대상에 포함시킴.
    tools: [{
      name: 'extract_auction_data',
      description: '경매정보지에서 추출한 구조화된 데이터를 담는 도구',
      input_schema: jsonSchema,
      cache_control: { type: 'ephemeral' },
    }],
    tool_choice: { type: 'tool', name: 'extract_auction_data' },
  }, attempt || 1);
  const toolUseBlock = Array.isArray(data.content)
    ? data.content.find((block) => block.type === 'tool_use')
    : null;
  if (!toolUseBlock || !toolUseBlock.input) {
    throw new Error('Claude 응답에서 결과를 찾을 수 없습니다.');
  }
  return toolUseBlock.input;
}
// mode:'taxUpdate' 전용 - Anthropic의 web_search 서버 툴을 붙여서 Claude가 스스로 몇 번이고
// 검색해가며(최대 maxUses회) 답을 만들도록 함. tool_choice를 강제하지 않음(자동 판단) -
// 구조화 출력이 필요한 게 아니라 "찾아서 정리한 리포트"가 목적이라 callClaude와는 다른 경로.
// 반환값: { text: 최종 응답 텍스트(citations 포함), sources: [{title,url}] 중복제거 목록 }
async function callClaudeWebSearch(apiKey, promptText, maxUses) {
  const data = await postAnthropicMessages(apiKey, {
    model: TAX_RESEARCH_MODEL,
    max_tokens: 4096,
    messages: [{ role: 'user', content: [{ type: 'text', text: promptText }] }],
    tools: [{ type: 'web_search_20250305', name: 'web_search', max_uses: maxUses || 8 }],
  }, 1);
  const blocks = Array.isArray(data.content) ? data.content : [];
  const text = blocks.filter((b) => b.type === 'text').map((b) => b.text).join('\n');
  const seen = new Set();
  const sources = [];
  blocks.forEach((b) => {
    if (b.type !== 'web_search_tool_result' || !Array.isArray(b.content)) return;
    b.content.forEach((r) => {
      if (r.type === 'web_search_result' && r.url && !seen.has(r.url)) {
        seen.add(r.url);
        sources.push({ title: r.title || r.url, url: r.url });
      }
    });
  });
  if (!text.trim()) {
    throw new Error('Claude가 검색 결과로 응답을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.');
  }
  return { text, sources };
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
  // ⚠️ Claude 전환 후 imageParts 모양이 Gemini의 { inline_data:{data} }에서
  // Claude의 { type:'image', source:{data} }로 바뀌었는데, 이 함수는 예전 모양만 읽고
  // 있어서 이미지가 있는 요청은 텍스트만으로 캐시 키가 정해지는 버그가 있었음(이미지가
  // 달라도 같은 텍스트면 같은 캐시로 오인될 수 있음) - source.data도 함께 확인하도록 수정.
  (imageParts || []).forEach((p) => {
    const data = p?.inline_data?.data || p?.source?.data;
    if (data) h.update(data);
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
// 하루 사용량 제한 (텍스트/이미지 AI 추출 전용)
// - Claude(Anthropic API)는 Gemini 무료 티어 같은 "하루 요청수(RPD)" 절대 상한이 없음 -
//   사용량 기반 과금 + 분당 롤링 한도(RPM/TPM, 유료 티어라 넉넉함)라서, 이 값은 이제
//   "진짜 기술적 한도"가 아니라 순수하게 "비용 급증 방지용 자체 안전장치"임(예: 스크립트
//   오작동이나 남용으로 하루에 수백~수천 회씩 호출되는 걸 막는 용도). 넉넉하게 하루
//   300회로 잡음 - 기능마다 1건당 호출 횟수가 달라서 "건수"가 아니라 "호출 횟수" 기준으로 셈:
//     - 물건 상세페이지 추출(기본 mode): 1건당 Claude 호출 2회(스키마 A+B)
//     - 낙찰사례 목록 일괄추출(mode:'caseList'): 1건당 Claude 호출 1회
//   즉 물건 추출은 하루 최대 약 150건, caseList 추출은 최대 약 300건까지 가능하고, 섞어
//   써도(예: 물건추출 50건=100회 + caseList 200건=200회 = 300회) 예산을 낭비 없이 다 쓸 수 있음.
//   실사용량이 이 안전한도에 자주 걸리면 값을 더 올리면 됨(비용은 어차피 Anthropic 콘솔에서
//   실사용량 기준으로 별도 청구되므로, 이 값은 "막는 상한선"일 뿐 과금액 자체를 바꾸지 않음).
// - mode:'devNews'(개발호재 검색, 네이버 뉴스API라 Claude와 무관)는 이 예산 대상이 아님.
// - 캐시로 즉시 반환되는 요청(동일 텍스트/이미지를 다시 보내 해시가 같은 경우)은 실제 Claude
//   호출이 없으므로 차감하지 않음 - 이 체크는 캐시 조회(getCachedParseResult) 이후,
//   Claude를 실제로 호출하기 직전에만 수행함.
// - 날짜 기준은 한국 시간(KST, UTC+9) 자정. Upstash Redis에 "그날 사용한 호출 횟수" 키를 두고,
//   그날 첫 차감일 때만 자정까지 남은 시간(+여유 1시간)으로 만료시간을 걸어 다음날 자동 초기화.
// - Redis 설정이 없거나 조회 자체가 실패하면 제한 없이 그냥 진행함(가용성 우선 - 이 기능이
//   고장났다고 AI 추출 자체가 막히면 안 됨).
// ════════════════════════════════════
const DAILY_CLAUDE_CALL_BUDGET = 300;
const CLAUDE_CALLS_PER_PROPERTY_EXTRACT = 2;
const CLAUDE_CALLS_PER_CASELIST_EXTRACT = 1;
// AI 투자 브리핑(mode:'briefing') - 이미 계산된 값들을 한 번만 Claude에 넘겨 자연어로
// 요약하는 기능이라 1건당 1회 호출로 끝남.
const CLAUDE_CALLS_PER_BRIEFING = 1;

function todayKstDateStr() {
  const kst = new Date(Date.now() + 9 * 60 * 60 * 1000);
  return kst.toISOString().slice(0, 10); // YYYY-MM-DD
}

function secondsUntilNextKstMidnight() {
  const now = new Date();
  const kstNow = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  const nextMidnightKst = new Date(Date.UTC(kstNow.getUTCFullYear(), kstNow.getUTCMonth(), kstNow.getUTCDate() + 1));
  const nextMidnightUtcMs = nextMidnightKst.getTime() - 9 * 60 * 60 * 1000;
  return Math.max(60, Math.ceil((nextMidnightUtcMs - now.getTime()) / 1000)) + 3600; // 여유 1시간
}

async function getDailyExtractCount(dateKey) {
  if (!REDIS_URL || !REDIS_TOKEN) return 0;
  try {
    const r = await fetch(`${REDIS_URL}/get/${dateKey}`, {
      headers: { Authorization: `Bearer ${REDIS_TOKEN}` },
      signal: AbortSignal.timeout(3000),
    });
    if (!r.ok) return 0;
    const data = await r.json();
    return data && data.result ? parseInt(data.result, 10) || 0 : 0;
  } catch (e) {
    console.error('일일 추출 카운트 조회 실패:', e.message);
    return 0;
  }
}

// by: 이번에 실제로 소모한 Gemini 호출 횟수(물건추출=2, caseList 추출=1). 기본값 1로 두면
// 예전 호출부(혹시 남아있다면)와도 안전하게 호환됨.
async function incrementDailyExtractCount(dateKey, by) {
  by = by || 1;
  if (!REDIS_URL || !REDIS_TOKEN) return;
  try {
    const r = await fetch(`${REDIS_URL}/incrby/${dateKey}/${by}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${REDIS_TOKEN}` },
      signal: AbortSignal.timeout(3000),
    });
    if (!r.ok) return;
    const data = await r.json();
    if (data && data.result === by) {
      // 이번 호출로 0 → by가 됐다는 건 오늘 첫 차감이었다는 뜻 - 자정 기준 만료시간을 걸어
      // 다음날엔 자동으로 0부터 다시 시작되게 함
      await fetch(`${REDIS_URL}/expire/${dateKey}/${secondsUntilNextKstMidnight()}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${REDIS_TOKEN}` },
        signal: AbortSignal.timeout(3000),
      }).catch(() => {});
    }
  } catch (e) {
    console.error('일일 추출 카운트 증가 실패:', e.message);
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
  // 개발호재 검색(mode:'devNews')은 기존 경매정보지 추출(Claude) 로직과 완전히 별개(네이버 뉴스검색
  // API 사용)라 ANTHROPIC_API_KEY 확인보다 먼저 분기함
  if (req.body && req.body.mode === 'devNews') {
    return handleDevNewsSearch(req, res);
  }
  // 낙찰사례 목록 일괄 추출(지역별 마진 통계용) - 위 devNews와 마찬가지로 기존 상세페이지
  // 추출(SCHEMA_A/B) 로직과는 별개 경로라 먼저 분기함.
  if (req.body && req.body.mode === 'caseList') {
    return handleCaseListExtraction(req, res);
  }
  // AI 투자 브리핑(mode:'briefing') - 물건 추출과 무관하게 이미 계산된 값들을 요약만 하는
  // 별개 경로라 먼저 분기함.
  if (req.body && req.body.mode === 'briefing') {
    return handleBriefing(req, res);
  }
  // 최신 세율 조사 - 물건 데이터와 무관하게 세법 자체를 웹검색으로 조사하는 별개 경로라 먼저
  // 분기함. 60초 함수 시간제한 때문에 리서치(taxUpdateResearch)와 구조화 추출
  // (taxUpdateExtract)을 별도 요청 2번으로 나눔 - 상세 이유는 위 handleTaxUpdateResearch
  // 함수 주석 참고.
  if (req.body && req.body.mode === 'taxUpdateResearch') {
    return handleTaxUpdateResearch(req, res);
  }
  if (req.body && req.body.mode === 'taxUpdateExtract') {
    return handleTaxUpdateExtract(req, res);
  }
  const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY;
  if (!ANTHROPIC_API_KEY) {
    return res.status(500).json({ error: 'ANTHROPIC_API_KEY 환경변수가 없습니다. Vercel 프로젝트 설정에 추가해 주세요.' });
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
        .map((img) => ({ type: 'image', source: { type: 'base64', media_type: img.mimeType || 'image/jpeg', data: img.data } }))
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

  // 캐시에 없어 실제로 Claude를 호출해야 하는 경우에만 하루 사용량 제한을 확인함
  // (캐시 히트는 위에서 이미 반환되어 여기 도달하지 않으므로 카운트에서 자연히 제외됨).
  const dailyKey = `auctionparse_daily_${todayKstDateStr()}`;
  const usedToday = await getDailyExtractCount(dailyKey);
  if (usedToday + CLAUDE_CALLS_PER_PROPERTY_EXTRACT > DAILY_CLAUDE_CALL_BUDGET) {
    return res.status(429).json({
      error: `오늘 AI 자동추출 사용량 안전한도(비용 급증 방지용, 하루 ${DAILY_CLAUDE_CALL_BUDGET}회)에 다 찼습니다. 한국시간 자정에 초기화됩니다. (물건 상세추출은 1건당 2회, 낙찰사례 목록 추출은 1건당 1회를 소모합니다 - 지금까지 ${usedToday}회 사용) 이미 추출했던 물건을 그대로 다시 붙여넣는 건 캐시로 처리돼 소모되지 않습니다.`,
      dailyLimitReached: true,
      usedToday,
      limit: DAILY_CLAUDE_CALL_BUDGET,
    });
  }

  const promptA = buildPrompt(PROMPT_A_RULES, trimmedText);
  const promptB = buildPrompt(PROMPT_B_RULES, trimmedText);

  try {
    // 두 스키마(A/B)를 병렬 호출함 - Claude는 Gemini 무료 티어 같은 RPM/RPD 제약이 없어
    // 굳이 순차 실행하거나 시작 시점을 어긋나게 둘 필요가 없지만, 순간 동시 요청 부담을
    // 살짝 분산시키는 차원에서 700ms 지연은 그대로 유지함.
    const [resultA, resultB] = await Promise.all([
      callClaude(ANTHROPIC_API_KEY, promptA, SCHEMA_A, imageParts, 1, 0),
      sleep(700).then(() => callClaude(ANTHROPIC_API_KEY, promptB, SCHEMA_B, imageParts, 1, 0)),
    ]);
    const merged = { ...resultA, ...resultB };
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
    incrementDailyExtractCount(dailyKey, CLAUDE_CALLS_PER_PROPERTY_EXTRACT); // 실제로 Claude를 새로 호출해 성공한 경우에만 하루 사용량에 반영 (fire-and-forget)
    return res.status(200).json({ detail: merged });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}
