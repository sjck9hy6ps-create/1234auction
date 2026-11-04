import sys,json,random; sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import numpy as np, flow_py as fp
from datetime import date,timedelta
random.seed(11)
cases=[]; py=[]
for k in range(3000):
    cut_d=date(2026,1,1)+timedelta(days=random.randint(0,300)); cut=int(cut_d.strftime('%Y%m%d'))
    n=random.choice([0,2,5,12,40,120]); minn=random.choice([3,10,30])
    rows=[]
    for _ in range(n):
        d=cut_d-timedelta(days=random.randint(-10,240)); rows.append((int(d.strftime('%Y%m%d')),random.uniform(250,420),d))
    rows.sort(key=lambda r:r[0])
    dd=np.array([r[0] for r in rows]); pp=np.array([r[1] for r in rows])
    out=fp.flow_ratio(dd,pp,cut,minn)
    py.append(out); cases.append(dict(cut=cut,minn=minn,t=[dict(y=r[2].year,m=r[2].month,d=r[2].day,ppm=r[1]) for r in rows]))
json.dump(dict(cases=cases,py=py),open('/tmp/flow_in.json','w')); print(len(cases),sum(1 for x in py if x is None))
