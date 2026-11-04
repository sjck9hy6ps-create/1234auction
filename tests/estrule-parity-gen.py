import json, random, subprocess, sys, math
import numpy as np, pandas as pd
from datetime import date, timedelta
import sys; sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__))); import estrule_py as ab
random.seed(7); np.random.seed(7)
# 지수: 2019-01 ~ 2026-12 랜덤워크
idxm={}; v=900.0
for y in range(2019,2027):
    for m in range(1,13):
        v*=1+random.uniform(-0.02,0.025); idxm[y*100+m]=v
class C: pass
cases=[]
for k in range(2500):
    cut_d=date(2026,1,1)+timedelta(days=random.randint(0,300))
    cut=int(cut_d.strftime('%Y%m%d')); cut_ym=cut//100
    n=random.choice([0,1,2,3,4,6,10,25])
    rows=[]
    for _ in range(n):
        d=cut_d-timedelta(days=random.randint(-20,1300))   # 일부는 cut 이후(제외돼야 함)
        size=random.choice([59.9,59.9+random.uniform(-4,4),84.9,84.9+random.uniform(-3.5,3.5),114.4,84.9+random.uniform(5,12)])
        ppm=random.uniform(250,420)*(idxm.get(d.year*100+d.month,900)/900)
        rows.append((int(d.strftime('%Y%m%d')),size,ppm*size,ppm,d.year*100+d.month,d))
    area=random.choice([59.9,84.9,84.95,114.4])
    reg=random.choice(['서울 강남구','경기 성남','경기 용인','충북 청주','대구 북구','인천 남동구'])
    cases.append(dict(cut=cut,cut_ym=cut_ym,rows=rows,area=area,reg=reg))
# python 계산
py=[]
for cs in cases:
    g=pd.DataFrame([dict(deal_date=r[0],size=r[1],price=r[2],ppm=r[3],ym=r[4]) for r in cs['rows']],columns=['deal_date','size','price','ppm','ym'])
    c=C(); c.area=cs['area']; c.region=cs['reg']
    out=ab.est_rule_asof(g,c,None,cs['cut'],cs['cut_ym'],lambda rg,ym:idxm.get(int(ym)))
    py.append(out)
# JS 입력
js_in=[]
for cs in cases:
    sido=cs['reg'].split()[0]; cls='서울' if sido.startswith('서울') else ('경기·인천' if sido[:2] in ('경기','인천') else '지방')
    cd=str(cs['cut']); ref=int(__import__('datetime').datetime(int(cd[:4]),int(cd[4:6]),int(cd[6:]),0,0,0).timestamp()*1000)
    js_in.append(dict(area=cs['area'],cls=cls,cut=cs['cut'],cutym=cs['cut_ym'],trades=[dict(y=r[5].year,m=r[5].month,d=r[5].day,price=r[2],size=r[1],ppm=r[3]) for r in cs['rows']]))
json.dump(dict(idx={str(k):v for k,v in idxm.items()},cases=js_in,py=py),open('/tmp/parity_in.json','w'))
print('cases',len(cases),'py none',sum(1 for x in py if x is None))
