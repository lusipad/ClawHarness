from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from deploy.package import package_release_assets

REPO_ROOT = Path(__file__).resolve().parents[1]


class ReleasePackageAssetTests(unittest.TestCase):
    def test_package_release_assets_writes_bundle_archive_manifest_and_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "release"

            result = package_release_assets.package_release_assets(
                output_dir=output_dir,
                label="test-label",
                image_archive=None,
                force=False,
            )

            bundle_archive = output_dir / "artifacts" / "clawharness-deploy-test-label.zip"
            checksum_file = output_dir / "artifacts" / "SHA256SUMS-test-label.txt"
            manifest_file = output_dir / "artifacts" / "artifact-manifest-test-label.json"

            self.assertEqual(bundle_archive, result["bundle_archive"])
            self.assertTrue(bundle_archive.is_file())
            self.assertTrue(checksum_file.is_file())
            self.assertTrue(manifest_file.is_file())

            checksum_text = checksum_file.read_text(encoding="utf-8")
            self.assertIn("clawharness-deploy-test-label.zip", checksum_text)

            manifest_text = manifest_file.read_text(encoding="utf-8")
            self.assertIn('"label": "test-label"', manifest_text)
            self.assertIn("clawharness-deploy-test-label.zip", manifest_text)

            with ZipFile(bundle_archive) as archive:
                names = archive.namelist()
                self.assertIn("clawharness-deploy-test-label/bootstrap.ps1", names)
                self.assertIn("clawharness-deploy-test-label/check-install.ps1", names)

    def test_package_release_assets_copies_optional_offline_image_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "release"
            offline_archive = Path(temp_dir) / "clawharness-images.tar.gz"
            offline_archive.write_bytes(b"offline-image-archive")

            result = package_release_assets.package_release_assets(
                output_dir=output_dir,
                label="offline",
                image_archive=offline_archive,
                force=False,
            )

            copied_archive = output_dir / "artifacts" / "clawharness-images-offline.tar.gz"
            checksum_file = output_dir / "artifacts" / "SHA256SUMS-offline.txt"

            self.assertEqual(copied_archive, result["offline_image_archive"])
            self.assertTrue(copied_archive.is_file())
            self.assertEqual(b"offline-image-archive", copied_archive.read_bytes())
            self.assertIn("clawharness-images-offline.tar.gz", checksum_file.read_text(encoding="utf-8"))

    def test_package_release_assets_keeps_tar_gz_suffix_for_version_like_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "release"
            offline_archive = Path(temp_dir) / "clawharness-images-v3.0.0-alpha.2.tar.gz"
            offline_archive.write_bytes(b"offline-image-archive")

            result = package_release_assets.package_release_assets(
                output_dir=output_dir,
                label="v3.0.0-alpha.2",
                image_archive=offline_archive,
                force=False,
            )

            copied_archive = output_dir / "artifacts" / "clawharness-images-v3.0.0-alpha.2.tar.gz"
            self.assertEqual(copied_archive, result["offline_image_archive"])
            self.assertTrue(copied_archive.is_file())

    def test_cli_entrypoint_supports_script_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "release"
            offline_archive = Path(temp_dir) / "clawharness-images.tar.gz"
            offline_archive.write_bytes(b"offline-image-archive")

            completed = subprocess.run(
                [
                    sys.executable,
                    "deploy/package/package_release_assets.py",
                    "--output",
                    str(output_dir),
                    "--label",
                    "cli",
                    "--image-archive",
                    str(offline_archive),
                    "--force",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, msg=completed.stderr)
            self.assertIn("packaged release assets", completed.stdout)
            self.assertTrue((output_dir / "artifacts" / "clawharness-deploy-cli.zip").is_file())
            self.assertTrue((output_dir / "artifacts" / "clawharness-images-cli.tar.gz").is_file())


if __name__ == "__main__":
    unittest.main()
