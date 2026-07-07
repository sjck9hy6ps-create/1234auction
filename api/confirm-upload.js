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

    // 3. 데이터 가공
    const rowsToInsert = parsed.data.map(row => ({
      city: row['시군구'] || row['﻿시군구'], 
      danji: row['단지명'],
      size: parseFloat(row['전용면적(㎡)']) || 0,
      price: row['거래금액(만원)'] ? parseInt(String(row['거래금액(만원)']).replace(/,/g, '')) : 0,
      deal_date: row['계약년월일'] || (row['계약년월'] && row['계약일'] ? row['계약년월'] + row['계약일'] : null),
      raw_row: row // 변수명 수정: raw_row -> row
    }));

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
