"""Read-only audit of already-restored LOCAL PostgreSQL snapshots; never imports app."""
import argparse
import json
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor


def audit(dbname, socket, port):
    assert socket.startswith('/tmp/') or socket.startswith('/private/tmp/')
    conn = psycopg2.connect(dbname=dbname, host=socket, port=port)
    conn.set_session(readonly=True, autocommit=False)
    with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SHOW transaction_read_only')
        assert cur.fetchone()['transaction_read_only'] == 'on'
        cur.execute('SELECT count(*) AS count FROM deals')
        total = cur.fetchone()['count']
        cur.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public'")
        columns = {}
        for row in cur.fetchall():
            columns.setdefault(row['table_name'], set()).add(row['column_name'])
        # Direct deal links only: no guessed client/time matching. updated_at is
        # deliberately excluded: a later edit alone cannot date creation.
        events = []
        for table, cols in columns.items():
            fk = next((k for k in ('deal_id', 'claimed_deal_id', 'crm_deal_id', 'stand_deal_id') if k in cols), None)
            ts = next((k for k in ('created_at', 'timestamp', 'confirmed_at') if k in cols), None)
            if fk and ts:
                events.append(f"SELECT {fk} AS deal_id, {ts} AS at, '{table}.{ts}' AS evidence FROM {table}")
        cur.execute('''WITH events AS (''' + ' UNION ALL '.join(events) + ''')
            SELECT d.id, d.created_at, d.updated_at,
                   min(e.at) AS first_linked_event,
                   json_agg(json_build_object('source', e.evidence, 'at', e.at) ORDER BY e.at, e.evidence) AS evidence
            FROM deals d JOIN events e ON e.deal_id=d.id
            WHERE d.created_at::time = time '00:00:00'
              AND e.at::time <> time '00:00:00'
            GROUP BY d.id ORDER BY d.id''')
        midnight = [dict(r) for r in cur.fetchall()]
        for r in midnight:
            r['same_day_evidence'] = [e for e in r['evidence'] if e['at'][:10] == str(r['created_at'])[:10]]
        cur.execute("""SELECT id,payout_source,payout_founder_name FROM deals
            WHERE payout_founder_name='Андрей'
              AND payout_source::text IS DISTINCT FROM 'FOUNDER_PERSONAL' ORDER BY id""")
        founder = [dict(r) for r in cur.fetchall()]
        cur.execute("""SELECT d.id,d.cash_batch_id,d.status,d.payout_amount_thb FROM deals d
            WHERE d.payout_source::text='CASH_BATCH'
              AND NOT EXISTS (SELECT 1 FROM cash_batches b WHERE b.id=d.cash_batch_id)
              AND NOT EXISTS (SELECT 1 FROM cash_allocations a JOIN cash_batches b ON b.id=a.batch_id WHERE a.deal_id=d.id)
            ORDER BY d.id""")
        cash = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT count(*) AS count FROM deals WHERE created_at::time=time '00:00:00'")
        midnight_total = cur.fetchone()['count']
    conn.close()
    return dict(database=dbname, total=total, midnight_total=midnight_total,
                midnight_with_linked_events=midnight, wrong_founder=founder, cash_without_batch=cash)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--socket', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--stand', required=True)
    parser.add_argument('--prod', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = {name: audit(db, args.socket, args.port) for name, db in [('stand', args.stand), ('prod', args.prod)]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str)+'\n')
    for name, data in result.items():
        print(name, 'total=',data['total'], 'midnight=', data['midnight_total'],
              'linked=',len(data['midnight_with_linked_events']),
              'same_day=',sum(bool(r['same_day_evidence']) for r in data['midnight_with_linked_events']),
              'founder=',len(data['wrong_founder']), 'cash=',len(data['cash_without_batch']))
