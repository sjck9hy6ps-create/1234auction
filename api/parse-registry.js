/* ════════════════════════════════════
   등기부등본 PDF 업로드 + AI 스토리텔링/리스크 분석
   - PDF를 Supabase Storage("registry-docs" 버킷)에 원본 그대로 영구 저장
   - Gemini에 PDF를 직접 첨부(inline_data)해서 이력을 시간순 스토리로 설명 +
     경매 매수 관점 리스크(임차인 대항력, 말소기준권리, 인수되는 권리 등) 분석
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
  api: { bodyParser: { sizeLimit: '12mb' } },
};
export const maxDuration = 58;

const RISK_SCHEMA = {
  type: 'OBJECT',
  properties: {
    summary: { type: 'STRING', description: '전체 위험도에 대한 한 줄 총평 (예: "임차인 대항력 충돌 가능성이 있어 주의가 필요한 물건")' },
    story: { type: 'STRING', description: '등기부등본에 기록된 소유권/권리 변동 이력을 시간순으로 자연스럽게 풀어쓴 스토리텔링 설명 (전문용어는 풀어서 설명)' },
    risks: {
      type: 'ARRAY',
      description: '경매 매수자 관점에서 확인한 위험요소 목록. 위험이 특별히 없다면 빈 배열이 아니라 "특이 위험 없음" 항목 하나를 낮음 등급으로 넣을 것.',
      items: {
        type: 'OBJECT',
        properties: {
          level: { type: 'STRING', enum: ['높음', '중간', '낮음'] },
          title: { type: 'STRING', description: '위험요소 제목 (예: "선순위 임차인 대항력 충돌 가능성")' },
          desc: { type: 'STRING', description: '왜 위험한지, 등기부등본의 어떤 내용에 근거했는지 구체적 설명' },
        },
        required: ['level', 'title', 'desc'],
      },
    },
    malsoGijunRight: { type: 'STRING', description: '확인 가능하다면 말소기준권리로 추정되는 권리와 그 설정일자 (예: "2019.03.15 설정된 근저당권(OO은행)"). 등기부등본만으로 특정이 어려우면 "등기부등본만으로는 특정이 어려움" 이라고 답할 것.' },
  },
  required: ['summary', 'story', 'risks'],
};

const PROMPT = `당신은 한국 부동산 경매 매수를 검토하는 투자자를 돕는 보조 분석가입니다.
첨부된 PDF는 등기부등본(부동산 등기사항증명서)입니다. 이 문서를 읽고 아래 작업을 수행하세요.

1. story: 소유권보존등기부터 지금까지의 소유권 변동, 근저당권/가압류/압류/가등기/가처분/신탁 등
   주요 권리 변동 이력을 시간순으로 쉬운 말로 스토리텔링하듯 설명하세요. 등기 전문용어가
   나오면 일반인이 이해할 수 있게 짧게 풀어서 설명하세요 (예: "근저당권 설정 = OO은행에서
   돈을 빌리면서 이 집을 담보로 잡았다는 뜻").

2. risks: 경매로 이 물건을 낙찰받으려는 사람 입장에서 반드시 확인해야 할 위험요소를
   분석하세요. 특히 아래 관점을 중점적으로 살펴보세요.
   - 말소기준권리보다 앞서 설정된(선순위) 권리가 있어 낙찰 후에도 소멸하지 않고
     매수인이 인수해야 할 가능성이 있는지
   - 근저당/가압류/압류가 여러 건 겹쳐 있어 배당 관계가 복잡한지
   - 가등기, 가처분, 신탁등기 등 소유권 자체에 영향을 줄 수 있는 특수한 권리가 있는지
   - 소유권이 짧은 기간 안에 여러 번 바뀌었는지(단기 전매, 이상 거래 정황)
   각 위험요소마다 등기부등본의 어느 부분(갑구/을구, 순위번호, 날짜)에 근거했는지
   구체적으로 밝히세요. 위험도는 높음/중간/낮음 중 하나로 표시하세요.
   특별한 위험이 없다면 "특이 위험 없음"으로 낮음 등급 항목을 하나 넣으세요.

3. malsoGijunRight: 등기부등본에 나온 권리들 중 말소기준권리로 추정되는 것을 찾아
   권리 종류와 설정일자를 밝히세요. 확실하지 않으면 그렇게 답하세요.

중요: 이것은 법률 자문이 아닌 자동 요약 참고자료입니다. 실제 입찰 결정은 반드시
법무사·변호사 등 전문가의 권리분석을 거쳐야 한다는 점을 story 마지막에 반드시
한 문장으로 언급하세요. 모든 응답은 한국어로 작성하세요.`;

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST 요청만 지원합니다.' });

  const { fileBase64, fileName, auctionId } = req.body || {};
  if (!fileBase64 || !fileName) {
    return res.status(400).json({ error: 'fileBase64, fileName이 필요합니다.' });
  }
  if (!GEMINI_API_KEY) return res.status(500).json({ error: 'GEMINI_API_KEY 환경변수가 없습니다.' });

  try {
    // ── 1. Supabase Storage에 원본 PDF 영구 저장 ──
    const buffer = Buffer.from(fileBase64, 'base64');
    const safeName = String(fileName).replace(/[^\w.\-가-힣]/g, '_');
    const path = `${auctionId || 'temp'}/${Date.now()}_${safeName}`;
    const { error: upErr } = await supabase.storage.from(BUCKET).upload(path, buffer, {
      contentType: 'application/pdf',
      upsert: true,
    });
    if (upErr) {
      return res.status(500).json({ error: '파일 업로드 실패: ' + upErr.message + ' ("registry-docs" 버킷이 Supabase Storage에 생성되어 있는지 확인해 주세요.)' });
    }
    const { data: urlData } = supabase.storage.from(BUCKET).getPublicUrl(path);
    const fileUrl = urlData?.publicUrl || null;

    // ── 2. Gemini에 PDF 직접 첨부해서 분석 요청 ──
    const geminiRes = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{
            parts: [
              { text: PROMPT },
              { inline_data: { mime_type: 'application/pdf', data: fileBase64 } },
            ],
          }],
          generationConfig: {
            responseMimeType: 'application/json',
            responseSchema: RISK_SCHEMA,
            thinkingConfig: { thinkingLevel: 'low' },
          },
        }),
        signal: AbortSignal.timeout(50000),
      }
    );
    const geminiData = await geminiRes.json();
    const text = geminiData?.candidates?.[0]?.content?.parts?.[0]?.text;
    if (!text) {
      return res.status(500).json({
        error: 'AI 분석에 실패했습니다.',
        fileUrl,
        geminiRaw: JSON.stringify(geminiData).slice(0, 1000),
      });
    }
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch (e) {
      return res.status(500).json({ error: 'AI 응답을 해석하지 못했습니다.', fileUrl, rawText: text.slice(0, 1000) });
    }

    return res.status(200).json({
      fileUrl,
      fileName: safeName,
      summary: parsed.summary || '',
      story: parsed.story || '',
      risks: Array.isArray(parsed.risks) ? parsed.risks : [],
      malsoGijunRight: parsed.malsoGijunRight || '',
    });
  } catch (err) {
    console.error('등기부등본 분석 에러:', err.message);
    if (err.name === 'TimeoutError' || err.name === 'AbortError') {
      return res.status(500).json({ error: 'AI 분석 시간이 초과되었습니다. 파일이 너무 크거나 페이지 수가 많을 수 있습니다.' });
    }
    return res.status(500).json({ error: err.message });
  }
}
