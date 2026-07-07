import { createClient } from '@supabase/supabase-js';

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);

const BUCKET = 'uploads'; // 실제 버킷 이름으로 변경

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { key, filename, size } = req.body;

  if (!key) {
    return res.status(400).json({ error: 'key is required' });
  }

  try {
    const { data, error } = await supabase.storage
      .from(BUCKET)
      .list('', { search: key });

    if (error) throw error;

    const exists = data.some(file => file.name === key);
    if (!exists) {
      return res.status(404).json({ error: '파일이 업로드되지 않았습니다.' });
    }

    res.json({ success: true, key });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
}
