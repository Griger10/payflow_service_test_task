import ast
import subprocess
import sys
from pathlib import Path

import payflow

FORBIDDEN_IMPORTS = {
    "domain": ("payflow.application", "payflow.infra", "payflow.presentation", "payflow.bootstrap"),
    "application": ("payflow.infra", "payflow.presentation", "payflow.bootstrap"),
    "infra": ("payflow.presentation", "payflow.bootstrap"),
    "bootstrap": ("payflow.presentation",),
}


def test_layers_follow_dependency_direction() -> None:
    package_root = Path(payflow.__file__).parent

    violations: list[str] = []
    for layer, forbidden_prefixes in FORBIDDEN_IMPORTS.items():
        for source_path in (package_root / layer).rglob("*.py"):
            tree = ast.parse(source_path.read_text())
            imported_modules = [
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module is not None
            ]
            imported_modules.extend(
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            )
            for module in imported_modules:
                if module.startswith(forbidden_prefixes):
                    violations.append(f"{source_path.relative_to(package_root)} -> {module}")

    assert violations == []


def test_outbox_main_module_is_safe_to_import() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import payflow.presentation.outbox.__main__"],
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )

    assert result.returncode == 0, result.stderr
