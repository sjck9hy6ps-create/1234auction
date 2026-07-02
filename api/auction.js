let auctions = []; // 임시 저장소 (Vercel 재배포 시 초기화됨)

export default async function handler(req, res) {
  if (req.method === 'GET') {
    return res.status(200).json(auctions);
  } 
  if (req.method === 'POST') {
    const data = req.body;
    const index = auctions.findIndex(a => a.id === data.id);
    if (index > -1) auctions[index] = data;
    else auctions.push(data);
    return res.status(200).json(data);
  }
  if (req.method === 'DELETE') {
    const { id } = req.query;
    auctions = auctions.filter(a => a.id !== id);
    return res.status(200).json({ success: true });
  }
}
