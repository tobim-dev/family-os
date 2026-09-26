import asyncio
from datetime import date, timedelta
from pathlib import Path
import tempfile
from types import SimpleNamespace as Row
import unittest

from fastapi.testclient import TestClient

from app import create_app
from meals import revision, snapshot
from recipe_images import RecipeImages, allowed

CDN = 'https://assets.tmecosys.com/image/upload/t_web_shared_recipe_221x240/img/recipe/ras/Assets/abc.jpg'


class Calendar:
    def __init__(self, thumbnail):
        self.thumbnail = thumbnail

    async def get_recipes_in_calendar_week(self, anchor):
        monday = anchor - timedelta(days=anchor.weekday())
        return [Row(id=str(monday + timedelta(days=i)), customer_recipe_ids=[],
                    recipes=[Row(id='r7', name='Linsen', total_time=2100, thumbnail=self.thumbnail)] if i == 0 else [])
                for i in range(7)]

    async def get_shopping_list_recipes(self): return [Row(id='r8', name='Curry', ingredients=[], thumbnail=self.thumbnail)]
    async def get_ingredient_items(self): return []
    async def get_additional_items(self): return []


class RecipeImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name) / 'family.sqlite', demo=True)
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, url):
        self.calls.append(url)
        if 'broken' in url:
            raise ValueError('status 500')
        return 'image/jpeg', b'\xff\xd8jpeg'

    def service(self):
        return RecipeImages(self.app.state.db, self.tmp.name, demo=False, fetch=self.fetch)

    def test_only_allowlisted_https_hosts(self):
        self.assertTrue(allowed(CDN))
        for url in ('http://assets.tmecosys.com/a.jpg', 'https://evil.example/a.jpg', 'https://assets.tmecosys.com.evil.example/a.jpg',
                    'https://user:pw@assets.tmecosys.com/a.jpg', 'https://assets.tmecosys.com:8443/a.jpg', 'file:///etc/passwd', ''):
            self.assertFalse(allowed(url), url)

    def test_remember_ignores_foreign_urls_and_invalid_ids(self):
        images = self.service()
        images.remember({'r1': CDN, 'r2': 'https://evil.example/x.jpg', '../x': CDN, 'r3': None})
        self.assertEqual(images.available(['r1', 'r2', 'r3', '../x']), {'r1': '/api/meals/image/r1'})

    def test_image_is_fetched_once_and_cached_on_disk(self):
        images = self.service()
        images.remember({'r1': CDN})
        kind, path = images.get('r1')
        self.assertEqual(kind, 'image/jpeg')
        self.assertEqual(path.read_bytes(), b'\xff\xd8jpeg')
        self.assertEqual(images.get('r1')[1], path)
        self.assertEqual(len(self.calls), 1)
        self.assertIsNone(images.get('r99'))
        self.assertIsNone(images.get('../../etc'))

    def test_failed_fetch_is_not_retried_immediately(self):
        images = self.service()
        images.remember({'r1': CDN.replace('abc', 'broken')})
        self.assertIsNone(images.get('r1'))
        self.assertIsNone(images.get('r1'))
        self.assertEqual(len(self.calls), 1)

    def test_demo_never_fetches(self):
        images = RecipeImages(self.app.state.db, self.tmp.name, demo=True, fetch=self.fetch)
        images.remember({'r1': CDN})
        self.assertIsNone(images.get('r1'))
        self.assertEqual(self.calls, [])

    def test_thumbnails_are_collected_without_changing_the_revision(self):
        start = date(2026, 10, 3)
        found = {}
        with_images = asyncio.run(snapshot(Calendar(CDN), start, images=found))
        without = asyncio.run(snapshot(Calendar(None), start))
        self.assertEqual(found, {'r7': CDN, 'r8': CDN})
        self.assertEqual(revision(with_images), revision(without))

    def test_endpoint_requires_login_and_images_opt_into_caching(self):
        client = TestClient(self.app, base_url='http://127.0.0.1:8765', headers={'Origin': 'http://127.0.0.1:8765', 'X-Family-Request': '1'})
        self.assertEqual(client.get('/api/meals/image/r1').status_code, 401)
        client.post('/api/login', json={'user': 'tobi'})
        self.assertEqual(client.get('/api/meals/image/r1').status_code, 404)  # demo: no external image
        self.assertEqual(client.get('/api/state', params={'month': '2026-10'}).headers['cache-control'], 'no-store')
        self.app.state.meals.images = self.service()
        self.app.state.meals.images.remember({'r1': CDN})
        response = client.get('/api/meals/image/r1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'image/jpeg')
        self.assertEqual(response.headers['cache-control'], 'private, max-age=604800')
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        client.close()


if __name__ == '__main__':
    unittest.main()
