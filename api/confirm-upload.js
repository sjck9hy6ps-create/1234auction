// [오타 수정] @supabase/supabase-client -> @supabase/supabase-js
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY);

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { filePath } = req.body;

  try {
    // 1. 파일 다운로드 (변수명 data로 고정)
    const { data, error: downloadError } = await supabase.storage
      .from('csv-uploads')
      .download(filePath);

    if (downloadError) throw downloadError;

    // 2. 텍스트 변환 및 파싱
    const csvText = await data.text();
    const lines = csvText.split('\n');
    const headers = lines[0].split(',').map(h => h.trim());

    const rowsToInsert = lines.slice(1).filter(line => line.trim()).map(line => {
      const values = line.split(',').map(v => v.trim());
      const row = {};
      headers.forEach((header, i) => {
        row[header] = values[i] || '';
      });

      // 숫자 변환 함수
      const toInt = (val) => parseInt(String(val).replace(/[^0-9]/g, '')) || 0;

      // [핵심 로직] 부번이 0이면 null 처리
      const subNumValue = toInt(row['부번']);

      return {
        region: row['시군구'],
        bunji: row['지번'],
        road_name: row['도로명'],
        main_num: toInt(row['본번']),
        sub_num: subNumValue === 0 ? null : subNumValue,
        danji: row['단지명'],
        floor: toInt(row['층']),
        // [핵심 로직] 면적 소수점 버림
        size: Math.floor(parseFloat(row['전용면적']) || 0),
        deal_date: (row['계약년월'] || '') + (row['계약일'] || '').padStart(2, '0'),
        price: toInt(row['거래금액(만원)']),
        build_year: toInt(row['건축년도'])
      };
    });

    // 3. DB 저장
    const { error: insertError } = await supabase
      .from('real_estate_trades')
      .insert(rowsToInsert);

    if (insertError) throw insertError;

    return res.status(200).json({ success: true, count: rowsToInsert.length });

  } catch (error) {
    // 에러 발생 시 JSON 응답 강제
    console.error(error);
    return res.status(500).json({ error: error.message });
  }
}
