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
  // 고정 명칭에서 값을 가져오는 함수 (공백 제거 후 비교)
  const getV = (fixedName) => {
    const key = Object.keys(row).find(k => k.trim() === fixedName);
    return key ? row[key] : null;
  };

  // 숫자 변환 함수
  const toInt = (val) => parseInt(String(val || '0').replace(/[^0-9]/g, '')) || 0;
  const toFloat = (val) => parseFloat(String(val || '0').replace(/,/g, '')) || 0;

  // 계약년월(202405) + 계약일(01) 조합하여 날짜 생성
  const yearMonth = String(getV('계약년월') || '');
  const day = String(getV('계약일') || '').padStart(2, '0');
  const fullDate = yearMonth && day ? yearMonth + day : null;

  // ... 기존 함수들 생략 ...

    // 숫자로 변환하는 함수
  const toInt = (val) => {
    const num = parseInt(String(val || '0').replace(/[^0-9]/g, ''));
    return isNaN(num) ? 0 : num;
  };

  // 부번 전용: 0이면 null을 반환, 아니면 숫자 반환
  const subNumValue = toInt(getV('부번'));

  return {
    region: getV('시군구'),
    bunji: getV('지번'),
    road_name: getV('도로명'),
    main_num: toInt(getV('본번')),
    // 부번이 0이면 null로 저장, 0이 아니면 그 숫자 저장
    sub_num: subNumValue === 0 ? null : subNumValue, 
    danji: getV('단지명'),
    floor: toInt(getV('층')),
    size: toInt(getV('전용면적')), 
    deal_date: fullDate,
    price: toInt(getV('거래금액(만원)')),
    build_year: toInt(getV('건축년도')),
    raw_row: row 
  };


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
