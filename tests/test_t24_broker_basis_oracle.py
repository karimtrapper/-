"""Compare the server's RUB close basis with the actual stand JS serializer."""
import json
import subprocess
from decimal import Decimal

import app as m
import pytest


def test_broker_basis_matches_source_js_at_rounding_edges():
    cases = [(100000, 100), (100005, 100), (100015, 100),
             (100025, 100), (100055, 100), (9200, 92)]
    script = r"""
const fs=require('fs'), vm=require('vm');
const src=fs.readFileSync('static/stand/tasks.html','utf8');
const broker=src.slice(src.indexOf('const BROKER_FEE='),
                       src.indexOf('/* Откуда физически',src.indexOf('const BROKER_FEE=')));
const parts=src.slice(src.indexOf('function hashSum('),src.indexOf('function econ('));
const payloadStart=src.indexOf('const E=econ(d)',src.indexOf('function crmPayload('));
const serializer=src.slice(payloadStart,src.indexOf('payin_rate_rub_usdt:',payloadStart));
const field=serializer.match(/^\s*(payin_amount_usdt:r2\([^\n]+\)),\s*$/m);
if(!field)throw Error('CRM serializer payin_amount_usdt expression missing');
const box={cases:JSON.parse(process.argv[1]), field:field[1], result:null, crypto:null};
vm.runInNewContext(`function num(x){return Number(x)||0}
function isCrypto(d){return d.payType==='Крипта'}
function payinForeign(d,h){return !!h.otherSender}
function r2(v){return (v==null||v===''||!isFinite(v))?null:Math.round(v*100)/100}
${broker}\n${parts}
result=cases.map(([rub,rate])=>{
  const d={payType:'Наличные',incomeAmount:rub,rates:{broker:rate},payinHashes:[]};
  const b=brokerSend(rub), main=payinParts(d)[0];
  return {control:b.ctrl,retained:b.ours,sent:b.sent,
          usdt:Math.round(main.usdt*100)/100,
          payloadUsdt:eval('({' + field + '})').payin_amount_usdt};
});
const freehold={kind:'Фрихолд',payType:'Крипта',amountUsdt:98800,rates:{},
  payinHashes:[{hash:'confirmed',amount:98799.5,verified:true},
               {hash:'unverified',amount:400,verified:false}]};
const d=freehold;
crypto={plan:d.amountUsdt,fact:payinParts(d)[0].fact,
        payloadUsdt:eval('({' + field + '})').payin_amount_usdt};`,box);
console.log(JSON.stringify({cash:box.result,crypto:box.crypto}));
"""
    run = subprocess.run(['node', '-e', script, json.dumps(cases)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    actual = result['cash']
    for (rub, rate), expected in zip(cases, actual):
        saved = m._stand_broker_payin_basis(rub, rate)
        assert saved is not None
        for key in ('control', 'retained', 'sent', 'usdt'):
            assert saved[key] == Decimal(str(expected[key])), (rub, rate, key, saved, expected)
        assert saved['usdt'] == Decimal(str(expected['payloadUsdt']))
    assert actual[0]['usdt'] == 996.60
    assert actual[2] == {'control': 140.01, 'retained': 200.03,
                         'sent': 99674.96, 'usdt': 996.75, 'payloadUsdt': 996.75}
    assert result['crypto'] == {'plan': 98800, 'fact': 98799.5,
                                'payloadUsdt': 98799.5}


@pytest.mark.parametrize('rub,rate', [(None, 100), (100000, None),
                                      (0, 100), (100000, 0), (-1, 100),
                                      (100000, -1), (10 ** 309, 100),
                                      (100000, '1e-400'), ('1e308', 1)])
def test_broker_basis_never_uses_invalid_inputs(rub, rate):
    assert m._stand_broker_payin_basis(rub, rate) is None
