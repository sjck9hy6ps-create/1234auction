/* ════════════════════════════════════
   경매정보지(탱크옥션 등) 텍스트 → 구조화된 JSON 추출
   - 클라이언트가 경매 상세페이지에서 복사한 텍스트를 그대로 넘기면
     Gemini API로 필수 항목들을 뽑아서 JSON으로 돌려줍니다.
   - 텍스트에 없는 값은 null로 두도록 프롬프트에 명시 (추측 금지)
════════════════════════════════════ */

const GEMINI_MODEL = 'gemini-3.5-flash';

// Vercel 함수 자체의 실행 제한 시간을 늘림 (기본값은 너무 짧아서, 스키마가 큰 요청은
// Gemini 응답이 오기 전에 함수가 먼저 죽어버릴 수 있음). Hobby 플랜에서도 60초까지 가능.
export const maxDuration = 60;

// Gemini structured output용 응답 스키마 (OpenAPI 서브셋, type은 대문자)
const RESPONSE_SCHEMA = {
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
    tenantOccupants: { type: 'ARRAY', items: { type: 'STRING' } },
    tenantNote: { type: 'STRING' },
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
        },
      },
    },
    riskSummary: { type: 'STRING' },
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

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST only' });

  const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
  if (!GEMINI_API_KEY) {
    return res.status(500).json({ error: 'GEMINI_API_KEY 환경변수가 없습니다. Vercel 프로젝트 설정에 추가해 주세요.' });
  }

  const { text } = req.body || {};
  if (!text || !String(text).trim()) {
    return res.status(400).json({ error: '분석할 텍스트가 없습니다.' });
  }

  const prompt = `다음은 경매정보 사이트(탱크옥션 등)에서 복사한 물건 "상세페이지" 텍스트입니다.
이 페이지에는 본문(이 물건 자체의 정보) 외에도 하단에 "인근물건자료", "인근진행정보", "인근매각사례",
"동일지번매각", "인근반경검색", "인근공매진행", "경매최근열람" 같은 섹션이 있는데, 여기 나열된 사건번호나
주소는 전부 이 물건과 무관한 "다른" 물건들입니다. 반드시 페이지 맨 위 제목 줄
(예: "경매 2025타경52046" 처럼 "경매"라는 단어 바로 뒤에 나오는 사건번호 하나)에 있는 정보만
이 물건의 정보로 사용하고, 하단 목록/사이드바에 나오는 다른 사건번호·주소는 절대 사용하지 마세요.

규칙:
- 텍스트에 명시되지 않은 값은 null(배열은 빈 배열)로 두세요. 절대 추측하거나 지어내지 마세요.
- caseNo는 페이지 맨 위 제목에 있는 사건번호 단 하나만 쓰세요 (예: "2025타경52046"). 하단 관련물건 목록의 번호는 무시하세요.
- 금액은 원 단위 숫자로 변환하세요 (예: "1억 3,300만" → 133000000, "9,310,000" → 9310000).
- 날짜는 가능하면 YYYY-MM-DD 형식으로 변환하세요.
- addrJibun은 이 물건의 지번주소 전체(층/호수 포함 가능, 예: "경기도 안산시 상록구 본오동 718-12 2층202호")를 그대로 담으세요.
- dong(동)과 bunji(번지)는 addrJibun에서 "동"과 "번지" 부분만 따로 뽑으세요.
  예: "경기도 안산시 상록구 본오동 718-12 2층202호" → dong: "본오동", bunji: "718-12"
  (시/도/구 이름이나 층수·호수는 dong·bunji에 포함하지 마세요. 번지에 "-"로 이어진 본번-부번은 그대로 유지하세요.)
- rounds(입찰 회차 이력)는 표에 나온 순서대로 모두 담으세요.
- registryItems(건물등기)는 접수일 순서대로 모두 담으세요.
- officialTrades(국토부 실거래가)는 표에 나온 개별 거래를 모두 담으세요.
- salesStats는 "최근1개월/3개월/6개월/12개월" 각 구간의 평균감정가/평균매각가/평균매각가율/평균입찰인수/예상매각가를 한 문장으로 요약해서 m1/m3/m6/m12에 넣으세요.
- officialPriceByYear는 연도별 공시가격을 "2021년 8,790만 / 2022년 8,930만 / ..." 같은 한 줄 텍스트로 요약하세요.

--- 텍스트 시작 ---
${text}
--- 텍스트 끝 ---`;

  try {
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}`;
    const geminiRes = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: {
          responseMimeType: 'application/json',
          responseSchema: RESPONSE_SCHEMA,
        },
      }),
      signal: AbortSignal.timeout(55000),
    });
    const data = await geminiRes.json();
    if (!geminiRes.ok) {
      return res.status(502).json({ error: data.error?.message || 'Gemini API 호출 실패' });
    }
    const jsonText = data.candidates?.[0]?.content?.parts?.[0]?.text;
    if (!jsonText) {
      return res.status(502).json({ error: 'Gemini 응답에서 결과를 찾을 수 없습니다.' });
    }
    const parsed = JSON.parse(jsonText);
    return res.status(200).json({ detail: parsed });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}
