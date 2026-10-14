import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE_PREFIX = Path(r"D:\TOOL\Anaconda")
TARGET_PREFIX = Path(__file__).resolve().parent / ".conda-env"
ROOT_PACKAGES = [
    "python",
    "pip",
    "numpy",
    "matplotlib-base",
    "tk",
    "pandas",
    "openpyxl",
]


def load_records(meta_dir: Path) -> tuple[dict[str, dict], dict[str, Path]]:
    records: dict[str, dict] = {}
    record_paths: dict[str, Path] = {}
    for path in meta_dir.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        records[data["name"]] = data
        record_paths[data["name"]] = path
    return records, record_paths


def dependency_closure(records: dict[str, dict], roots: list[str]) -> set[str]:
    seen: set[str] = set()
    stack = roots[:]
    while stack:
        name = stack.pop()
        if name in seen or name == "__win":
            continue
        record = records.get(name)
        if not record:
            raise RuntimeError(f"Missing package in base env: {name}")
        seen.add(name)
        for dep in record.get("depends", []):
            dep_name = dep.split(" ", 1)[0]
            if dep_name and dep_name not in seen and dep_name != "__win":
                stack.append(dep_name)
    return seen


def collect_files(records: dict[str, dict], packages: set[str]) -> list[tuple[Path, Path]]:
    files: list[tuple[Path, Path]] = []
    for name in sorted(packages):
        for rel in records[name].get("files", []):
            src = BASE_PREFIX / rel
            dst = TARGET_PREFIX / rel
            files.append((src, dst))
    return files


def copy_one(pair: tuple[Path, Path]) -> str | None:
    src, dst = pair
    if not src.exists():
        return f"missing:{src}"
    if dst.exists():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return None


def main() -> None:
    records, record_paths = load_records(BASE_PREFIX / "conda-meta")
    packages = dependency_closure(records, ROOT_PACKAGES)
    files = collect_files(records, packages)

    TARGET_PREFIX.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(max_workers=8) as executor:
        issues = [issue for issue in executor.map(copy_one, files) if issue]

    conda_meta_target = TARGET_PREFIX / "conda-meta"
    conda_meta_target.mkdir(parents=True, exist_ok=True)
    for name in sorted(packages):
        shutil.copy2(record_paths[name], conda_meta_target / record_paths[name].name)

    (conda_meta_target / "history").write_text(
        "# Local project environment materialized from D:\\TOOL\\Anaconda\n"
        f"# Roots: {', '.join(ROOT_PACKAGES)}\n",
        encoding="utf-8",
    )
    (TARGET_PREFIX / ".nonadmin").write_text("", encoding="utf-8")

    print(f"packages={len(packages)}")
    print(f"files={len(files)}")
    print(f"issues={len(issues)}")
    for issue in issues[:20]:
        print(issue)


if __name__ == "__main__":
    main()
