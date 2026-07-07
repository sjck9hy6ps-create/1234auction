import { createClient } from '@supabase/supabase-client';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY);

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { filePath } = req.body;

  try {
    // 1. 오타 수정: { data, error } 가 Supabase 표준 수신 방식입니다.
    const { data, error: downloadError } = await supabase.storage
      .from('csv-uploads')
      .download(filePath);

    if (downloadError) throw downloadError;

    // 2. 정상 작동하던 텍스트 변환 방식
    const csvText = await data.text();
    const lines = csvText.split('\n');
    const headers = lines[0].split(',').map(h => h.trim());

    const rowsToInsert = lines.slice(1).filter(line => line.trim()).map(line => {
      const values = line.split(',').map(v => v.trim());
      const row = {};
      headers.forEach((header, i) => {
        row[header] = values[i] || '';
      });

      // 헬퍼: 숫자 변환 및 콤마 제거
      const toInt = (val) => parseInt(String(val).replace(/[^0-9]/g, '')) || 0;

      // [수정 사항] 부번 로직: 0이면 null 처리
      const subNumValue = toInt(row['부번']);

      return {
        region: row['시군구'],
        bunji: row['지번'],
        road_name: row['도로명'],
        main_num: toInt(row['본번']),
        sub_num: subNumValue === 0 ? null : subNumValue, // 0 -> null
        danji: row['단지명'],
        floor: toInt(row['층']),
        // [수정 사항] 전용면적: 소수점 버리고 정수로
        size: Math.floor(parseFloat(row['전용면적']) || 0),
        deal_date: row['계약년월'] + row['계약일'].padStart(2, '0'),
        price: toInt(row['거래금액(만원)']),
        build_year: toInt(row['건축년도'])
      };
    });

    const { error: insertError } = await supabase
      .from('real_estate_trades')
      .insert(rowsToInsert);

    if (insertError) throw insertError;

    return res.status(200).json({ success: true, count: rowsToInsert.length });

  } catch (error) {
    // 500 에러 시 HTML이 아닌 JSON 메시지를 보내도록 유지
    return res.status(500).json({ error: error.message });
  }
}
