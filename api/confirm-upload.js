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
    const lines = csvText.split('\n');
    // 헤더에서 보이지 않는 공백이나 따옴표 제거
    const headers = lines[0].split(',').map(h => h.replace(/"/g, '').trim());

    const rowsToInsert = lines.slice(1).filter(line => line.trim()).map(line => {
      const values = line.split(',').map(v => v.replace(/"/g, '').trim());
      const row = {};
      headers.forEach((header, i) => {
        row[header] = values[i] || '';
      });

      // [수정] replace 에러 방지: val이 있을 때만 replace 실행
      const toInt = (val) => {
        if (!val) return 0;
        const cleanVal = String(val).replace(/[^0-9]/g, '');
        return cleanVal ? parseInt(cleanVal) : 0;
      };

      const subNumValue = toInt(row['부번']);

      return {
        region: row['시군구'] || '',
        bunji: row['지번'] || '',
        road_name: row['도로명'] || '',
        main_num: toInt(row['본번']),
        sub_num: subNumValue === 0 ? null : subNumValue,
        danji: row['단지명'] || '',
        floor: toInt(row['층']),
        size: Math.floor(parseFloat(row['전용면적']) || 0),
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
    // 이제 에러 메시지가 JSON으로 정확히 출력됩니다.
    return res.status(500).json({ error: error.message });
  }
}
