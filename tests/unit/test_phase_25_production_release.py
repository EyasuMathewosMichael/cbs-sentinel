from pathlib import Path


def test_phase_25_production_release_artifacts_exist():
    repo_root = Path(__file__).resolve().parents[2]
    prod_dir = repo_root / "deployments" / "production_release"

    readme = prod_dir / "README.md"
    report = prod_dir / "production_release_gate_report.md"

    assert readme.exists()
    assert report.exists()
    assert "v1.0.0" in report.read_text()
    assert "No new functionality" not in report.read_text()
    assert "release-candidate" in report.read_text().lower()
