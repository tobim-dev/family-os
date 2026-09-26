"""Read-only offline copy for the iPhone (E-13, V-01, decision O-10 of 26.09.2026).

The app keeps a copy of the last shopping list and of the active voucher PDFs
in the browser's cache so they can be read without a connection to the NAS.
Offline nothing can be changed; ticking off stays in the Cookidoo app.
The copy is removed on logout (static/offline-sync.js).
"""
import json

from fastapi import Request


class Offline:
    def __init__(self, db):
        self.db = db

    def snapshot(self, conn):
        row = conn.execute("SELECT value,updated FROM meal_cache WHERE key='shopping'").fetchone()
        shopping = json.loads(row['value']) if row else None
        items = []
        if shopping:
            for group in ('ingredients', 'additional'):
                for item in shopping[group]:
                    items.append({'name': item['name'], 'description': item.get('description', ''),
                                  'owned': bool(item['is_owned']), 'own': group == 'additional'})
        vouchers = [dict(r) for r in conn.execute(
            'SELECT id,store,value_cents,remaining_cents,version FROM vouchers WHERE remaining_cents>0 ORDER BY created')]
        return {'shopping_updated': row['updated'] if row else None,
                'recipes': [r['name'] for r in shopping['shopping_recipes']] if shopping else [],
                'items': items, 'vouchers': vouchers}

    def routes(self, app, identity):
        @app.get('/api/offline')
        def offline(request: Request):
            with self.db() as conn:
                identity(request, conn)
                return self.snapshot(conn)
