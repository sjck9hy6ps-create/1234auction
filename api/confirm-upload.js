import { createClient } from '@supabase/supabase-js';
import Papa from 'papaparse';

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY 
);

const BUCKET = 'uploads';

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { key } = req.body; // filename은 사용하지 않으므로 key만 받아도 충분합니다.
  if (!key) return res.status(400).json({ error: 'key is required' });

  try {
    // 1. Storage에서 파일 다운로드 (변수명 수정: fileData -> data)
    const { data, error: downloadError } = await supabase.storage
      .from(BUCKET)
      .download(key);

    if (downloadError) throw downloadError;

    // 2. CSV 파싱
    const csvText = await data.text();
    const parsed = Papa.parse(csvText, {
      header: true,
      skipEmptyLines: true
    });

    // 3. 데이터 가공 (유연하게 헤더 찾기)
    const rowsToInsert = parsed.data.map(row => {
      // 키 이름에서 공백이나 특수문자를 제거하는 함수
      const getVal = (possibleNames) => {
        for (const name of possibleNames) {
          // 실제 row의 키들 중 name을 포함하는 것이 있는지 확인
          const actualKey = Object.keys(row).find(k => k.trim().includes(name));
          if (actualKey && row[actualKey]) return row[actualKey];
        }
        return null;
      };

      return {
        city: getVal(['시군구']),
        danji: getVal(['단지명', '아파트명']),
        size: parseFloat(String(getVal(['전용면적', '면적'])).replace(/,/g, '')) || 0,
        price: parseInt(String(getVal(['거래금액', '가격'])).replace(/,/g, '')) || 0,
        deal_date: getVal(['계약년월일']) || (getVal(['계약년월']) + getVal(['계약일'])),
        raw_row: row 
      };
    });

    // 4. DB 삽입 (변수명 수정: insertData -> error만 확인해도 됨)
    const { error: insertError } = await supabase
      .from('real_estate_trades')
      .insert(rowsToInsert);

    if (insertError) throw insertError;

    return res.status(200).json({
      success: true,
      message: `${rowsToInsert.length}행의 데이터를 DB에 저장했습니다.`
    });

  } catch (err) {
    console.error('Error details:', err);
    return res.status(500).json({ error: err.message });
  }
}
