const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('static/stand/tasks.html','utf8');
const s8=html.slice(html.indexOf('  s8:()=>'),html.indexOf('\n  s11:()=>',html.indexOf('  s8:()=>'))).trim().replace(/,$/,'');
for(const [type,kind,expected] of [['Обмен валюты','',['pass','inv']],['Оплата недвижимости','Лизхолд',['pass','inv','spa','ipds']],['Оплата недвижимости','Фрихолд',['pass','inv','spa','ipds']]]){
 const calls=[],ctx={d:{id:1,type,kind},docRow:(d,k)=>{calls.push(k);return k;},doctOf:()=>'',docParseLine:()=>'',fioHint:()=>'',freeholdInvoiceTariffBlock:()=>''};
 vm.runInNewContext('({'+s8+'}).s8()',ctx);assert.deepEqual(calls,expected);
}
console.log('client documents by deal type: PASS');
