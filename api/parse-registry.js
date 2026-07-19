/* ════════════════════════════════════
   경매서류 교차분석: 등기부등본 · 매각물건명세서 · 전입세대확인서
   - 최대 3종의 PDF를 Supabase Storage("registry-docs" 버킷)에 원본 그대로 영구 저장
   - Gemini에 PDF를 직접 첨부(inline_data)해서 세 서류를 서로 대조하며
     건물 이력을 시간순 스토리로 설명 + 경매 매수 관점 리스크
     (임차인 대항력, 말소기준등기, 낙찰 후 인수/말소되는 등기 등) 분석
   - 3종 모두 필수는 아님 - 등기부등본만 올려도 분석되지만(구버전과 동일 동작),
     매각물건명세서·전입세대확인서를 함께 올리면 서로 다른 자료 출처를 교차검증할 수
     있어서 특히 "임차인이 실제로 전입돼 있는가", "매각물건명세서상 임차인현황과
     전입세대확인서가 일치하는가" 같은 판단의 신뢰도가 크게 올라감
   - ⚠️ 법률 자문이 아닌 참고용 자동 요약이라는 점을 프롬프트/응답 모두에 명시

   사전 준비 (근수님이 직접 해주셔야 함):
   1) Supabase 대시보드 → Storage → New bucket
      이름: registry-docs / Public bucket 체크(원본 파일을 링크로 바로
      볼 수 있게 하려면 Public으로, 비공개로 하고 싶으면 Private으로 만들고
      추후 signed URL 방식으로 바꿀 수 있습니다 - 지금 코드는 Public 기준)
   2) 기존 환경변수 그대로 사용: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
      GEMINI_API_KEY (전부 이미 등록되어 있음)
════════════════════════════════════ */
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);
const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const GEMINI_MODEL = 'gemini-3.5-flash';
const BUCKET = 'registry-docs';

export const config = {
  // ⚠️ Vercel 서버리스 함수는 플랫폼 자체에서도 요청 본문 크기 제한이 걸려있어서,
  // 여기 sizeLimit을 올려도 무한정 큰 파일을 받을 수는 없음. 프론트엔드에서
  // 서류를 2개 이상 동시에 올릴 때는 합쳐서 15MB 이내로 제한해두었으므로
  // (base64 인코딩 시 원본의 약 1.37배가 됨) 그보다 여유 있게 24mb로 설정함.
  api: { bodyParser: { sizeLimit: '24mb' } },
};
export const maxDuration = 58;

const DOC_LABELS = {
  registry: '등기부등본(부동산 등기사항증명서)',
  saleStatement: '매각물건명세서(법원경매정보에서 발급하는 매각물건명세서)',
  residentCert: '전입세대확인서(전입세대열람내역, 주민센터 발급)',
};

const RIGHT_ITEM_SCHEMA = {
  type: 'OBJECT',
  properties: {
    right: { type: 'STRING', description: '권리 종류 (예: "근저당권", "가압류", "선순위 임차인의 임차권" 등)' },
    date: { type: 'STRING', description: '등기/전입/확정일자 등 기준일자 (예: "2019.03.15")' },
    holder: { type: 'STRING', description: '권리자 이름 또는 소속 (예: "OO은행", "임차인 김OO")' },
    note: { type: 'STRING', description: '왜 인수/말소로 판단했는지, 근거가 된 서류·조항을 간단히 설명' },
  },
  required: ['right'],
};

