"""Host-only tests. No valid provider is supplied and no graphics device is opened."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "bin" / "armada_model_probe.exe"


@unittest.skipUnless(os.name == 'nt', 'Host checks require the Windows helper runtime')
class ProbeHostTests(unittest.TestCase):
    def invoke(self, args, expected):
        result = subprocess.run([str(EXE), *args], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, expected)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"")

    def test_actual_cpp_numeric_fixtures(self):
        # Runs the production decoder, RGB accumulator and row scanner in the
        # same executable before any path/provider/graphics operation. Fixtures:
        # zero, constant red, varying-alpha constant RGB, structured finite RGB,
        # infinity, exponent endpoints, nonzero offset/padded rows, and positive
        # versus negative checker/luminance correlation.
        self.invoke(["--numeric-self-test"], 0)

    def test_negative_cli(self):
        with tempfile.TemporaryDirectory(prefix="probe-host-", dir=ROOT / "tests") as tmp:
            folder = Path(tmp)
            report = folder / "new.ndjson"
            cases = [
                ("no_arguments", [], 2),
                ("one_argument", [str(folder)], 2),
                ("relative_bundle_rejected", ["relative", str(report)], 2),
                ("relative_report_rejected", [str(folder), "relative.ndjson"], 2),
                ("dos_device_component_rejected", [str(folder / "NUL.txt"), str(report)], 2),
            ]
            for name, args, code in cases:
                with self.subTest(name=name):
                    self.invoke(args, code)
                    self.assertFalse(report.exists())
            self.invoke([str(folder), str(report)], 1)
            records = [json.loads(line) for line in report.read_text().splitlines()]
            result = records[1]
            self.assertEqual(result["stage"], "bundle_file_type")
            self.assertFalse(result["passed"])
            self.assertFalse(result["rgb_validation_passed"])
            self.assertEqual(type(result["rgb_frames_checked"]), int)
            self.assertEqual(result["rgb_frames_checked"], 0)
            self.assertEqual(result["exposure"], "unit")
            self.assertEqual(result["dispatches_completed"], 0)
            self.assertLess(report.stat().st_size, 16 * 1024)
            original = report.read_bytes()
            self.invoke([str(folder), str(report)], 2)
            self.assertEqual(report.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
