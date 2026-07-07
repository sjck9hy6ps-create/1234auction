import { createClient } from '@supabase/supabase-client';
import Papa from 'papaparse';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY);

export default async function handler(req, res) {
  // 1. 요청 방식 확인
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { filePath } = req.body;
  if (!filePath) {
    return res.status(400).json({ error: 'filePath가 누락되었습니다.' });
  }

  try {
    // 2. Storage에서 파일 다운로드
    const { fileBlob, error: downloadError } = await supabase.storage
      .from('csv-uploads')
      .download(filePath);

    if (downloadError) {
      return res.status(500).json({ error: '파일 다운로드 실패: ' + downloadError.message });
    }

    // 3. Blob을 텍스트로 변환 (가장 표준적인 방식)
    const csvText = await fileBlob.text();

    // 4. CSV 파싱
    const parsed = Papa.parse(csvText, {
      header: true,
      skipEmptyLines: true
    });

    // 5. 데이터 매핑 (parsed.data가 실제 배열입니다)
    const rowsToInsert = parsed.data.map(row => {
      const getV = (name) => {
        const key = Object.keys(row).find(k => k.trim() === name);
        return key ? String(row[key]).trim() : '';
      };

      const toInt = (val) => {
        const cleaned = val.replace(/[^0-9]/g, '');
        return parseInt(cleaned) || 0;
      };

      // 부번 로직 (0이면 null)
      const sNum = toInt(getV('부번'));
      
      // 날짜 로직
      const ym = getV('계약년월');
      const d = getV('계약일').padStart(2, '0');

      return {
        region: getV('시군구'),
        bunji: getV('지번'),
        road_name: getV('도로명'),
        main_num: toInt(getV('본번')),
        sub_num: sNum === 0 ? null : sNum,
        danji: getV('단지명'),
        floor: toInt(getV('층')),
        size: Math.floor(parseFloat(getV('전용면적')) || 0),
        deal_date: (ym && d) ? ym + d : null,
        price: toInt(getV('거래금액(만원)')),
        build_year: toInt(getV('건축년도'))
      };
    });

    // 6. DB Insert
    const { error: insertError } = await supabase
      .from('real_estate_trades')
      .insert(rowsToInsert);

    if (insertError) {
      return res.status(500).json({ error: 'DB 저장 실패: ' + insertError.message });
    }

    return res.status(200).json({ success: true, count: rowsToInsert.length });

  } catch (error) {
    // 여기서 발생하는 모든 에러를 JSON으로 반환하도록 강제
    return res.status(500).json({ 
      error: '서버 내부 오류 발생', 
      details: error.message 
    });
  }
}