const RISK_SCHEMA = {
  type: 'OBJECT',
  properties: {
    summary: { type: 'STRING', description: '전체 위험도에 대한 한 줄 총평 (예: "임차인 대항력 충돌 가능성이 있어 주의가 필요한 물건")' },
    approvalDate: { type: 'STRING', description: '건물 사용승인일. 이미 알고 있는 값(knownApprovalDate)이 주어졌으면 그 값을 그대로 사용하고, 없으면 첨부된 서류에서 확인되는 값을, 그마저 없으면 빈 문자열로 둘 것.' },
    auctionReason: { type: 'STRING', description: '누가(채권자) 어떤 근거(예: 대여금 미상환에 따른 근저당권 실행, 확정판결에 따른 강제경매 등)로 경매를 신청하게 됐는지 1~2문장 요약' },
    story: { type: 'STRING', description: '건물 사용승인부터 지금까지의 소유권 변동, 근저당권/가압류/압류/가등기/가처분/신탁 등 주요 권리 변동, 그리고 채권자가 어떤 관계로 이 건물에 얽혔고 왜 경매를 신청하게 됐는지를 시간순으로 쉬운 말로 스토리텔링하듯 설명. 등기 전문용어는 일반인이 이해할 수 있게 짧게 풀어서 설명(예: "근저당권 설정 = OO은행에서 돈을 빌리면서 이 집을 담보로 잡았다는 뜻"). 첨부된 서류가 여러 개면 서로 대조해서 나온 내용도 자연스럽게 녹여 설명할 것.' },
    survivingRights: {
      type: 'ARRAY',
      description: '말소기준등기보다 선순위이거나 별도 사유로 소멸하지 않아, 낙찰 후 매수인이 그대로 인수해야 하는 권리 목록. 없으면 빈 배열.',
      items: RIGHT_ITEM_SCHEMA,
    },
    extinguishedRights: {
      type: 'ARRAY',
      description: '말소기준등기를 기준으로 매각과 동시에 소멸(말소)되는 권리 목록. 없으면 빈 배열.',
      items: RIGHT_ITEM_SCHEMA,
    },
    risks: {
      type: 'ARRAY',
      description: '경매 매수자 관점에서 확인한 위험요소 목록. 위험이 특별히 없다면 빈 배열이 아니라 "특이 위험 없음" 항목 하나를 낮음 등급으로 넣을 것.',
      items: {
        type: 'OBJECT',
        properties: {
          level: { type: 'STRING', enum: ['높음', '중간', '낮음'] },
          title: { type: 'STRING', description: '위험요소 제목 (예: "선순위 임차인 대항력 충돌 가능성")' },
          desc: { type: 'STRING', description: '왜 위험한지, 첨부 서류의 어떤 내용에 근거했는지 구체적 설명' },
        },
        required: ['level', 'title', 'desc'],
      },
    },
    malsoGijunRight: { type: 'STRING', description: '말소기준등기(=말소기준권리)로 추정되는 권리와 설정일자 (예: "2019.03.15 설정된 근저당권(OO은행)"). 특정이 어려우면 "서류만으로는 특정이 어려움"이라고 답할 것.' },
  },
  required: ['summary', 'story', 'risks'],
};

