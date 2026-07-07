import { createClient } from '@supabase/supabase-js';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY);

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { filePath } = req.body;

  try {
    const { data, error: downloadError } = await supabase.storage
      .from('csv-uploads')
      .download(filePath);

    if (downloadError) throw downloadError;

    const csvText = await data.text();
    // [수정] lines가 비어있을 경우를 대비해 기본값 처리
    const lines = csvText ? csvText.split('\n') : [];
    if (lines.length === 0) throw new Error('CSV 파일이 비어있습니다.');

    // [수정] headers 추출 시 h가 있을 때만 replace 실행
    const headers = lines[0].split(',').map(h => (h || '').replace(/"/g, '').trim());

    const rowsToInsert = lines.slice(1).filter(line => line.trim()).map(line => {
      // [수정] values 추출 시 v가 있을 때만 replace 실행
      const values = line.split(',').map(v => (v || '').replace(/"/g, '').trim());
      const row = {};
      headers.forEach((header, i) => {
        if (header) row[header] = values[i] || '';
      });

      // [수정] 모든 replace 호출 전에 값이 있는지 확인
      const toInt = (val) => {
        const strVal = String(val || '');
        const cleanVal = strVal.replace(/[^0-9]/g, '');
        return cleanVal ? parseInt(cleanVal) : 0;
      };

      const subNumValue = toInt(row['부번']);

      return {
        region: row['시군구'] || '',
        bunji: row['지번'] || '',
        road_name: row['도로명'] || '',
        main_num: toInt(row['본번']),
        sub_num: subNumValue === 0 ? null : subNumValue, // 부번 0 -> null
        danji: row['단지명'] || '',
        floor: toInt(row['층']),
        size: Math.floor(parseFloat(row['전용면적']) || 0), // 면적 정수화
        deal_date: (row['계약년월'] || '') + (row['계약일'] || '').padStart(2, '0'),
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
    return res.status(500).json({ error: error.message });
  }
}
