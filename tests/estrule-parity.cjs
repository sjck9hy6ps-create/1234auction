const fs=require('fs');
const src=fs.readFileSync('/tmp/chk1.js','utf8')+fs.readFileSync('/tmp/chk0.js','utf8');
const i=src.indexOf('function estRuleCore'), j=src.indexOf('// 서버 지수와 같은 방식');
const k=src.indexOf('function weightedMedianByAge'), l=src.indexOf('function aptOwnTradeStats');
const f=new Function(src.slice(k,l)+src.slice(i,j)+';return estRuleCore;')();
const D=JSON.parse(fs.readFileSync('/tmp/parity_in.json','utf8'));
const idxmap=D.idx;
let maxd=0,bad=0,nn=0,worst=null,over1=0,over0=0;
D.cases.forEach((c,n)=>{
  const idx=ym=>{const y=Math.floor((ym-1)/12),m=ym-y*12;const v=idxmap[String(y*100+m)];return v===undefined?null:v;};
  const cd=String(c.cut); const ref=new Date(+cd.slice(0,4),+cd.slice(4,6)-1,+cd.slice(6)).getTime();
  const base=idx(+cd.slice(0,4)*12+ +cd.slice(4,6));
  const trades=c.trades.map(t=>({td:new Date(t.y,t.m-1,t.d).getTime(),price:t.price,size:t.size,ppm:t.ppm}));
  const out=f(trades,c.area,c.cls,ref,idx,base);
  const p=D.py[n];
  if((out==null)!==(p==null)){bad++; if(!worst) worst={n,out,p,cls:c.cls,nt:c.trades.length};return;}
  if(out!=null){nn++; const d=Math.abs(out/p-1); if(d>1e-9)over0++; if(d>0.001)over1++; if(d>maxd){maxd=d; worst={n,out,p,cls:c.cls,nt:c.trades.length};}}
});
console.log('비교',nn,'건 / none 불일치',bad,'/ 최대 상대차이',maxd,'/ 1e-9 초과',over0,'/ 0.1% 초과',over1, JSON.stringify(worst));