function buildPrompt({ providedTypes, knownApprovalDate }) {
  const docListText = providedTypes.map((t, i) => `${i + 1}. ${DOC_LABELS[t]}`).join('\n');
  const missingTypes = Object.keys(DOC_LABELS).filter((t) => !providedTypes.includes(t));
  const missingText = missingTypes.length
    ? `\n\n※ 다음 서류는 이번에 첨부되지 않았습니다: ${missingTypes.map((t) => DOC_LABELS[t]).join(', ')}. 이 서류들의 내용은 절대로 추측하지 말고, 확인이 필요하다는 점만 story나 risks에 짧게 언급하세요.`
    : '';
  const knownDateText = knownApprovalDate
    ? `\n\n참고: 이 건물의 사용승인일은 이미 "${knownApprovalDate}"로 확인되어 있습니다. approvalDate와 story에서는 이 값을 그대로 사용하고, 서류에서 다른 값이 보이더라도 이 값을 우선하세요.`
    : '';

  return `당신은 한국 부동산 경매 매수를 검토하는 투자자를 돕는 보조 분석가입니다.
아래 서류가 순서대로 첨부되어 있습니다(각 문서 앞에 어떤 서류인지 라벨을 붙여뒀습니다).
${docListText}${missingText}${knownDateText}

첨부된 서류를 모두 읽고 서로 대조하면서 아래 작업을 수행하세요. 특히 매각물건명세서에
적힌 임차인현황(전입일·확정일자·배당요구 여부)과 전입세대확인서에 실제로 나타나는
전입 내역이 서로 일치하는지, 등기부등본에 나온 권리들과 매각물건명세서의 "최선순위
설정일자"·"등기된 권리" 항목이 서로 맞는지를 반드시 교차검증하세요.

1. approvalDate: 건물 사용승인일. (참고 값이 주어졌다면 그 값을 그대로 사용)

2. auctionReason: 채권자가 누구이고 이 건물과 어떤 관계(근저당권자/가압류권자/전세권자/
   확정판결 채권자 등)인지, 어떤 사유(대여금 미상환에 따른 근저당권 실행, 확정판결에
   따른 강제경매 신청 등)로 경매를 신청하게 됐는지 1~2문장으로 요약하세요.

3. story: 건물이 언제 사용승인을 받았고, 소유권이 어떻게 변동돼왔고(보존등기부터
   현재까지), 채권자가 이 건물과 어떤 관계를 맺게 됐으며, 그 채권자가 어떤 이유로
   누구를 상대로 경매를 신청하게 됐는지를 시간순으로 자연스럽게 풀어쓴 스토리텔링
   설명으로 작성하세요. 등기 전문용어가 나오면 일반인이 이해할 수 있게 짧게 풀어서
   설명하세요. 여러 서류를 대조해서 알게 된 사실(예: "매각물건명세서상 임차인 김OO의
   전입일이 전입세대확인서에서도 확인됨" 또는 "확인되지 않아 대항력을 단정할 수 없음")도
   자연스럽게 포함하세요.
   ⚠️ story 안에는 반드시 "말소기준등기가 무엇이고(권리 종류+설정일), 이를 기준으로
   어떤 등기는 소멸하고 어떤 등기는 매수인이 인수하는지"를 명확한 문단으로 강조해서
   설명하세요. 아래 [말소기준등기 판단 기준]의 무조건 인수 항목에 해당하는 것이
   하나라도 있으면 story 마지막에 "⚠️ 입찰 전 반드시 확인" 같은 표현으로 눈에 띄게
   경고하세요.

[말소기준등기 판단 기준] - 이 기준을 정확히 적용해서 survivingRights/extinguishedRights/
malsoGijunRight/risks를 채우세요 (근거: 민사집행법 제91조·제144조, 가등기담보법 제15조).
- 말소기준등기 = (근)저당권 · (가)압류 · 담보가등기 · 경매개시결정등기 ·
  전세권(배당요구 또는 임의경매신청) 중 등기일자가 가장 빠른 것.
- 말소기준등기보다 먼저(선순위) 등기된 권리는 원칙적으로 매수인 인수, 그 이후(후순위)
  등기된 권리는 원칙적으로 매각과 동시에 말소.
- ⚠️ 등기 순서·말소기준등기와 무관하게 "무조건 매수인에게 인수"되는 권리 (반드시
  survivingRights에 포함하고 risks에도 "높음"으로 별도 표시):
  · 유치권 (성립 요건 충족 시)
  · 법정지상권, 분묘기지권
  · 토지소유자가 지상건물 소유자를 상대로 한 처분금지가처분(건물철거·토지인도 청구)
- 판단이 까다로운 것 (서류에서 근거를 찾되, 확실하지 않으면 risks에 "판단 불확실"로 표시):
  · 가등기는 등기부에 "매매예약"으로만 표기되어 담보가등기(말소기준권리가 될 수 있음)인지
    순위보전가등기(선순위면 인수)인지 등기부만으로 구분되지 않음 - 배당요구 여부로 추정.
  · 전세권은 배당요구 시 말소기준권리가 되어 소멸하지만, 배당요구를 했어도 보증금을
    전액 배당받지 못하면 그 잔액은 대항력 있는 임차인 지위로 매수인에게 인수될 수 있음
    (전세권자와 임차인이 동일인인 경우의 대법원 판례).
  · 대항력만 갖추고 우선변제권(확정일자)이 없는 임차권은 배당 자체가 불가능해 보증금
    전액이 매수인에게 인수됨.
- 소액임차인 최우선변제 판단 기준일은 "임차인 전입일"이 아니라 "말소기준등기(주로
  최선순위 근저당) 설정일"이며, 그 설정일 당시 시행되던 지역별 공고금액표를 기준으로
  판단해야 함 - 서류에 그 근거가 없으면 risks에 확인 필요 항목으로 남기세요.
- 임차인이 있는 물건이라면, 임차인이 전세사기피해자로 인정될 경우 LH 등 공공주택사업자가
  낙찰가와 동일한 금액으로 우선매수권을 행사하거나 경·공매 유예·정지를 신청할 수 있는
  제도(전세사기피해자 지원 특별법)가 있다는 점도 risks에 참고 항목으로 짧게 언급하세요
  (이건 등기부만으로 확인되는 사실은 아니므로 "가능성 있음" 수준으로만 언급).

4. survivingRights / extinguishedRights: 위 [말소기준등기 판단 기준]에 따라, 낙찰 후에도
   소멸하지 않고 매수인이 그대로 인수해야 하는 권리(survivingRights)와 매각과 동시에
   소멸하는 권리(extinguishedRights)를 각각 목록으로 나누어 정리하세요. "무조건 인수"
   항목(유치권/법정지상권/분묘기지권/토지소유자의 처분금지가처분)이 있다면 note에
   "등기 순서와 무관하게 무조건 인수됨"이라고 명시하세요.

5. risks: 경매로 이 물건을 낙찰받으려는 사람 입장에서 반드시 확인해야 할 위험요소를
   분석하세요. 특히 아래 관점을 중점적으로 살펴보세요.
   - 말소기준등기보다 선순위 권리, 또는 순서와 무관한 "무조건 인수" 권리가 있어
     매수인이 인수해야 할 가능성 (있다면 반드시 "높음"으로 표시)
   - 매각물건명세서상 임차인현황과 전입세대확인서 실제 전입 내역의 불일치 여부
   - 근저당/가압류/압류가 여러 건 겹쳐 있어 배당 관계가 복잡한지
   - 가등기, 가처분, 신탁등기 등 소유권 자체에 영향을 줄 수 있는 특수한 권리
   - 소유권이 짧은 기간 안에 여러 번 바뀌었는지(단기 전매, 이상 거래 정황)
   - 임차인이 있다면 소액임차인 최우선변제/전세사기피해자 우선매수권 관련 확인사항
   각 위험요소마다 어느 서류의 어느 부분(갑구/을구, 순위번호, 날짜, 임차인현황 등)에
   근거했는지 구체적으로 밝히세요. 위험도는 높음/중간/낮음 중 하나로 표시하세요.
   특별한 위험이 없다면 "특이 위험 없음"으로 낮음 등급 항목을 하나 넣으세요.

6. malsoGijunRight: 말소기준등기(=말소기준권리)로 추정되는 권리와 설정일자를 밝히세요.
   확실하지 않으면 그렇게 답하세요.

중요: 이것은 법률 자문이 아닌 자동 요약 참고자료입니다. 실제 입찰 결정은 반드시
법무사·변호사 등 전문가의 권리분석을 거쳐야 한다는 점을 story 마지막에 반드시
한 문장으로 언급하세요. 모든 응답은 한국어로 작성하세요.`;
}

