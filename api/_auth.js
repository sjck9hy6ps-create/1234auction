/* 🔑 쓰기 인증(2026-11-15) - 저장·삭제 같은 '쓰기' 요청이 공유 비밀값(저장 열쇠)을 들고 왔는지 확인.
   환경변수: WRITE_KEY(열쇠) · WRITE_AUTH_MODE('monitor' 기본 = 열쇠 없어도 허용하고 기록만 / 'enforce' = 열쇠 없으면 401). WRITE_KEY가 없으면 꺼짐(예전과 같음).
   요청 헤더: x-write-key.  파일 이름이 _로 시작해서 서버 함수로 노출되지 않음. */
import { timingSafeEqual } from 'node:crypto';

export function writeAuthMode() {
  if (!process.env.WRITE_KEY) return 'off';
  return String(process.env.WRITE_AUTH_MODE || 'monitor').toLowerCase() === 'enforce' ? 'enforce' : 'monitor';
}

export function checkWrite(req) {
  const mode = writeAuthMode();
  if (mode === 'off') return { mode, ok: true, reason: 'off' };
  const got = String((req.headers && req.headers['x-write-key']) || '');
  const want = String(process.env.WRITE_KEY);
  let ok = false;
  if (got.length && got.length === want.length) { try { ok = timingSafeEqual(Buffer.from(got), Buffer.from(want)); } catch (e) { ok = false; } }
  return { mode, ok, reason: ok ? 'ok' : (got ? 'wrong' : 'missing') };
}

/** 쓰기 요청 검사. 거절했으면 true(응답을 이미 보냄), 통과(또는 모니터링만)면 false. onLog(reason)은 모니터링 기록용(선택) */
export function rejectWrite(req, res, onLog) {
  const g = checkWrite(req);
  if (g.mode === 'off' || g.ok) return false;
  try { if (onLog) onLog(g.reason, g.mode); } catch (e) {}
  if (g.mode === 'enforce') { res.status(401).json({ error: '저장 열쇠가 필요해요 (앱 ☰ 메뉴 → 🔑 저장 열쇠)', code: 'write-key' }); return true; }
  return false;
}
