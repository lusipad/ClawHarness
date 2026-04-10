from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deploy.package import export_deploy_bundle


class DeployBundleAssetTests(unittest.TestCase):
    def test_remote_provider_examples_keep_shell_disabled_by_default(self) -> None:
        azure = export_deploy_bundle.REPO_ROOT / "deploy" / "config" / "providers.azure-devops.yaml"
        github = export_deploy_bundle.REPO_ROOT / "deploy" / "config" / "providers.github.yaml"

        self.assertIn("enabled: false", azure.read_text(encoding="utf-8"))
        self.assertIn("enabled: false", github.read_text(encoding="utf-8"))

    def test_offline_bundle_scripts_support_shell_only_profile(self) -> None:
        self.assertIn("[switch]$Shell", export_deploy_bundle.UP_OFFLINE_PS1)
        self.assertIn("--profile\", \"shell\"", export_deploy_bundle.UP_OFFLINE_PS1)
        self.assertIn("--shell", export_deploy_bundle.UP_OFFLINE_SH)
        self.assertIn("--profile shell", export_deploy_bundle.UP_OFFLINE_SH)

    def test_export_bundle_includes_bootstrap_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "bundle"
            export_deploy_bundle.export_bundle(output_dir, force=False)

            bootstrap = output_dir / "bootstrap.ps1"
            check_install = output_dir / "check-install.ps1"
            self.assertTrue(bootstrap.is_file())
            self.assertTrue(check_install.is_file())
            self.assertTrue((output_dir / "src" / "deploy" / "windows" / "run-harness-core.ps1").is_file())
            self.assertTrue((output_dir / "src" / "deploy" / "windows" / "install-openclaw.ps1").is_file())

            bootstrap_text = bootstrap.read_text(encoding="utf-8")
            self.assertIn("OPENAI_API_KEY is required", bootstrap_text)
            self.assertIn("[string]$InstallMode = \"docker\"", bootstrap_text)
            self.assertIn("[switch]$Interactive", bootstrap_text)
            self.assertIn("[switch]$Advanced", bootstrap_text)
            self.assertIn("[switch]$InstallDocker", bootstrap_text)
            self.assertIn("[switch]$SkipStart", bootstrap_text)
            self.assertIn("HARNESS_PROVIDER_PROFILE", bootstrap_text)
            self.assertIn("native-core", bootstrap_text)
            self.assertIn("native-openclaw", bootstrap_text)
            self.assertIn("ClawHarness quick bootstrap", bootstrap_text)
            self.assertIn("ClawHarness advanced bootstrap", bootstrap_text)
            self.assertIn("Test-ShouldRunBootstrapWizard", bootstrap_text)
            self.assertIn("Select setup experience", bootstrap_text)
            self.assertIn("Install summary", bootstrap_text)
            self.assertIn("Running final install check", bootstrap_text)
            self.assertIn("Installation failed", bootstrap_text)
            self.assertIn("Common fixes:", bootstrap_text)

            check_install_text = check_install.read_text(encoding="utf-8")
            self.assertIn("[string]$InstallMode = \"docker\"", check_install_text)
            self.assertIn("Join-Path $PSScriptRoot \"compose.yml\"", check_install_text)
            self.assertIn("install_check_ok", check_install_text)

            readme_text = (output_dir / "README.md").read_text(encoding="utf-8")
            self.assertIn("./bootstrap.ps1 -OpenAiApiKey <your-key>", readme_text)
            self.assertIn("./bootstrap.ps1 -Interactive", readme_text)
            self.assertIn("./bootstrap.ps1 -Interactive -Advanced", readme_text)
            self.assertIn("./bootstrap.ps1 -InstallMode native-core -OpenAiApiKey <your-key>", readme_text)
            self.assertIn("./check-install.ps1 -InstallMode docker", readme_text)
            self.assertIn("./check-install.ps1 -InstallMode native-openclaw", readme_text)

    def test_windows_scripts_use_powershell_5_compatible_random_generation(self) -> None:
        for relative in (
            "deploy/windows/bootstrap.ps1",
            "deploy/windows/install-openclaw.ps1",
            "deploy/windows/run-harness.ps1",
            "deploy/windows/run-harness-core.ps1",
        ):
            script_text = (export_deploy_bundle.REPO_ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("RandomNumberGenerator]::Fill", script_text)
            self.assertIn("RandomNumberGenerator]::Create()", script_text)

    def test_native_windows_harness_scripts_support_provider_profile_switching(self) -> None:
        for relative in (
            "deploy/windows/run-harness.ps1",
            "deploy/windows/run-harness-core.ps1",
        ):
            script_text = (export_deploy_bundle.REPO_ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("HARNESS_PROVIDER_PROFILE", script_text)
            self.assertIn("providers.azure-devops.yaml", script_text)
            self.assertIn("providers.github.yaml", script_text)


if __name__ == "__main__":
    unittest.main()
