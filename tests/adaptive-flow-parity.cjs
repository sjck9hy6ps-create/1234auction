// 서버(adaptive_flow)와 앱(adaptiveFlowCore)이 같은 값을 내는지 시험: python tests/adaptive-flow-gen.py 로 /tmp/af_in.json 을 만든 뒤 실행
const fs=require('fs');
const src=fs.readFileSync(process.argv[2]||'/tmp/chk1.js','utf8')+fs.readFileSync(process.argv[3]||'/tmp/chk0.js','utf8');
const i=src.indexOf('function adaptiveFlowCore'), j=src.indexOf('function flowDaysTrades');
const f=new Function(src.slice(i,j)+';return adaptiveFlowCore;')();
const D=JSON.parse(fs.readFileSync('/tmp/af_in.json','utf8'));
const ord=(y,m,d)=>Date.UTC(y,m-1,d)/86400000;
let bad=0,maxd=0,n=0;
D.cases.forEach((c,k)=>{const cd=String(c.cut);const cutDays=ord(+cd.slice(0,4),+cd.slice(4,6),+cd.slice(6));
 const tr=c.dd.map((x,ix)=>{const s=String(x);return {d:ord(+s.slice(0,4),+s.slice(4,6),+s.slice(6)),ppm:c.pp[ix]};});
 const o=f(tr,cutDays,c.K,c.mx),p=D.py[k];
 if((o==null)!==(p==null)){bad++;return;}
 if(o!=null){n++;['rate','z','vol','dens'].forEach(key=>{maxd=Math.max(maxd,Math.abs(o[key]-p[key])/(Math.abs(p[key])+1e-9));});}});
console.log('비교',n,'건 / 값 있음·없음 불일치',bad,'/ 최대 상대차이',maxd);
