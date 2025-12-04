from pathlib import Path


def test_requirements_include_ci_tooling():
    root = Path(__file__).resolve().parents[2]
    requirements = (root / "backend" / "requirements.txt").read_text().lower()

    for tool in ["pytest", "pytest-cov", "ruff", "black", "mypy"]:
        assert tool in requirements, f"{tool} missing from requirements"


def test_ci_scripts_exist():
    root = Path(__file__).resolve().parents[2]
    build_script = root / "scripts" / "devcontainer" / "build.sh"
    assert build_script.exists()
    assert "docker build" in build_script.read_text()

