"""
📈 정확도 원장 (2026-10-25, 사용자: 시세·예상낙찰가·예상매도가·추천가 4가지가 매주 정확해지도록)
주간 파이프라인의 각 단계가 자기 값의 '학습에 쓰지 않은 최근 사례' 정확도를 여기에 한 줄씩 남긴다 → leader_follower_cache 'signal|__accuracy_ledger__'
  metrics[이름] = {latest: {...}, history: [{week, ...} 최근 26주]}   (같은 주에 다시 돌리면 그 주 값을 덮어씀)
각 항목: n(사례 수) · err(보통 오차 %) · bias(치우침 %, +는 실제가 더 높음) · hi10(예상이 실제보다 10%+ 높아 손해 쪽인 비율 %) 등.
앱은 이 값을 읽어 주간 리포트 🛠 탭에 '지난주 대비 좋아졌나'를 보여준다. 자동으로 계산 규칙을 바꾸지는 않는다(후보 점검 결과를 보고 사용자가 결정).
"""
import os, json
from datetime import datetime, timezone

LEDGER_ID = "signal|__accuracy_ledger__"


def _iso_week(now=None):
    d = now or datetime.now(timezone.utc)
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def record(cyc, name, stats, label=None):
    """stats: dict(숫자 위주). 읽기-수정-쓰기라 여러 단계가 같은 행을 차례로 갱신해도 서로 덮어쓰지 않음(단계는 순서대로 실행됨)"""
    import requests
    now = datetime.now(timezone.utc); wk = _iso_week(now)
    cur = {}
    try:
        rr = requests.get(f"{cyc.SUPABASE_URL}/rest/v1/leader_follower_cache?select=payload&id=eq.{LEDGER_ID.replace('|', '%7C')}", headers=cyc.HEADERS, timeout=60)
        if rr.ok and rr.json(): cur = rr.json()[0].get("payload") or {}
    except Exception as e:
        print("  원장 읽기 실패(새로 시작):", e)
    m = cur.get("metrics") or {}
    e = m.get(name) or {"history": []}
    e["label"] = label or e.get("label") or name
    e["history"] = [h for h in (e.get("history") or []) if h.get("week") != wk]
    e["history"].append({"week": wk, "at": now.isoformat(), **stats})
    e["history"] = e["history"][-26:]
    e["latest"] = e["history"][-1]
    m[name] = e
    cur["metrics"] = m; cur["generatedAt"] = now.isoformat()
    cyc.upsert_rows([{"id": LEDGER_ID, "payload": cyc.clean_json(cur), "fetched_at": cur["generatedAt"]}])
    print(f"  📈 정확도 원장 기록 [{name}] {json.dumps(stats, ensure_ascii=False)}")
