// 호가 자동 진행(0.8.0) - 화면과 상관없는 순수 계산(단지 고르기·다음 순서·멈춤 조건·간격). 확장(content-chain.js)과 노드 시험(tests/chain-logic.test.js)이 같이 씀.
(function (root) {
  const normName = (n) => String(n || '').replace(/\([^)]*\)|（[^）]*）/g, '').replace(/아파트\s*$/, '').replace(/[\s·.\-_,]/g, '').toLowerCase();
  const itemKey = (it) => normName(it && it.name) + '|' + String((it && it.dong) || '').replace(/\s/g, '');

  // 네이버 검색 결과의 단지 링크 중 이 단지(이름·동)와 맞는 것 하나. 이름이 정확히 같은 것 → 서로 포함(3글자 이상) 순. 동이 맞는 것을 우선. 못 찾으면 null(엉뚱한 단지를 열지 않음)
  function pickComplexLink(links, item) {
    const t = normName(item && item.name), dong = String((item && item.dong) || '').replace(/\s/g, '');
    if (!t || t.length < 2) return null;
    const cands = [];
    for (const l of links || []) {
      if (!l || !/\/complexes\/\d+/.test(l.href || '')) continue;
      const ln = normName(l.text);
      if (!ln) continue;
      let score = 0;
      if (ln === t) score = 3;
      else if (ln.length >= 3 && t.length >= 3 && (ln.indexOf(t) >= 0 || t.indexOf(ln) >= 0)) score = 2;
      if (!score) continue;
      if (dong && String(l.ctx || '').replace(/\s/g, '').indexOf(dong) >= 0) score += 1;
      cands.push({ href: l.href, score });
    }
    if (!cands.length) return null;
    cands.sort((a, b) => b.score - a.score);
    return cands[0].href;
  }

  // 대기열(items) 중 아직 처리 안 한 첫 항목
  function nextItem(q, handled) {
    const h = handled || {};
    for (const it of (q && q.items) || []) {
      const k = it.key || itemKey(it);
      if (!h[k]) return Object.assign({ key: k }, it);
    }
    return null;
  }

  // 로그인·캡차·접속 제한 화면이면 멈출 이유를 돌려줌(없으면 null)
  function blockedReason(url, text) {
    const u = String(url || ''), t = String(text || '').slice(0, 6000);
    if (/nid\.naver\.com|login|captcha/i.test(u)) return '로그인·확인 화면이 떴어요';
    if (/자동\s*입력\s*방지|로봇이\s*아닙니다|보안\s*문자|캡차|captcha/i.test(t)) return '캡차(자동입력 방지) 화면이 떴어요';
    if (/과도한\s*접속|비정상적인\s*접근|접근이\s*제한|잠시\s*후\s*다시\s*시도|이용이\s*제한/.test(t)) return '네이버가 접속 제한 안내를 띄웠어요';
    return null;
  }

  // 다음 단지까지 쉬는 시간(ms): min~max 사이 무작위
  const jitter = (min, max, rnd) => Math.round(min + (max - min) * (typeof rnd === 'number' ? rnd : Math.random()));
  const dayKey = (d) => { const x = d || new Date(); return x.getFullYear() + '-' + String(x.getMonth() + 1).padStart(2, '0') + '-' + String(x.getDate()).padStart(2, '0'); };

  // 오늘 처리 건수·연속 실패로 계속할지 판단
  function shouldStop(st, limit, failLimit) {
    if ((st.count || 0) >= limit) return '오늘 ' + limit + '곳을 다 했어요 ✅';
    if ((st.fails || 0) >= failLimit) return failLimit + '번 연속으로 못 읽어서 멈췄어요(네이버 화면이 바뀌었을 수 있어요)';
    return null;
  }

  const api = { normName, itemKey, pickComplexLink, nextItem, blockedReason, jitter, dayKey, shouldStop };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.HGChain = api;
})(typeof self !== 'undefined' ? self : this);
