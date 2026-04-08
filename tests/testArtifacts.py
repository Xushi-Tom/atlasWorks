import os
import sys
import types
import unittest


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

if "psutil" not in sys.modules:
    sys.modules["psutil"] = types.SimpleNamespace(
        cpu_count=lambda: 4,
        virtual_memory=lambda: types.SimpleNamespace(total=8 * 1024 * 1024 * 1024, available=4 * 1024 * 1024 * 1024),
    )

from artifacts import _artifact_type_for, _output_format_for  # noqa: E402


class ArtifactTypeTests(unittest.TestCase):
    def test_3dtiles_job_type_maps_to_3dtiles_artifact(self):
        self.assertEqual(_artifact_type_for("3dtiles"), "3dtiles")
        self.assertEqual(_artifact_type_for("3dtiles-pointcloud"), "3dtiles")
        self.assertEqual(_artifact_type_for("3dtiles-osgb"), "3dtiles")

    def test_3dtiles_job_type_uses_3d_tiles_format(self):
        self.assertEqual(_output_format_for("3dtiles", {"result": {}}), "3d-tiles")
        self.assertEqual(_output_format_for("3dtiles-vector", {"result": {}}), "3d-tiles")


if __name__ == "__main__":
    unittest.main()
