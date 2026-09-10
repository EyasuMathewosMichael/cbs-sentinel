from pathlib import Path


def test_phase_23_final_acceptance_artifacts_exist():
    repo_root = Path(__file__).resolve().parents[2]
    acceptance_dir = repo_root / "deployments" / "final_acceptance"
    readme = acceptance_dir / "README.md"
    report = acceptance_dir / "enterprise_acceptance_report.md"

    assert readme.exists(), "Phase 23 final acceptance artifact README is required"
    assert report.exists(), "Phase 23 final acceptance report is required"

    readme_text = readme.read_text(encoding="utf-8")
    report_text = report.read_text(encoding="utf-8")

    required_topics = {
        "architecture",
        "test acceptance",
        "security acceptance",
        "performance acceptance",
        "operational acceptance",
        "financial integrity",
        "resilience",
        "DR",
        "integration",
        "operations",
        "documentation",
    }

    for topic in required_topics:
        assert topic.lower() in readme_text.lower() or topic.lower() in report_text.lower()