async function uploadOne(buffer, auctionId, type, fileName) {
  const safeName = String(fileName).replace(/[^\w.\-가-힣]/g, '_');
  const path = `${auctionId || 'temp'}/${Date.now()}_${type}_${safeName}`;
  const { error: upErr } = await supabase.storage.from(BUCKET).upload(path, buffer, {
    contentType: 'application/pdf',
    upsert: true,
  });
  if (upErr) {
    throw new Error(`${DOC_LABELS[type]} 업로드 실패: ${upErr.message} ("registry-docs" 버킷이 Supabase Storage에 생성되어 있는지 확인해 주세요.)`);
  }
  const { data: urlData } = supabase.storage.from(BUCKET).getPublicUrl(path);
  return { url: urlData?.publicUrl || null, fileName: safeName };
}

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST 요청만 지원합니다.' });

  // 구버전 프론트엔드(단일 등기부등본, fileBase64/fileName)와도 호환되도록 처리
  const body = req.body || {};
  let docsInput = body.docs;
  if (!docsInput && body.fileBase64 && body.fileName) {
    docsInput = { registry: { fileBase64: body.fileBase64, fileName: body.fileName } };
  }
  const { auctionId, knownApprovalDate } = body;

  if (!docsInput || typeof docsInput !== 'object') {
    return res.status(400).json({ error: 'docs가 필요합니다 (등기부등본/매각물건명세서/전입세대확인서 중 최소 1개).' });
  }
  const providedTypes = Object.keys(DOC_LABELS).filter((t) => docsInput[t] && docsInput[t].fileBase64 && docsInput[t].fileName);
  if (!providedTypes.length) {
    return res.status(400).json({ error: '최소 1개 이상의 서류(fileBase64, fileName)가 필요합니다.' });
  }
  if (!GEMINI_API_KEY) return res.status(500).json({ error: 'GEMINI_API_KEY 환경변수가 없습니다.' });

  try {
    // ── 1. Supabase Storage에 원본 PDF들을 영구 저장 ──
    const savedDocs = {};
    const geminiParts = [];
    for (const type of providedTypes) {
      const { fileBase64, fileName } = docsInput[type];
      const buffer = Buffer.from(fileBase64, 'base64');
      savedDocs[type] = await uploadOne(buffer, auctionId, type, fileName);
      geminiParts.push({ text: `[첨부 서류: ${DOC_LABELS[type]}]` });
      geminiParts.push({ inline_data: { mime_type: 'application/pdf', data: fileBase64 } });
    }

    // ── 2. Gemini에 PDF들을 직접 첨부해서 교차분석 요청 ──
    const prompt = buildPrompt({ providedTypes, knownApprovalDate });
    const geminiRes = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{
            parts: [{ text: prompt }, ...geminiParts],
          }],
          generationConfig: {
            responseMimeType: 'application/json',
            responseSchema: RISK_SCHEMA,
            thinkingConfig: { thinkingLevel: 'low' },
          },
        }),
        signal: AbortSignal.timeout(55000),
      }
    );
    const geminiData = await geminiRes.json();
    const text = geminiData?.candidates?.[0]?.content?.parts?.[0]?.text;
    if (!text) {
      return res.status(500).json({
        error: 'AI 분석에 실패했습니다.',
        docs: savedDocs,
        geminiRaw: JSON.stringify(geminiData).slice(0, 1000),
      });
    }
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch (e) {
      return res.status(500).json({ error: 'AI 응답을 해석하지 못했습니다.', docs: savedDocs, rawText: text.slice(0, 1000) });
    }

    return res.status(200).json({
      docs: savedDocs,
      summary: parsed.summary || '',
      approvalDate: parsed.approvalDate || knownApprovalDate || '',
      auctionReason: parsed.auctionReason || '',
      story: parsed.story || '',
      survivingRights: Array.isArray(parsed.survivingRights) ? parsed.survivingRights : [],
      extinguishedRights: Array.isArray(parsed.extinguishedRights) ? parsed.extinguishedRights : [],
      risks: Array.isArray(parsed.risks) ? parsed.risks : [],
      malsoGijunRight: parsed.malsoGijunRight || '',
    });
  } catch (err) {
    console.error('경매서류 교차분석 에러:', err.message);
    if (err.name === 'TimeoutError' || err.name === 'AbortError') {
      return res.status(500).json({ error: 'AI 분석 시간이 초과되었습니다. 파일이 너무 크거나 페이지 수가 많을 수 있습니다. 서류 수를 줄여서 다시 시도해 보세요.' });
    }
    return res.status(500).json({ error: err.message });
  }
}
