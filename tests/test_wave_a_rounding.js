const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const html=fs.readFileSync('static/stand/tasks.html','utf8'),ctx={};vm.createContext(ctx);
for(const name of ['freeholdFee','freeholdSend']){
 const fn=html.match(new RegExp(`^function ${name}\\([^\\n]*\\}\\s*$`,'m'))||html.match(new RegExp(`^function ${name}\\([^]*?^}`,'m'));
 vm.runInContext(fn[0],ctx);
}
assert.equal(ctx.freeholdSend(941,{percent:1.5,fixed:50}),1005.12);
assert.equal(ctx.freeholdSend(133205,{percent:1.5,fixed:50}),135253.08);
for(const [name,percent] of [['soft',1.5],['bank',.8]]){
 const hash=crypto.createHash('sha256');
 for(let invoice=100000;invoice<=1000000;invoice++)hash.update(ctx.freeholdSend(invoice,{percent,fixed:50}).toFixed(2)+'\n');
 console.log(name,hash.digest('hex'));
}
