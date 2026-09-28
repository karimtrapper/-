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
const field=src.match(/payin_amount_usdt:r2\(payinParts\(d\)\[0\]\?\.usdt\)/);
if(!field)throw Error('T17 CRM serializer field expression changed');
const box={cases:JSON.parse(process.argv[1]), field:field[0], result:null};
vm.runInNewContext(`function num(x){return Number(x)||0}
function isCrypto(d){return d.payType==='Крипта'}
function r2(v){return (v==null||v===''||!isFinite(v))?null:Math.round(v*100)/100}
${broker}\n${parts}
result=cases.map(([rub,rate])=>{
  const d={payType:'Наличные',incomeAmount:rub,rates:{broker:rate},payinHashes:[]};
  const b=brokerSend(rub), main=payinParts(d)[0];
  return {control:b.ctrl,retained:b.ours,sent:b.sent,
          usdt:Math.round(main.usdt*100)/100,
          payloadUsdt:eval('({' + field + '})').payin_amount_usdt};
});`,box);
console.log(JSON.stringify(box.result));
"""
    run = subprocess.run(['node', '-e', script, json.dumps(cases)],
                         check=True, capture_output=True, text=True)
    actual = json.loads(run.stdout)
    for (rub, rate), expected in zip(cases, actual):
        saved = m._stand_broker_payin_basis(rub, rate)
        assert saved is not None
        for key in ('control', 'retained', 'sent', 'usdt'):
            assert saved[key] == Decimal(str(expected[key])), (rub, rate, key, saved, expected)
        assert saved['usdt'] == Decimal(str(expected['payloadUsdt']))
    assert actual[0]['usdt'] == 996.60
    assert actual[2] == {'control': 140.01, 'retained': 200.03,
                         'sent': 99674.96, 'usdt': 996.75, 'payloadUsdt': 996.75}


@pytest.mark.parametrize('rub,rate', [(None, 100), (100000, None),
                                      (0, 100), (100000, 0), (-1, 100),
                                      (100000, -1), (10 ** 309, 100),
                                      (100000, '1e-400'), ('1e308', 1)])
def test_broker_basis_never_uses_invalid_inputs(rub, rate):
    assert m._stand_broker_payin_basis(rub, rate) is None
