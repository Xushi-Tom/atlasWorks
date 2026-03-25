import os
import re
import unittest

ROUTE_REGISTRY_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "backend", "routeRegistry.py")
)


class RouteRegistryTests(unittest.TestCase):
    def test_route_registry_contains_core_paths(self):
        with open(ROUTE_REGISTRY_PATH, "r", encoding="utf-8") as file_obj:
            content = file_obj.read()

        routes = set(re.findall(r'add_url_rule\("([^"]+)"', content))
        self.assertIn("/", routes)
        self.assertIn("/api/health", routes)
        self.assertIn("/api/dataSources/split", routes)
        self.assertIn("/api/cache/info", routes)
        self.assertIn("/api/tile/indexedTiles", routes)
        self.assertIn("/api/tasks/<taskId>", routes)


if __name__ == "__main__":
    unittest.main()
