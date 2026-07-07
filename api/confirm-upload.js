import { createClient } from '@supabase/supabase-client';
import Papa from 'papaparse';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY);

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { filePath } = req.body;
  if (!filePath) {
    return res.status(400).json({ error: 'filePath가 누락되었습니다.' });
  }

  try {
    // [검수 수정] download 결과의 키값은 'data'입니다. 이를 fileBlob으로 별칭 지정합니다.
    const { fileBlob, error: downloadError } = await supabase.storage
      .from('csv-uploads')
      .download(filePath);

    if (downloadError) {
      return res.status(500).json({ error: '파일 다운로드 실패: ' + downloadError.message });
    }

    // fileBlob이 존재하는지 한 번 더 체크
    if (!fileBlob) {
      return res.status(500).json({ error: '파일 데이터를 찾을 수 없습니다.' });
    }

    const csvText = await fileBlob.text();

    const parsed = Papa.parse(csvText, {
      header: true,
      skipEmptyLines: true
    });

    const rowsToInsert = parsed.data.map(row => {
      const getV = (name) => {
        const key = Object.keys(row).find(k => k.trim() === name);
        return key ? String(row[key]).trim() : '';
      };

      const toInt = (val) => {
        // [검수 보완] 숫자가 아닌 문자가 들어올 경우를 대비해 더 안전하게 처리
        const cleaned = val.replace(/[^0-9]/g, '');
        return cleaned ? parseInt(cleaned) : 0;
      };

      const sNum = toInt(getV('부번'));
      const ym = getV('계약년월');
      const d = getV('계약일').padStart(2, '0');

      return {
        region: getV('시군구'),
        bunji: getV('지번'),
        road_name: getV('도로명'),
        main_num: toInt(getV('본번')),
        sub_num: sNum === 0 ? null : sNum, // 부번 0 무시 처리
        danji: getV('단지명'),
        floor: toInt(getV('층')),
        // 전용면적 정수화 처리 (84.95 -> 84)
        size: Math.floor(parseFloat(getV('전용면적')) || 0),
        deal_date: (ym && d) ? ym + d : null,
        price: toInt(getV('거래금액(만원)')),
        build_year: toInt(getV('건축년도'))
      };
    });

    const { error: insertError } = await supabase
      .from('real_estate_trades')
      .insert(rowsToInsert);

    if (insertError) {
      return res.status(500).json({ error: 'DB 저장 실패: ' + insertError.message });
    }

    return res.status(200).json({ success: true, count: rowsToInsert.length });

  } catch (error) {
    console.error('Final Catch Error:', error);
    return res.status(500).json({ 
      error: '서버 내부 오류 발생', 
      details: error.message 
    });
  }
}
