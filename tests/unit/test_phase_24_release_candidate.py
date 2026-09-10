from pathlib import Path


def test_phase_24_release_candidate_gate_artifacts_exist():
    repo_root = Path(__file__).resolve().parents[2]
    release_dir = repo_root / "deployments" / "release_candidate"

    readme = release_dir / "README.md"
    report = release_dir / "release_candidate_gate_report.md"
    sbom = release_dir / "sbom.json"

    assert readme.exists()
    assert report.exists()
    assert sbom.exists()
    assert "v1.0.0-rc1" in report.read_text()
    assert "Feature development is frozen" in report.read_text()
    assert "all tests pass" in report.read_text().lower()
    assert "no critical/high findings remain" in report.read_text().lower()
    assert "git working tree is clean" in report.read_text().lower()
    assert "documentation is complete" in report.read_text().lower()
    assert "release artifacts are reproducible" in report.read_text().lower()
    assert "sbom exists" in report.read_text().lower()
    assert "security validation is complete" in report.read_text().lower()
