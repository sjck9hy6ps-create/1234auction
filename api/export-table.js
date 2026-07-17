/* ════════════════════════════════════════════════════════════
   api/export-table.js
   테이블 하나를 통째로 CSV로 뽑아주는 백업용 API.
   사용법: GET /api/export-table?table=house_trades
   프론트(public/backup.html)에서 6개 테이블 각각 호출해서 받은 CSV를
   JSZip으로 묶어 하나의 zip으로 다운로드하게 되어있음.
   ⚠️ 데이터가 아주 많아지면(수십만 행) 타임아웃 날 수 있음 - 그때는
   페이지 크기를 줄이거나 별도 배치 방식으로 바꿔야 함.
════════════════════════════════════════════════════════════ */
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY, {
  auth: { persistSession: false },
  realtime: { transport: ws },
});

export const config = { maxDuration: 60 };

const VALID_TABLES = ['house_trades', 'house_rent', 'villa_trades', 'villa_rent', 'single_trades', 'single_rent'];
const PAGE_SIZE = 1000;

function csvEscape(v) {
  if (v === null || v === undefined) return '';
  const s = String(v);
  if (/[",\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
  return s;
}

export default async function handler(req, res) {
  const table = req.query?.table;
  if (!VALID_TABLES.includes(table)) {
    return res.status(400).json({ error: `알 수 없는 테이블: ${table}` });
  }

  try {
    let allRows = [];
    let from = 0;
    while (true) {
      const { data, error } = await supabase
        .from(table)
        .select('*')
        .order('id', { ascending: true })
        .range(from, from + PAGE_SIZE - 1);
      if (error) throw error;
      if (!data || data.length === 0) break;
      allRows = allRows.concat(data);
      if (data.length < PAGE_SIZE) break;
      from += PAGE_SIZE;
    }

    if (allRows.length === 0) {
      res.setHeader('Content-Type', 'text/csv; charset=utf-8');
      res.setHeader('Content-Disposition', `attachment; filename="${table}.csv"`);
      return res.status(200).send('');
    }

    const columns = Object.keys(allRows[0]);
    const lines = [columns.map(csvEscape).join(',')];
    for (const row of allRows) {
      lines.push(columns.map(c => csvEscape(row[c])).join(','));
    }
    const csv = lines.join('\n');

    res.setHeader('Content-Type', 'text/csv; charset=utf-8');
    res.setHeader('Content-Disposition', `attachment; filename="${table}.csv"`);
    return res.status(200).send(csv);
  } catch (e) {
    console.error('export-table 에러:', e);
    return res.status(500).json({ error: e.message });
  }
}
