import { createClient } from '@supabase/supabase-client';
import Papa from 'papaparse';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY);

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { filePath } = req.body;

  try {
    const { fileData, error: downloadError } = await supabase.storage
      .from('csv-uploads')
      .download(filePath);

    if (downloadError) throw downloadError;

    const csvText = await fileData.text();
    // Papa.parse의 결과는 'data'라는 이름으로 구조분해 할당해야 합니다.
    const { parsedRows } = Papa.parse(csvText, { header: true, skipEmptyLines: true });

    const rowsToInsert = parsedRows.map(row => {
      // 헬퍼 함수들을 map 내부에서 안전하게 정의
      const getV = (name) => {
        const key = Object.keys(row).find(k => k.trim() === name);
        return key ? row[key] : '';
      };

      const toInt = (val) => {
        const cleaned = String(val || '0').replace(/[^0-9]/g, '');
        return parseInt(cleaned) || 0;
      };

      // 부번 로직: 0이면 null, 아니면 숫자
      const rawSubNum = toInt(getV('부번'));
      const finalSubNum = rawSubNum === 0 ? null : rawSubNum;

      // 날짜 로직
      const ym = String(getV('계약년월') || '').trim();
      const d = String(getV('계약일') || '').trim().padStart(2, '0');
      const finalDate = (ym && d) ? ym + d : null;

      // 면적 로직: 소수점 버리고 정수로
      const finalSize = Math.floor(parseFloat(String(getV('전용면적') || '0').replace(/,/g, ''))) || 0;

      return {
        region: getV('시군구'),
        bunji: getV('지번'),
        road_name: getV('도로명'),
        main_num: toInt(getV('본번')),
        sub_num: finalSubNum,
        danji: getV('단지명'),
        floor: toInt(getV('층')),
        size: finalSize,
        deal_date: finalDate,
        price: toInt(getV('거래금액(만원)')),
        build_year: toInt(getV('건축년도'))
      };
    });

    const { error: insertError } = await supabase
      .from('real_estate_trades')
      .insert(rowsToInsert);

    if (insertError) throw insertError;

    return res.status(200).json({ success: true, count: rowsToInsert.length });

  } catch (error) {
    return res.status(500).json({ error: error.message });
  }
}
