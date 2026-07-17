/* ════════════════════════════════════════════════════════════
   api/import-csv-batch.js
   브라우저에서 파싱한 CSV row 묶음(batch)을 받아서 지역 매칭 + DB 저장.
   - 프론트엔드(public/backup.html)가 파일 전체를 파싱한 뒤 1500개씩
     끊어서 이 API를 여러 번 호출하는 방식. 큰 파일도 서버리스 함수
     타임아웃/페이로드 제한에 안 걸림.
   - api/lib/molit-import.mjs 의 공용 로직 재사용.
════════════════════════════════════════════════════════════ */
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';
import { importBatch, VALID_TABLES } from '../lib/molit-import.mjs';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY, {
  auth: { persistSession: false },
  realtime: { transport: ws },
});

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'POST만 지원함' });
  }
  try {
    const { table, rows } = req.body || {};
    if (!VALID_TABLES.includes(table)) {
      return res.status(400).json({ error: `알 수 없는 테이블: ${table}` });
    }
    if (!Array.isArray(rows) || rows.length === 0) {
      return res.status(400).json({ error: 'rows가 비어있음' });
    }
    const result = await importBatch(supabase, table, rows);
    return res.status(200).json(result);
  } catch (e) {
    console.error('import-csv-batch 에러:', e);
    return res.status(500).json({ error: e.message });
  }
}
