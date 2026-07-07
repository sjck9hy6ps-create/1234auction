import { createClient } from '@supabase/supabase-client';
import Papa from 'papaparse';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY);

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { filePath } = req.body;
  if (!filePath) return res.status(400).json({ error: 'No file path provided' });

  try {
    // 1. Storage에서 파일 다운로드
    const { fileBlob, error: downloadError } = await supabase.storage
      .from('csv-uploads')
      .download(filePath);

    if (downloadError) {
      return res.status(500).json({ error: `Download Error: \${downloadError.message}` });
    }

    // 2. Blob을 텍스트로 변환 (더 안전한 방법)
    const arrayBuffer = await fileBlob.arrayBuffer();
    const buffer = Buffer.from(arrayBuffer);
    const csvText = buffer.toString('utf-8');

    // 3. CSV 파싱
    const parsed = Papa.parse(csvText, { 
      header: true, 
      skipEmptyLines: true,
      dynamicTyping: false 
    });

    if (parsed.errors.length > 0) {
      console.error('CSV Parsing Errors:', parsed.errors);
    }

    // 4. 데이터 매핑
    const rowsToInsert = parsed.data.map(row => {
      const getV = (name) => {
        const key = Object.keys(row).find(k => k.trim() === name);
        return key ? row[key] : null;
      };

      const toInt = (val) => {
        const cleaned = String(val || '0').replace(/[^0-9]/g, '');
        return parseInt(cleaned) || 0;
      };

      const sNum = toInt(getV('부번'));
      const ym = String(getV('계약년월') || '').trim();
      const d = String(getV('계약일') || '').trim().padStart(2, '0');

      return {
        region: getV('시군구'),
        bunji: getV('지번'),
        road_name: getV('도로명'),
        main_num: toInt(getV('본번')),
        sub_num: sNum === 0 ? null : sNum,
        danji: getV('단지명'),
        floor: toInt(getV('층')),
        size: Math.floor(parseFloat(String(getV('전용면적') || '0').replace(/,/g, ''))) || 0,
        deal_date: ym && d ? ym + d : null,
        price: toInt(getV('거래금액(만원)')),
        build_year: toInt(getV('건축년도'))
      };
    });

    // 5. DB Insert
    const { error: insertError } = await supabase
      .from('real_estate_trades')
      .insert(rowsToInsert);

    if (insertError) {
      return res.status(500).json({ error: `DB Insert Error: \${insertError.message}` });
    }

    return res.status(200).json({ success: true, count: rowsToInsert.length });

  } catch (error) {
    console.error('Final Catch Error:', error);
    return res.status(500).json({ 
      error: 'Internal Server Error', 
      details: error.message 
    });
  }
}
