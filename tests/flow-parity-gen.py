import sys,json,random; sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import numpy as np, flow_py as fp
from datetime import date,timedelta
random.seed(5)
cases=[];py=[]
for k in range(3000):
    cut_d=date(2026,1,1)+timedelta(days=random.randint(0,300)); cut=int(cut_d.strftime('%Y%m%d'))
    n=random.choice([0,3,8,20,60,200]); minp=random.choice([3,10,30]); minb=random.choice([6,30,90])
    rows=[]
    for _ in range(n):
        d=cut_d-timedelta(days=random.randint(-10,400)); rows.append((int(d.strftime('%Y%m%d')),random.uniform(250,420),random.random()<0.7,d))
    rows.sort(key=lambda r:r[0])
    allr=rows; band=[r for r in rows if r[2]]
    out=fp.flow_pv(np.array([r[0] for r in band]),np.array([r[1] for r in band]),np.array([r[0] for r in allr]),cut,minp,minb)
    py.append(out); cases.append(dict(cut=cut,minp=minp,minb=minb,all=[dict(y=r[3].year,m=r[3].month,d=r[3].day) for r in allr],band=[dict(y=r[3].year,m=r[3].month,d=r[3].day,ppm=r[1]) for r in band]))
json.dump(dict(cases=cases,py=py),open('/tmp/flow_in.json','w')); print(len(cases))
