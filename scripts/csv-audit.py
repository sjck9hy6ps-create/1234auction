"""앱의 경매물건 금액을 탱크옥션 CSV(같은 사건번호 + 같은 주소 행)와 대조 (2026-11-01)
- 같은 사건번호가 다른 법원에도 있어 다른 물건의 감정가·최저가가 섞인 기록(오염)을 찾음
- 사용: python3 scripts/csv-audit.py [CSV폴더(기본 ~/Downloads)]  → 요약 출력 + /tmp/csvaudit.json
읽기 전용(앱 데이터를 바꾸지 않음)"""
import csv,glob,re,json,collections,os,sys,urllib.request
def load(fn):
    for enc in ('utf-8-sig','cp949'):
        try: return list(csv.reader(open(fn,encoding=enc)))
        except Exception: pass
    return []
def n(x): return str(x or '').replace('타경','-').replace(' ','')
num=lambda s:int(re.sub(r'\D','',s)) if re.search(r'\d',s or '') else 0
def addrtok(s):
    s=re.sub(r'\s*\([^()]*(?:로|길)\s*\d[^()]*\)\s*$','',s or '')
    m=re.search(r'(?:^|\s)([가-힣0-9]+(?:동|리|가))\s+(?:산\s*)?(\d+(?:-\d+)?)(?![\d])',s); return (m.group(1),m.group(2)) if m else None
rec=collections.defaultdict(list)
for fn in sorted(glob.glob(os.path.join(os.path.expanduser(sys.argv[1] if len(sys.argv)>1 else '~/Downloads'),'탱크옥션*.csv'))):
    ts=fn.split()[1][:12]; rows=load(fn); hi=next((i for i,r in enumerate(rows) if '사건번호' in r and '주소(시군구동)' in r),None)
    if hi is None: continue
    H=rows[hi]
    for r in rows[hi+1:]:
        if len(r)>=len(H):
            d=dict(zip(H,r)); d['_ts']=ts; d['_a']=addrtok(d['주소(시군구동)']); rec[n(d['사건번호'])].append(d)
auc=json.load(urllib.request.urlopen('https://1234auction.vercel.app/api/auction?kind=auctions'))
res=collections.defaultdict(list)
for a in auc:
    if a.get('isBacktest'): continue
    k=n(a.get('caseNo')); rows=rec.get(k,[]); 
    if not rows: res['CSV에 없음'].append(a); continue
    dg=str(a.get('dong') or '').strip(); bj=str(a.get('bunji') or '').strip()
    if not dg or not bj:
        t=addrtok(a.get('addr') or ''); 
        if t: dg,bj=t
    def same(d):
        t=d['_a']
        if not t or not dg or not bj: return False
        return (t[0]==dg or dg in d['주소(시군구동)']) and (t[1]==bj or t[1].startswith(bj+'-') or bj.startswith(t[1]+'-'))
    S=sorted([d for d in rows if same(d)],key=lambda d:d['_ts']); O=[d for d in rows if not same(d)]
    aa=int(a.get('appraisal') or 0)*10000; mm=int(a.get('minBid') or 0)*10000
    close=lambda x,y: x and y and abs(x/y-1)<=0.005
    if S:
        last=S[-1]
        if close(aa,num(last['감정가'])) and (close(mm,num(last['최저가'])) or True): res['정상(같은 주소 CSV와 일치)'].append(a)
        elif any(close(aa,num(d['감정가'])) for d in S): res['이전 회차 값(갱신 필요)'].append((a,last))
        elif any(close(aa,num(d['감정가'])) for d in O): res['⚠️ 다른 물건 금액이 섞임(오염)'].append((a,last,[d for d in O if close(aa,num(d['감정가']))][0]))
        else: res['⚠️ 같은 주소 CSV와 금액이 다름(원인 불명)'].append((a,last))
    else:
        if any(close(aa,num(d['감정가'])) for d in O): res['⚠️ 같은 주소 CSV가 없고 다른 주소 행 금액과 같음(오염 의심)'].append((a,O[-1]))
        else: res['같은 주소 CSV 없음(비교 불가)'].append(a)
if __name__=='__main__':
    for k,v in sorted(res.items(), key=lambda kv:-len(kv[1])): print(len(v),k)
    json.dump({k:[ (x[0]['caseNo'] if isinstance(x,tuple) else x['caseNo']) for x in v] for k,v in res.items()},open('/tmp/csvaudit.json','w'),ensure_ascii=False)
    for k in ('⚠️ 다른 물건 금액이 섞임(오염)','⚠️ 같은 주소 CSV와 금액이 다름(원인 불명)','⚠️ 같은 주소 CSV가 없고 다른 주소 행 금액과 같음(오염 의심)'):
        print('---',k)
        for x in res.get(k,[])[:6]:
            a=x[0]; print(' ',a['caseNo'],a.get('addr','')[:34],'앱 감정',a.get('appraisal'),'최저',a.get('minBid'),a.get('bidDate'),'| CSV',x[1]['주소(시군구동)'][:34],x[1]['감정가'],x[1]['최저가'],x[1]['입찰일자'])
