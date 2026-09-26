import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as Row
import unittest

import httpx
from fastapi.testclient import TestClient

from app import create_app
from meal_suggestions import MealSuggestions, local_plan, protein_of, vegetarian

CDN = 'https://assets.tmecosys.com/image/upload/{}/x.jpg'

RECIPES = {
    'r10': ('Rote-Linsen-Dal', 30, ['Rote Linsen', 'Kokosmilch', 'Spinat'], ['Vegetarisch'], 21),
    'r11': ('Kichererbsen-Curry', 40, ['Kichererbsen', 'Tomaten'], ['Hauptgerichte'], 18),
    'r12': ('Tofu-Pfanne', 25, ['Tofu', 'Brokkoli', 'Sojasauce'], ['Vegan'], 27),
    'r13': ('Hähnchen-Curry', 35, ['Hähnchenbrust', 'Reis'], ['Hauptgerichte'], 35),
    'r14': ('Bohnen-Chili sin Carne', 50, ['Kidneybohnen', 'Mais'], ['Vegetarisch'], 20),
    'r15': ('Gemüse-Lasagne', 85, ['Nudelplatten', 'Zucchini', 'Ricotta'], ['Vegetarisch'], 19),
    'r16': ('Pasta mit Sardellen', 20, ['Spaghetti', 'Sardellenfilets'], [], 16),
    'r17': ('Halloumi-Bowl', 35, ['Halloumi', 'Quinoa'], ['Vegetarisch'], 24),
    'r18': ('Spinat-Feta-Quiche', 70, ['Blätterteig', 'Feta', 'Hühnereier'], [], 22),
}


def details(rid):
    name, minutes, ingredients, categories, protein = RECIPES[rid]
    nutrition = [Row(name='pro Portion', recipe_nutritions=[Row(quantity=1, unit_notation='Portion', nutritions=[
        Row(type='kcal', number=500, unittype='kcal'), Row(type='protein', number=protein, unittype='g')])])]
    return Row(id=rid, name=name, total_time=minutes * 60, thumbnail=CDN.format(rid),
               ingredients=[Row(id=f'{rid}-{i}', name=n, description='') for i, n in enumerate(ingredients)],
               categories=[Row(id='c', name=c, notes='') for c in categories], nutrition_groups=nutrition)


class Remote:
    def __init__(self):
        self.days = {}
        self.queries, self.detail_calls = [], []

    async def get_recipes_in_calendar_week(self, anchor):
        monday = anchor - timedelta(days=anchor.weekday())
        return [Row(id=str(monday + timedelta(days=i)), recipes=deepcopy(self.days.get(str(monday + timedelta(days=i)), [])), customer_recipe_ids=[]) for i in range(7)]

    async def get_shopping_list_recipes(self): return []
    async def get_ingredient_items(self): return []
    async def get_additional_items(self): return []

    async def search_recipes(self, query, languages, total_time, page_size):
        self.queries.append((query, total_time))
        return Row(total=len(RECIPES), recipes=[Row(id=rid, name=v[0], thumbnail=CDN.format(rid), image=None, url='') for rid, v in RECIPES.items()])

    async def get_recipe_details(self, rid):
        self.detail_calls.append(rid)
        return details(rid)


class SuggestionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name) / 'family.sqlite', demo=True)
        self.meals = self.app.state.meals
        self.meals.demo = False
        self.remote = Remote()

        @asynccontextmanager
        async def adapter(credentials=None):
            yield self.remote
        self.meals.adapter = adapter
        self.requests = []
        self.claude_reply = None
        self.meals.suggestions = MealSuggestions(self.meals, api_key='test-key', transport=httpx.MockTransport(self.claude))
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8765', headers={'Origin': 'http://127.0.0.1:8765', 'X-Family-Request': '1'})
        self.client.post('/api/login', json={'user': 'tobi'})
        self.start = '2026-10-31'
        self.remote.days['2026-11-02'] = [Row(id='r10', name='Rote-Linsen-Dal', total_time=1800)]  # Monday planned
        self.assertEqual(self.client.post('/api/meals/sync', json={'start': self.start}).status_code, 200)

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def claude(self, request):
        body = json.loads(request.content)
        self.requests.append((request, body))
        if self.claude_reply == 'error':
            return httpx.Response(529, json={'type': 'error'})
        payload = json.loads(body['messages'][0]['content'])
        choices = self.claude_reply(payload) if self.claude_reply else []
        return httpx.Response(200, json={'content': [{'type': 'tool_use', 'name': 'wochenplan', 'input': {'auswahl': choices}}],
                                         'usage': {'input_tokens': 1200, 'output_tokens': 150}})

    def suggest(self, **data):
        body = {'start': self.start, 'use_ai': True}
        body.update(data)
        response = self.client.post('/api/meals/suggest', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def chosen(self, result):
        return {d['day']: d['recipe']['id'] for d in result['days'] if d['recipe']}

    def test_rules_hold_for_local_suggestion(self):
        self.meals.suggestions.api_key = ''
        result = self.suggest()
        self.assertEqual(result['source'], 'lokal')
        self.assertIn('Kein Claude-Schlüssel', result['notice'])
        chosen = self.chosen(result)
        self.assertNotIn('2026-11-02', [d['day'] for d in result['days']])  # already planned day skipped
        self.assertEqual(len(set(chosen.values())), len(chosen))
        self.assertNotIn('r10', chosen.values())  # already in this week
        for rid in ('r13', 'r16'):
            self.assertNotIn(rid, chosen.values())  # meat / fish
        for day, rid in chosen.items():
            limit = 90 if date.fromisoformat(day).weekday() >= 5 else 45
            self.assertLessEqual(RECIPES[rid][1], limit)
        self.assertEqual(self.requests, [])

    def test_claude_receives_only_minimal_anonymous_data(self):
        self.claude_reply = lambda p: [{'tag': t['tag'], 'id': p['kandidaten'][i]['id'], 'grund': 'Abwechslung'} for i, t in enumerate(p['tage'])]
        result = self.suggest(wishes='Kürbis, Pasta')
        [(request, body)] = self.requests
        self.assertEqual(request.headers['x-api-key'], 'test-key')
        self.assertEqual(body['model'], 'claude-haiku-4-5-20251001')
        sent = json.loads(body['messages'][0]['content'])
        self.assertEqual(set(sent), {'tage', 'kandidaten'})
        self.assertEqual(set(sent['tage'][0]), {'tag', 'max_minuten'})
        text = json.dumps(body, ensure_ascii=False)
        for forbidden in ('Tobi', 'Britta', 'Lina', '2026', 'r1', 'Kürbis', 'assets.tmecosys', 'tobi'):
            self.assertNotIn(forbidden, text)
        for candidate in sent['kandidaten']:
            self.assertTrue(set(candidate) <= {'id', 'name', 'minuten', 'eiweiss_g', 'zutaten'})
            self.assertRegex(candidate['id'], r'^k\d+$')
            self.assertNotIn(candidate['name'], ('Hähnchen-Curry', 'Pasta mit Sardellen'))
        self.assertEqual(result['sent'], sent)
        self.assertEqual(result['source'], 'claude')
        self.assertEqual(self.meals.suggestions.usage()['calls'], 1)
        # Wishes are only Cookidoo search terms.
        self.assertIn('Kürbis', [q for q, _ in self.remote.queries])

    def test_invalid_claude_choices_are_rejected_and_filled_locally(self):
        def reply(payload):
            ids = {c['name']: c['id'] for c in payload['kandidaten']}
            return [{'tag': 'Samstag', 'id': ids['Gemüse-Lasagne'], 'grund': 'ok'},
                    {'tag': 'Dienstag', 'id': ids['Gemüse-Lasagne'], 'grund': 'doppelt'},        # duplicate
                    {'tag': 'Mittwoch', 'id': ids['Spinat-Feta-Quiche'], 'grund': 'zu lang'},   # 70 > 45 min
                    {'tag': 'Donnerstag', 'id': 'k999', 'grund': 'erfunden'},                     # unknown
                    {'tag': 'Montag', 'id': ids['Tofu-Pfanne'], 'grund': 'schon geplant'}]       # not requested
        self.claude_reply = reply
        result = self.suggest()
        by_day = {d['day']: d for d in result['days']}
        self.assertEqual(by_day['2026-10-31']['recipe']['id'], 'r15')
        self.assertEqual(by_day['2026-10-31']['source'], 'claude')
        self.assertNotEqual(by_day['2026-11-03']['recipe']['id'], 'r15')
        self.assertEqual(by_day['2026-11-03']['source'], 'lokal')
        self.assertNotEqual(by_day['2026-11-04']['recipe']['id'], 'r18')
        self.assertIn('ergänzt', result['notice'])

    def test_claude_failure_and_monthly_limit_fall_back_locally(self):
        self.claude_reply = 'error'
        result = self.suggest()
        self.assertEqual(result['source'], 'lokal')
        self.assertIn('nicht erreichbar', result['notice'])
        self.meals.suggestions.monthly_calls = 0
        result = self.suggest()
        self.assertIn('Limit', result['notice'])
        self.assertEqual(len(self.requests), 1)

    def test_recent_history_is_excluded_and_details_are_cached(self):
        self.meals.suggestions.api_key = ''
        previous = str(date.fromisoformat(self.start) - timedelta(days=7))
        self.remote.days['2026-10-26'] = [Row(id='r12', name='Tofu-Pfanne', total_time=1500)]
        self.client.post('/api/meals/sync', json={'start': previous})
        self.client.post('/api/meals/sync', json={'start': self.start})
        result = self.suggest()
        self.assertNotIn('r12', self.chosen(result).values())
        calls = len(self.remote.detail_calls)
        self.suggest()
        self.assertEqual(len(self.remote.detail_calls), calls)  # cached details

    def test_suggestion_is_stored_and_never_written_to_cookidoo(self):
        self.meals.suggestions.api_key = ''
        self.suggest()
        state = self.client.get('/api/meals', params={'start': self.start}).json()
        self.assertEqual(state['suggestion']['source'], 'lokal')
        planned = [r['id'] for d in state['snapshot']['days'] for r in d['recipes']]
        self.assertEqual(planned, ['r10'])
        self.assertFalse(state['ai']['ai_available'])  # no key configured in this test
        self.assertEqual(state['ai']['monthly_calls'], 40)
        self.assertIn('usage', state['ai'])

    def test_helpers(self):
        self.assertEqual(protein_of(details('r12').nutrition_groups), 27)
        self.assertIsNone(protein_of([]))
        self.assertEqual(vegetarian({'name': 'Flammkuchen', 'ingredients': ['Speck'], 'categories': []}), 'no')
        self.assertEqual(vegetarian({'name': 'Suppe', 'ingredients': ['Rinderbrühe'], 'categories': []}), 'no')
        self.assertEqual(vegetarian({'name': 'Dal', 'ingredients': ['Fleischtomaten', 'Hühnereier'], 'categories': []}), 'likely')
        self.assertEqual(vegetarian({'name': 'Dal', 'ingredients': ['Linsen'], 'categories': ['Vegetarisch']}), 'ok')
        slots = [{'day': 'a', 'max_minutes': 30}, {'day': 'b', 'max_minutes': 30}]
        candidates = [{'id': 'x', 'minutes': 25, 'protein': 30, 'veg': 'ok', 'topic': 't'}, {'id': 'y', 'minutes': 60, 'protein': 40, 'veg': 'ok', 'topic': 't'}]
        self.assertEqual({k: v['id'] for k, v in local_plan(slots, candidates).items()}, {'a': 'x'})

    def test_demo_makes_no_external_calls(self):
        self.meals.demo = True
        result = self.suggest()
        self.assertEqual(self.requests, [])
        self.assertEqual(self.remote.queries, [])
        self.assertIn('Demo', result['notice'])


    # --- single day (E-19) -------------------------------------------------

    def other(self, day, use_ai=False, expect=200):
        response = self.client.post('/api/meals/suggest/day', json={'start': self.start, 'day': day, 'use_ai': use_ai})
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def test_one_day_is_replaced_from_the_pool_without_new_search(self):
        self.meals.suggestions.api_key = ''
        week = self.suggest()
        before = self.chosen(week)
        day = next(iter(before))
        searches, details = len(self.remote.queries), len(self.remote.detail_calls)
        result = self.other(day)
        after = self.chosen(result)
        self.assertNotEqual(after[day], before[day])
        self.assertEqual({d: r for d, r in after.items() if d != day}, {d: r for d, r in before.items() if d != day})
        self.assertNotIn(after[day], [r for d, r in before.items() if d != day])  # no duplicate in the week
        self.assertNotIn(after[day], ('r10', 'r13', 'r16'))  # planned, meat, fish
        self.assertEqual((len(self.remote.queries), len(self.remote.detail_calls)), (searches, details))
        self.assertIn(before[day], result['rejected'])
        # The rejected dish does not come back for that day.
        again = self.chosen(self.other(day))
        self.assertNotIn(again[day], (before[day], after[day]))

    def test_used_up_pool_searches_again_and_then_reports_clearly(self):
        self.meals.suggestions.api_key = ''
        week = self.suggest()
        day = next(d['day'] for d in week['days'] if d['recipe'])
        seen = set()
        for _ in range(10):
            response = self.client.post('/api/meals/suggest/day', json={'start': self.start, 'day': day, 'use_ai': False})
            if response.status_code != 200:
                break
            seen.add(self.chosen(response.json())[day])
        self.assertEqual(response.status_code, 502)
        self.assertIn('Kein weiteres passendes Gericht', response.json()['detail'])
        self.assertTrue(any(q for q in self.remote.queries))

    def test_claude_gets_one_day_and_only_the_other_dish_names(self):
        self.claude_reply = lambda p: [{'tag': t['tag'], 'id': p['kandidaten'][i]['id'], 'grund': 'Abwechslung'} for i, t in enumerate(p['tage'])]
        week = self.suggest()
        day = next(d['day'] for d in week['days'] if d['recipe'])
        names = sorted(d['recipe']['name'] for d in week['days'] if d['recipe'] and d['day'] != day)
        self.requests.clear()
        result = self.other(day, use_ai=True)
        [(request, body)] = self.requests
        sent = json.loads(body['messages'][0]['content'])
        self.assertEqual(set(sent), {'tage', 'kandidaten', 'bereits_geplant'})
        self.assertEqual(len(sent['tage']), 1)
        self.assertEqual(sorted(sent['bereits_geplant']), names)
        text = json.dumps(sent, ensure_ascii=False)
        for forbidden in ('Tobi', 'Britta', 'Lina', '2026', 'r1'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(result['sent_days'], [sent])
        entry = next(d for d in result['days'] if d['day'] == day)
        self.assertEqual(entry['source'], 'claude')

    def test_single_day_respects_monthly_limit_and_planned_days(self):
        week = self.suggest(use_ai=False)
        day = next(d['day'] for d in week['days'] if d['recipe'])
        self.meals.suggestions.monthly_calls = 0
        result = self.other(day, use_ai=True)
        self.assertIn('Limit', result['notice'])
        self.assertEqual(self.requests, [])
        self.remote.days[day] = [Row(id='r12', name='Tofu-Pfanne', total_time=1500)]
        self.client.post('/api/meals/sync', json={'start': self.start})
        self.assertIn('bereits in Cookidoo geplant', self.other(day, expect=409)['detail'])
        self.assertIn('keinen Vorschlag', self.other('2026-11-02', expect=409)['detail'])

if __name__ == '__main__':
    unittest.main()
