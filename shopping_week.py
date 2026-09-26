"""Guided shopping-list week change and count-based readback checks.

Decisions from 26.09.2026 (O-06, see ANFORDERUNGEN.md E-16):
- "Old" are all shopping-list recipes that are not planned in the chosen
  week (Saturday to Friday). Single recipes can be kept in the preview.
- Old recipes are removed including checked ingredients; the preview lists them.
- Own items (Cookidoo "additional items") are never touched.
- Cookidoo may deliver the same ingredient ID several times. Recipe ingredient
  changes stay possible, but every write is verified by counting entries per ID.

Cookidoo removes ingredients only per recipe, never per single ingredient.
"""
import re
from collections import Counter

RECIPE_ID = re.compile(r'r[0-9]+')


def automatable(recipe_id):
    return bool(RECIPE_ID.fullmatch(recipe_id))


def plan(snapshot):
    """Preview of the week change for the given snapshot. Changes nothing."""
    planned = {}
    for day in snapshot['days']:
        for recipe in day['recipes']:
            planned.setdefault(recipe['id'], recipe['name'])
    custom_planned = sum(len(day['custom_ids']) for day in snapshot['days'])

    on_list = {}
    for recipe in snapshot['shopping_recipes']:
        on_list.setdefault(recipe['id'], recipe)

    remove, keep, manual = [], [], []
    for rid, recipe in on_list.items():
        if rid in planned:
            keep.append({'id': rid, 'name': recipe['name']})
        elif automatable(rid):
            remove.append(removal(recipe, snapshot['ingredients']))
        else:
            manual.append({'id': rid, 'name': recipe['name'],
                           'reason': 'Eigenes Cookidoo-Rezept · bitte direkt in Cookidoo prüfen'})

    add = []
    for rid, name in planned.items():
        if rid in on_list:
            continue
        if automatable(rid):
            add.append({'id': rid, 'name': name})
        else:
            manual.append({'id': rid, 'name': name,
                           'reason': 'Nicht automatisch übertragbar · bitte direkt in Cookidoo ergänzen'})

    own = snapshot['additional']
    return {
        'start': snapshot['start'],
        'remove': remove,
        'keep': keep,
        'add': add,
        'manual': manual,
        'custom_planned': custom_planned,
        'own_items': len(own),
        'own_checked': sum(bool(i['is_owned']) for i in own),
    }


def removal(recipe, ingredients):
    ids = set(recipe['ingredient_ids'])
    checked = sorted({i['name'] for i in ingredients if i['id'] in ids and i['is_owned']})
    return {'id': recipe['id'], 'name': recipe['name'], 'checked': checked}


# --- Readback checks -----------------------------------------------------------
# Entries are compared as multisets. An ID can occur several times; nothing is
# merged or matched by position.

def entries(items, ids=None, loose=False):
    """Counter of ingredient entries, optionally only for the given IDs.

    loose ignores the quantity text: Cookidoo may recalculate the amount of a
    shared ingredient when a recipe is added or removed.
    """
    def key(item):
        if loose:
            return (item['id'], item['name'], bool(item['is_owned']))
        return (item['id'], item['name'], item.get('description', ''), bool(item['is_owned']))
    return Counter(key(i) for i in items if ids is None or i['id'] in ids)


def recipes(snapshot, skip=None):
    return Counter((r['id'], r['name'], tuple(r['ingredient_ids']))
                   for r in snapshot['shopping_recipes'] if r['id'] != skip)


def ingredient_ids(snapshot, recipe_id=None, skip=None):
    return {iid for r in snapshot['shopping_recipes']
            if (recipe_id is None or r['id'] == recipe_id) and r['id'] != skip
            for iid in r['ingredient_ids']}


def preserved(action, recipe_id, before, after):
    """True if an ingredients_add/remove left everything else intact.

    - Own items and the week plan are unchanged.
    - Other shopping-list recipes are unchanged.
    - Entries of IDs the recipe does not use are exactly unchanged.
    - For IDs the recipe uses: no position and no checkmark of another recipe
      is lost; removal never adds entries, adding never loses entries.
    """
    if before['days'] != after['days']:
        return False
    if Counter(map(repr, before['additional'])) != Counter(map(repr, after['additional'])):
        return False
    if recipes(before, skip=recipe_id) != recipes(after, skip=recipe_id):
        return False

    if action == 'ingredients_remove':
        touched = ingredient_ids(before, recipe_id)
    else:
        touched = ingredient_ids(after, recipe_id)
    untouched_before = [i for i in before['ingredients'] if i['id'] not in touched]
    untouched_after = [i for i in after['ingredients'] if i['id'] not in touched]
    if entries(untouched_before) != entries(untouched_after):
        return False

    old = entries(before['ingredients'], touched, loose=True)
    new = entries(after['ingredients'], touched, loose=True)
    if action == 'ingredients_remove':
        # Only entries that existed before may remain.
        if new - old:
            return False
        # Shared ingredients that were on the list must stay. Cookidoo may
        # leave some recipe ingredients off the list entirely (e.g. water).
        listed = {i['id'] for i in before['ingredients']}
        still_needed = ingredient_ids(before, skip=recipe_id) & touched & listed
        present = {i['id'] for i in after['ingredients']}
        return still_needed <= present
    # Adding: every earlier entry (including checkmarks) must still be there.
    return not old - new

