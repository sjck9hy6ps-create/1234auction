import { createClient } from '@supabase/supabase-js';
import Papa from 'papaparse';

// 서버 측에서는 SERVICE_ROLE_KEY를 사용하는 것이 RLS를 우회하여 DB 쓰기에 안전합니다.
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY 
);

const BUCKET = 'uploads';

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { key, filename } = req.body;
  if (!key) return res.status(400).json({ error: 'key is required' });

  try {
    // 1. Storage에서 파일 다운로드
    const { fileData, error: downloadError } = await supabase.storage
      .from(BUCKET)
      .download(key);

    if (downloadError) throw downloadError;

    // 2. CSV 파싱 (한글 깨짐 방지를 위해 text() 사용)
    const csvText = await fileData.text();
    const parsed = Papa.parse(csvText, {
      header: true,      // 첫 줄을 컬럼명으로 사용
      skipEmptyLines: true
    });

    // 3. 데이터 가공 (CSV 헤더 이름은 실제 파일과 일치해야 합니다)
    // 아래 '시군구', '단지명' 등은 국토부 실거래가 표준 헤더 기준입니다.
    const rowsToInsert = parsed.data.slice(0, 100).map(row => ({
      city: row['시군구'] || row['﻿시군구'], // 가끔 보이지 않는 문자가 붙는 경우 대비
      danji: row['단지명'],
      size: parseFloat(row['전용면적(㎡)']) || 0,
      price: row['거래금액(만원)'] ? parseInt(row['거래금액(만원)'].replace(/,/g, '')) : 0,
      deal_date: row['계약년월일'] || (row['계약년월'] + row['계약일']),
      raw_row // 전체 데이터 보관용
    }));

    // 4. DB(real_estate_trades 테이블)에 삽입
    const { insertData, error: insertError } = await supabase
      .from('real_estate_trades')
      .insert(rowsToInsert);

    if (insertError) throw insertError;

    return res.status(200).json({
      success: true,
      message: `${rowsToInsert.length}행의 데이터를 DB에 저장했습니다.`,
      first_row_preview: rowsToInsert[0]
    });

  } catch (err) {
    console.error('Error details:', err);
    return res.status(500).json({ error: err.message });
  }
}
