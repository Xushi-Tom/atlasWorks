import os
import sys
import tempfile
import types
import unittest


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.jsonify = lambda payload=None, *args, **kwargs: payload
    flask_stub.request = object()
    flask_stub.send_file = lambda path, *args, **kwargs: path
    sys.modules["flask"] = flask_stub

if "psutil" not in sys.modules:
    psutil_stub = types.ModuleType("psutil")
    psutil_stub.virtual_memory = lambda: types.SimpleNamespace(total=8 * 1024 * 1024 * 1024, available=4 * 1024 * 1024 * 1024)
    psutil_stub.cpu_count = lambda logical=True: 4
    sys.modules["psutil"] = psutil_stub

from indexedTilesOps import generateShapefileIndex  # noqa: E402


class IndexedTilesOpsTests(unittest.TestCase):
    def test_generate_shapefile_index_skips_and_cleans_when_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact_names = [
                "tile_index.geojson",
                "tile_index.shp",
                "tile_index.shx",
                "tile_index.dbf",
                "tile_index.prj",
                "tile_index.cpg",
                ".tile_index_hash",
            ]
            for artifact_name in artifact_names:
                with open(os.path.join(temp_dir, artifact_name), "w", encoding="utf-8") as file_obj:
                    file_obj.write("stale")

            result = generateShapefileIndex(
                tileIndex=[{"z": 0, "x": 0, "y": 0, "sourceCount": 1, "sourceFiles": []}],
                outputPath=temp_dir,
                generateShp=False,
            )

            self.assertTrue(result["success"])
            self.assertTrue(result["skipped"])
            self.assertIsNone(result["shpFile"])
            self.assertIsNone(result["geojsonFile"])
            for artifact_name in artifact_names:
                self.assertFalse(os.path.exists(os.path.join(temp_dir, artifact_name)))


if __name__ == "__main__":
    unittest.main()
