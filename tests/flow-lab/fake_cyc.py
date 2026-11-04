import types, numpy as np, pandas as pd, json
START_DATE='2017-09-01'
avm=types.SimpleNamespace()
saved={}
def upsert_rows(rows): saved.update({r['id']:r['payload'] for r in rows}); print('  [upsert]',[r['id'] for r in rows])
def clean_json(x): return json.loads(json.dumps(x,default=lambda o: float(o) if hasattr(o,'__float__') else str(o)))
rng=np.random.default_rng(0)
regions=['서울 강남구','경북 구미시']; rows=[]; coords=[]
for ci in range(150):
    rg=regions[ci%2]
    lat=37.5+rng.uniform(-0.03,0.03) if ci%2==0 else 36.1+rng.uniform(-0.12,0.12); lon=127.0+rng.uniform(-0.03,0.03) if ci%2==0 else 128.3+rng.uniform(-0.12,0.12)
    key=f'동{ci%7}|단지{ci}|{100+ci}|도로{ci}|{100+ci}|'.lower()
    coords.append(dict(cache_key=key,lat=lat,lon=lon))
    base=np.log(900+rng.uniform(-200,300))
    for _ in range(int(rng.integers(60,260))):
        m=int(rng.integers(0,111)); y=2017+(8+m)//12; mo=(8+m)%12+1
        size=float(rng.choice([59,84,114])+rng.uniform(-2,2)); trend=0.004*m+0.1*np.sin(m/10)
        p=np.exp(base+trend+rng.normal(0,0.05))*size
        rows.append(dict(region=rg,dong=f'동{ci%7}',danji=f'단지{ci}',bunji=str(100+ci),price=p,size=size,deal_date=y*10000+mo*100+int(rng.integers(1,28)),dealing_type='중개거래',cdeal_type='',road_name=f'도로{ci}',main_num=100+ci,sub_num=None))
TR=pd.DataFrame(rows); TR=TR[TR['deal_date']<=20261031]
CC=pd.DataFrame(coords); CC['id']=range(len(CC))
def fetch_all_rows(table,cols=None,order_col='id',extra_filter=''):
    return TR.copy() if table=='house_trades' else CC.copy()
avm.fetch_all_rows=fetch_all_rows
