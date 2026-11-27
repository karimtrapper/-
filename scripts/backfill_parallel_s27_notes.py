"""One-time, idempotent s27 handoff notice for prepay deals missed before deploy.

Preview by default. Run with --apply only after the UI/notification fix is deployed.
"""

import argparse
import json

import app as crm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deal-id', type=int, action='append', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not crm.STAND_MODE:
        parser.error('STAND_MODE is required')

    db = crm.get_session()
    try:
        row = crm._stand_row(db, lock=True)
        state = json.loads(row.data or '{}')
        pending = []
        for deal_id in dict.fromkeys(args.deal_id):
            deal = next((d for d in state.get('deals', []) if d.get('id') == deal_id), None)
            if not deal or not deal.get('prepay') or deal.get('closed') or deal.get('step') != 's27':
                print(f'{deal_id}: skip (no open prepay s27 task)')
                continue
            event_id = f'stand:repair:prepay-s27:{deal_id}'
            if any(n.get('id') == event_id for n in state.get('notes', [])):
                print(f'{deal_id}: skip (repair notice already exists)')
                continue
            pending.append((deal, event_id))
            print(f'{deal_id}: manager handoff notice ready')
        if not args.apply:
            print('preview only; pass --apply after deployment to create and deliver notices')
            return
        for deal, event_id in pending:
            crm._stand_note(state, event_id, 'manager', deal,
                            f"{deal.get('code') or deal['id']}: задача на вас — закрытие сделки")
        if pending:
            row.data = json.dumps(state, ensure_ascii=False)
            row.version = (row.version or 0) + 1
            row.updated_by = 's27 notification repair'
            db.commit()
    finally:
        db.close()
    if pending:
        print(f'created {len(pending)} notice(s); delivery: {crm._stand_deliver_notes()}')


if __name__ == '__main__':
    main()
