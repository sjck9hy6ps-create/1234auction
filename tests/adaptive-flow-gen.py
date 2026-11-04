"""adaptive_flow(서버)와 adaptiveFlowCore(앱) 값 일치 시험용 입력 만들기 - 실행 후: node tests/adaptive-flow-parity.cjs"""
import json, random, os, sys, numpy as np
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adaptive_flow_py as ab
random.seed(9); np.random.seed(9)
cases = []; py = []
for k in range(2500):
    n = random.choice([10, 25, 60, 150, 600, 5000]); K = random.choice([5, 12, 20, 40]); mx = random.choice([365, 730])
    cut_d = date(2026, 1, 1) + timedelta(days=random.randint(0, 300)); cut = int(cut_d.strftime('%Y%m%d'))
    span = random.choice([200, 500, 900])
    ds = sorted(int((cut_d - timedelta(days=random.randint(-15, span))).strftime('%Y%m%d')) for _ in range(n))
    drift = random.uniform(-0.3, 0.3)
    t = np.array([(cut_d - date(int(str(x)[:4]), int(str(x)[4:6]), int(str(x)[6:]))).days for x in ds])
    pp = 1000 * np.exp(-drift * t / 365 + np.random.normal(0, 0.06, n))
    py.append(ab.adaptive_flow(np.array(ds), pp, cut, K, mx)); cases.append(dict(cut=cut, K=K, mx=mx, dd=ds, pp=pp.tolist()))
json.dump(dict(cases=cases, py=py), open('/tmp/af_in.json', 'w')); print(len(cases), sum(1 for x in py if x is None))
