from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from deploy.package import export_deploy_bundle


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Package ClawHarness deployment artifacts for CI or release workflows")
    parser.add_argument("--output", required=True, help="target directory for packaged artifacts")
    parser.add_argument("--label", default="local", help="artifact label suffix, for example a tag, sha, or run number")
    parser.add_argument(
        "--image-archive",
        default="",
        help="optional path to a prebuilt offline Docker image archive that should be copied into the packaged output",
    )
    parser.add_argument("--force", action="store_true", help="overwrite the output directory if it already exists")
    return parser


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def package_release_assets(output_dir: Path, label: str, image_archive: Path | None, force: bool) -> dict[str, object]:
    if output_dir.exists():
        if not force:
            raise FileExistsError(f"Output directory already exists: {output_dir}")
        shutil.rmtree(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    staging_root = output_dir / "staging"
    bundle_dir = staging_root / f"clawharness-deploy-{label}"
    export_deploy_bundle.export_bundle(bundle_dir, force=False)

    archives_dir = output_dir / "artifacts"
    archives_dir.mkdir(parents=True, exist_ok=True)

    bundle_archive_base = archives_dir / f"clawharness-deploy-{label}"
    bundle_zip = Path(shutil.make_archive(str(bundle_archive_base), "zip", root_dir=staging_root, base_dir=bundle_dir.name))

    files: list[Path] = [bundle_zip]
    copied_image_archive: Path | None = None
    if image_archive is not None:
      if not image_archive.is_file():
          raise FileNotFoundError(f"Offline image archive not found: {image_archive}")
      copied_image_archive = archives_dir / f"clawharness-images-{label}.tar"
      shutil.copy2(image_archive, copied_image_archive)
      files.append(copied_image_archive)

    checksum_lines: list[str] = []
    manifest_files: list[dict[str, object]] = []
    for file_path in files:
        checksum = sha256_file(file_path)
        checksum_lines.append(f"{checksum}  {file_path.name}")
        manifest_files.append(
            {
                "name": file_path.name,
                "path": str(file_path.resolve()),
                "sha256": checksum,
                "size_bytes": file_path.stat().st_size,
            }
        )

    checksums_path = archives_dir / f"SHA256SUMS-{label}.txt"
    checksums_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    manifest = {
        "label": label,
        "bundle_dir": str(bundle_dir.resolve()),
        "bundle_archive": str(bundle_zip.resolve()),
        "offline_image_archive": str(copied_image_archive.resolve()) if copied_image_archive is not None else None,
        "files": manifest_files,
        "checksums_file": str(checksums_path.resolve()),
    }
    manifest_path = archives_dir / f"artifact-manifest-{label}.json"
    write_json(manifest_path, manifest)

    return {
        "bundle_dir": bundle_dir,
        "bundle_archive": bundle_zip,
        "offline_image_archive": copied_image_archive,
        "checksums_file": checksums_path,
        "manifest_file": manifest_path,
    }


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    image_archive = Path(args.image_archive).resolve() if args.image_archive else None
    result = package_release_assets(
        output_dir=Path(args.output).resolve(),
        label=args.label,
        image_archive=image_archive,
        force=args.force,
    )
    print(f"packaged release assets in {Path(args.output).resolve()}")
    print(f"bundle archive: {result['bundle_archive']}")
    if result["offline_image_archive"] is not None:
        print(f"offline image archive: {result['offline_image_archive']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
