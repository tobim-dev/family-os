"""Guided shopping-list week change (E-09, E-10, E-12, E-16) with a Cookidoo stand-in.

The stand-in behaves like the real account where it matters here: every
shopping-list recipe contributes its own ingredient entries, so shared
ingredients appear several times with the same ID.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace as Row
import tempfile
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from app import create_app
import shopping_week


@dataclass
class Item:
    id: str
    name: str
    is_owned: bool = False
    description: str = ''


RECIPES = {
    'r1': ('Linsen-Dal', [('zwiebel', 'Zwiebel', '1 Stück'), ('linsen', 'Rote Linsen', '200 g')]),
    'r2': ('Kürbis-Risotto', [('zwiebel', 'Zwiebel', '2 Stück'), ('reis', 'Risottoreis', '300 g')]),
    'r3': ('Gemüse-Curry', [('curry', 'Currypaste', '2 EL')]),
    'r4': ('Spinat-Lasagne', [('spinat', 'Blattspinat', '500 g'), ('zwiebel', 'Zwiebel', '1 Stück')]),
}


class Remote:
    def __init__(self):
        self.days = {}
        self.list = []      # [recipe_id, Item] per entry, like the flattened provider list
        self.recipes = []   # shopping-list recipe IDs
        self.additional = [Item('own-1', 'Haferflocken', True), Item('own-2', 'Brot')]
        self.calls = []
        self.sabotage = None

    def put(self, rid):
        self.recipes.append(rid)
        for iid, name, amount in RECIPES[rid][1]:
            self.list.append([rid, Item(iid, name, False, amount)])

    async def get_recipes_in_calendar_week(self, anchor):
        monday = anchor - timedelta(days=anchor.weekday())
        result = []
        for offset in range(7):
            day = str(monday + timedelta(days=offset))
            rows = [Row(id=r, name=RECIPES[r][0], total_time=1800) for r in self.days.get(day, [])]
            result.append(Row(id=day, recipes=rows, customer_recipe_ids=[]))
        return result

    async def get_shopping_list_recipes(self):
        return [Row(id=r, name=RECIPES[r][0], ingredients=[Row(id=i[0]) for i in RECIPES[r][1]])
                for r in self.recipes]

    async def get_ingredient_items(self):
        return [deepcopy(item) for _, item in self.list]

    async def get_additional_items(self):
        return deepcopy(self.additional)

    async def add_ingredient_items_for_recipes(self, ids):
        for rid in ids:
            self.put(rid)
        self.calls.append(('add', tuple(ids)))
        self.damage()

    async def remove_ingredient_items_for_recipes(self, ids):
        self.recipes = [r for r in self.recipes if r not in ids]
        self.list = [entry for entry in self.list if entry[0] not in ids]
        self.calls.append(('remove', tuple(ids)))
        self.damage()

    async def edit_ingredient_items_ownership(self, items):
        for entry in self.list:
            for new in items:
                if entry[1].id == new.id:
                    entry[1] = new
        self.calls.append(('check',))

    def damage(self):
        if self.sabotage == 'drop_shared':
            # Provider drops every entry of a shared ID, also those of other recipes.
            self.list = [e for e in self.list if e[1].id != 'zwiebel']
        elif self.sabotage == 'uncheck':
            for _, item in self.list:
                item.is_owned = False
        elif self.sabotage == 'touch_other':
            for _, item in self.list:
                if item.id == 'linsen':
                    item.description = '999 g'
        elif self.sabotage == 'lose_own':
            self.additional = self.additional[1:]


class WeekSwitchTests(unittest.TestCase):
    start = '2026-10-31'  # Saturday

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name) / 'family.sqlite', demo=True)
        self.meals = self.app.state.meals
        self.meals.demo = False  # Real integration routes, fake provider.
        self.remote = Remote()

        @asynccontextmanager
        async def adapter(credentials=None):
            yield self.remote
        self.meals.adapter = adapter
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8765',
                                 headers={'Origin': 'http://127.0.0.1:8765', 'X-Family-Request': '1'})
        self.client.post('/api/login', json={'user': 'tobi'})
        # Last week: r1 and r4 on the list, one ingredient already checked.
        self.remote.put('r1')
        self.remote.put('r4')
        self.remote.list[1][1].is_owned = True   # Rote Linsen (r1)
        # This week: r2 and r3 planned.
        self.remote.days['2026-10-31'] = ['r2']
        self.remote.days['2026-11-02'] = ['r3']

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def sync(self):
        response = self.client.post('/api/meals/sync', json={'start': self.start})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def step(self, action, recipe_id, expect=200):
        revision = self.client.get('/api/meals', params={'start': self.start}).json()['revision']
        body = {'id': str(uuid4()), 'start': self.start, 'revision': revision,
                'action': action, 'recipe_id': recipe_id}
        response = self.client.post('/api/meals/change', json=body)
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def test_preview_lists_old_new_kept_and_own_items_without_writing(self):
        self.remote.put('r2')
        state = self.sync()
        preview = state['week_switch']
        self.assertEqual([r['id'] for r in preview['remove']], ['r1', 'r4'])
        self.assertEqual(preview['remove'][0]['checked'], ['Rote Linsen'])
        self.assertEqual(preview['remove'][1]['checked'], [])
        self.assertEqual(preview['keep'], [{'id': 'r2', 'name': 'Kürbis-Risotto'}])
        self.assertEqual(preview['add'], [{'id': 'r3', 'name': 'Gemüse-Curry'}])
        self.assertEqual((preview['own_items'], preview['own_checked']), (2, 1))
        self.assertEqual(self.remote.calls, [])

    def test_full_week_switch_keeps_own_items_and_shared_ingredients(self):
        self.remote.put('r2')  # Already on the list, planned again: stays.
        self.sync()
        own_before = deepcopy(self.remote.additional)
        state = self.sync()
        for recipe in state['week_switch']['remove']:
            state = self.step('ingredients_remove', recipe['id'])
        for recipe in state['week_switch']['add']:
            state = self.step('ingredients_add', recipe['id'])
        self.assertEqual(self.remote.recipes, ['r2', 'r3'])
        self.assertEqual(self.remote.additional, own_before)
        names = sorted(item.name for _, item in self.remote.list)
        self.assertEqual(names, ['Currypaste', 'Risottoreis', 'Zwiebel'])
        preview = state['week_switch']
        self.assertEqual((preview['remove'], preview['add']), ([], []))
        self.assertEqual(len(preview['keep']), 2)

    def test_removal_with_duplicate_ids_keeps_other_recipes_entries(self):
        self.remote.put('r2')
        state = self.sync()
        self.assertEqual(state['snapshot']['duplicate_ids']['ingredients'], ['zwiebel'])
        self.step('ingredients_remove', 'r4')
        zwiebel = [(rid, item.description) for rid, item in self.remote.list if item.id == 'zwiebel']
        self.assertEqual(zwiebel, [('r1', '1 Stück'), ('r2', '2 Stück')])

    def test_adding_with_duplicate_ids_keeps_checkmarks(self):
        self.remote.list[0][1].is_owned = True  # Zwiebel of r1 checked.
        self.sync()
        self.step('ingredients_add', 'r2')
        checked = [(rid, item.id) for rid, item in self.remote.list if item.is_owned]
        self.assertEqual(checked, [('r1', 'zwiebel'), ('r1', 'linsen')])

    def test_provider_dropping_shared_entries_needs_review(self):
        self.remote.put('r2')
        self.sync()
        self.remote.sabotage = 'drop_shared'
        self.step('ingredients_remove', 'r4', expect=502)
        state = self.client.get('/api/meals', params={'start': self.start}).json()
        self.assertEqual(state['reviews'][0]['state'], 'review')
        # Further writes stay blocked until someone checks Cookidoo.
        self.remote.sabotage = None
        self.step('ingredients_remove', 'r1', expect=409)
        self.assertEqual(len(self.remote.calls), 1)

    def test_lost_checkmark_on_add_needs_review(self):
        self.sync()
        self.remote.sabotage = 'uncheck'
        self.step('ingredients_add', 'r2', expect=502)

    def test_change_to_untouched_ingredient_needs_review(self):
        self.sync()
        self.remote.sabotage = 'touch_other'
        self.step('ingredients_add', 'r3', expect=502)

    def test_lost_own_item_needs_review(self):
        self.sync()
        self.remote.sabotage = 'lose_own'
        self.step('ingredients_remove', 'r1', expect=502)

    def test_ingredients_missing_from_list_do_not_cause_false_alarm(self):
        # Cookidoo can leave basics like water off the list; they must not block writes.
        RECIPES['r5'] = ('Suppe', [('wasser', 'Wasser', '1 l'), ('zwiebel', 'Zwiebel', '1 Stück')])
        RECIPES['r6'] = ('Brühe', [('wasser', 'Wasser', '2 l')])
        self.addCleanup(RECIPES.pop, 'r5')
        self.addCleanup(RECIPES.pop, 'r6')
        self.remote.put('r5')
        self.remote.put('r6')
        self.remote.list = [e for e in self.remote.list if e[1].id != 'wasser']
        self.remote.days['2026-11-01'] = ['r5']
        self.sync()
        self.step('ingredients_remove', 'r6')
        self.assertEqual(self.remote.recipes, ['r1', 'r4', 'r5'])

    def test_unplanned_recipe_cannot_be_added(self):
        self.sync()
        self.step('ingredients_add', 'r4', expect=409)
        self.assertEqual(self.remote.calls, [])

    def test_already_shopped_is_stored_per_week_and_can_be_undone(self):
        self.sync()
        response = self.client.post('/api/meals/shopped', json={'start': self.start, 'shopped': True})
        self.assertEqual(response.status_code, 200)
        shopped = response.json()['shopped']
        self.assertEqual(shopped['by'], 'tobi')
        other_week = self.client.get('/api/meals', params={'start': '2026-11-07'}).json()
        self.assertIsNone(other_week['shopped'])
        self.assertEqual(self.remote.calls, [])  # nothing written to Cookidoo
        undone = self.client.post('/api/meals/shopped', json={'start': self.start, 'shopped': False}).json()
        self.assertIsNone(undone['shopped'])
        self.assertEqual(self.client.post('/api/meals/shopped', json={'start': '2026-11-01', 'shopped': True}).status_code, 422)


class PlanTests(unittest.TestCase):
    def snapshot(self, **changes):
        value = {
            'start': '2026-10-31',
            'days': [{'day': '2026-10-31', 'recipes': [{'id': 'r2', 'name': 'Neu'}], 'custom_ids': ['c-1']},
                     {'day': '2026-11-01', 'recipes': [{'id': 'r2', 'name': 'Neu'}], 'custom_ids': []}],
            'shopping_recipes': [
                {'id': 'r1', 'name': 'Alt', 'ingredient_ids': ['a']},
                {'id': 'r1', 'name': 'Alt', 'ingredient_ids': ['a']},
                {'id': '01ABC', 'name': 'Eigenes Rezept', 'ingredient_ids': ['b']},
            ],
            'ingredients': [{'id': 'a', 'name': 'Tomate', 'is_owned': True},
                            {'id': 'a', 'name': 'Tomate', 'is_owned': True}],
            'additional': [],
        }
        value.update(changes)
        return value

    def test_duplicates_and_custom_recipes(self):
        preview = shopping_week.plan(self.snapshot())
        self.assertEqual(preview['remove'], [{'id': 'r1', 'name': 'Alt', 'checked': ['Tomate']}])
        self.assertEqual(preview['add'], [{'id': 'r2', 'name': 'Neu'}])
        self.assertEqual([m['id'] for m in preview['manual']], ['01ABC'])
        self.assertEqual(preview['custom_planned'], 1)
        self.assertEqual(preview['own_items'], 0)

    def test_remove_rejects_new_entries(self):
        before = self.snapshot()
        after = deepcopy(before)
        after['shopping_recipes'] = after['shopping_recipes'][2:]
        after['ingredients'] = [{'id': 'a', 'name': 'Tomate', 'is_owned': False}]
        self.assertFalse(shopping_week.preserved('ingredients_remove', 'r1', before, after))
        after['ingredients'] = []
        self.assertTrue(shopping_week.preserved('ingredients_remove', 'r1', before, after))


if __name__ == '__main__':
    unittest.main()
