// Прямая загрузка не отправляет base64 в доску и сохраняет параллельный ввод.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync(require('node:path').join(__dirname,'../static/stand/tasks.html'),'utf8');
const names=['standMerge','fileUploadServer','fileAddReal','fileValid'];
const code=names.map(n=>html.match(new RegExp(`^(?:async )?function ${n}\\([^]*?^}`,'m'))[0]).join('\n');
const clone=x=>JSON.parse(JSON.stringify(x));
async function run(){
  const base={deals:[{id:1,files:{},comment:'',log:[]}]};
  const ctx={STAND:true,SCREEN:false,SNAP:false,STAND_SHARED:['deals'],
    standBase:clone(base),standVer:1,standBusy:false,standPush:false,
    standClone:clone,jeq:(a,b)=>JSON.stringify(a)===JSON.stringify(b),
    standWaitSaved:async()=>({ok:true}),FormData,File,Blob,console,atob,
    toasts:[],render:()=>{},optimized:[],saves:0};
  let local=clone(base),requests=0;
  ctx.standSnapshot=()=>clone(local);ctx.standApply=x=>{local=clone(x);};
  ctx.toast=x=>ctx.toasts.push(x);ctx.standSave=()=>{ctx.saves++;ctx.standPush=false;};
  ctx.fileOptimizeImage=async file=>{ctx.optimized.push(file.name);return file;};
  ctx.fetch=async (url,options)=>{
    requests++;assert.equal(url,'/api/stand/files');assert.equal(ctx.standBusy,true);
    assert.ok(options.body instanceof FormData);
    assert.equal(options.body.get('dealId'),'1');assert.equal(options.body.get('kind'),'inv');
    assert.equal(await options.body.get('file').text(),'%PDF-1.4');
    local.deals[0].comment='ввели во время загрузки';ctx.standPush=true;
    const data=clone(base);data.deals[0].files.inv=[{storageId:'abc',data:'__detached__'}];
    return {ok:true,json:async()=>({success:true,version:2,data})};
  };
  vm.createContext(ctx);vm.runInContext('let fileUploadQueue=Promise.resolve();\n'+code,ctx);
  await ctx.fileAddReal(1,'inv',new File(['%PDF-1.4'],'invoice.pdf',{type:'application/pdf'}));
  assert.equal(requests,1);assert.equal(ctx.standBusy,false);
  assert.equal(local.deals[0].comment,'ввели во время загрузки');
  assert.equal(local.deals[0].files.inv[0].storageId,'abc');assert.equal(ctx.saves,1);
  assert.equal(ctx.toasts.at(-1),'Файл сохранён');
  assert.equal(ctx.fileValid({data:'__detached__',file:'x.pdf',mime:'application/pdf',bytes:15*1024*1024}),true);
  ctx.fetch=async()=>({ok:false,json:async()=>({success:false,error:'Хранилище файлов не настроено'})});
  await ctx.fileAddReal(1,'inv',new File(['%PDF-1.4'],'invoice.pdf',{type:'application/pdf'}));
  assert.equal(ctx.standBusy,false);assert.match(ctx.toasts.at(-1),/не настроено/);
  console.log('files storage: multipart, concurrent edit, error, 15MB metadata PASS');
}
run().catch(e=>{console.error(e);process.exitCode=1;});
