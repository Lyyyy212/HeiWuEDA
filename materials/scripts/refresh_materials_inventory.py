#!/usr/bin/env python3
"""Build a traceable inventory for the EasyEDA official material snapshot."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MATERIALS_ROOT = Path(__file__).resolve().parents[1]
SOURCES_ROOT = MATERIALS_ROOT / "sources"
MANIFESTS_ROOT = MATERIALS_ROOT / "manifests"
OFFICIAL_ORG_API = "https://api.github.com/orgs/easyeda/repos"
NPM_PACKAGE_API = "https://registry.npmjs.org/@jlceda%2Fpro-api-types"

CURATED_REPOSITORIES: dict[str, dict[str, str]] = {
    "pro-api-sdk": {
        "group": "core",
        "purpose": "官方扩展开发模板、构建工具和最小示例",
    },
    "easyeda-api-skill": {
        "group": "core",
        "purpose": "官方 API 参考、文档格式资料和 Bridge Server",
    },
    "easyeda-api-i18n": {
        "group": "core",
        "purpose": "官方 API 文档多语言资料",
    },
    "eext-run-api-gateway": {
        "group": "core",
        "purpose": "EasyEDA 客户端侧官方 Bridge 扩展实现",
    },
    "eext-extension-demo": {
        "group": "examples",
        "purpose": "基础扩展结构和常见原理图、PCB 图元操作",
    },
    "eext-api-test-tool": {
        "group": "examples",
        "purpose": "API 测试与 iframe 交互示例",
    },
    "eext-excalidraw": {
        "group": "examples",
        "purpose": "画板和 iframe 集成参考",
    },
    "eext-generate-schematic-from-netlist": {
        "group": "examples",
        "purpose": "由网表创建原理图器件和导线的参考实现",
    },
    "eext-netlist-explorer": {
        "group": "examples",
        "purpose": "原理图器件、引脚和网表拓扑读取参考",
    },
    "eext-export-design-report": {
        "group": "examples",
        "purpose": "PCB 设计检查数据和报告导出参考",
    },
    "eext-datasheet-helper": {
        "group": "examples",
        "purpose": "选中器件、数据手册和 AI 学习交互参考",
    },
    "eext-ai-device-standardization": {
        "group": "examples",
        "purpose": "器件搜索、标准化和原理图修改参考；写操作仅作研究",
    },
    "eext-bom-compare": {
        "group": "examples",
        "purpose": "BOM 比较和 iframe 展示参考",
    },
    "eext-interactive-html-bom": {
        "group": "examples",
        "purpose": "PCB、BOM、图元和网络提取参考",
    },
}

SKIP_DIRECTORIES = {
    ".git",
    "node_modules",
    "build",
    "dist",
    "coverage",
    ".cache",
}
SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".mjs", ".cjs", ".html"}
EDA_CALL_RE = re.compile(r"\beda\.([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_json(url: str, *, attempts: int = 3) -> Any:
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json, application/json",
                "User-Agent": "easyeda-hardware-workbench-material-inventory",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except (OSError, TimeoutError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch JSON after {attempts} attempts: {url}: {last_error}")


def run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def scan_eda_calls(repo: Path) -> list[str]:
    calls: set[str] = set()
    for path in repo.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if any(part in SKIP_DIRECTORIES for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        calls.update(f"eda.{module}.{method}" for module, method in EDA_CALL_RE.findall(text))
    return sorted(calls)


def collect_local_repositories() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for name, metadata in sorted(CURATED_REPOSITORIES.items()):
        repo = SOURCES_ROOT / metadata["group"] / name
        record: dict[str, Any] = {
            "name": name,
            "group": metadata["group"],
            "purpose": metadata["purpose"],
            "localPath": repo.relative_to(MATERIALS_ROOT).as_posix(),
            "trustLevel": "official-implementation",
        }
        if not (repo / ".git").is_dir():
            record["status"] = "missing"
        else:
            record.update(
                {
                    "status": "snapshot-ready",
                    "remote": run_git(repo, "remote", "get-url", "origin"),
                    "commit": run_git(repo, "rev-parse", "HEAD"),
                    "branch": run_git(repo, "branch", "--show-current"),
                    "commitTime": run_git(repo, "show", "-s", "--format=%cI", "HEAD"),
                    "edaCalls": scan_eda_calls(repo),
                }
            )
        records.append(record)
    return records


def collect_official_repository_catalog() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = fetch_json(
            f"{OFFICIAL_ORG_API}?per_page=100&page={page}&sort=updated&direction=desc"
        )
        if not isinstance(payload, list):
            raise RuntimeError("GitHub organization response is not a repository list")
        for repo in payload:
            name = str(repo.get("name") or "")
            if not (
                name.startswith("eext-")
                or name.startswith("pro-api")
                or name.startswith("easyeda-api")
                or name == "jlc-mcli"
            ):
                continue
            license_info = repo.get("license") or {}
            records.append(
                {
                    "name": name,
                    "url": repo.get("html_url"),
                    "cloneUrl": repo.get("clone_url"),
                    "description": repo.get("description"),
                    "defaultBranch": repo.get("default_branch"),
                    "pushedAt": repo.get("pushed_at"),
                    "sizeKiB": repo.get("size"),
                    "license": license_info.get("spdx_id"),
                    "archived": bool(repo.get("archived")),
                    "locallyCurated": name in CURATED_REPOSITORIES,
                }
            )
        if len(payload) < 100:
            break
        page += 1
    return sorted(records, key=lambda item: item["name"])


def collect_documents() -> list[dict[str, Any]]:
    document_root = SOURCES_ROOT / "official-docs" / "html"
    records: list[dict[str, Any]] = []
    for path in sorted(document_root.glob("*.html")):
        relative_url = "/" + path.name.replace("__", "/")
        records.append(
            {
                "url": f"https://prodocs.lceda.cn{relative_url}",
                "localPath": path.relative_to(MATERIALS_ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "trustLevel": "official-documentation",
            }
        )
    return records


def collect_type_package() -> dict[str, Any]:
    package_files = sorted(
        (SOURCES_ROOT / "packages").glob("pro-api-types-*/package/package.json")
    )
    if len(package_files) != 1:
        raise RuntimeError(
            f"expected one pinned pro-api-types package, found {len(package_files)}"
        )
    extracted = package_files[0].parent
    package_json = json.loads(package_files[0].read_text(encoding="utf-8"))
    version = str(package_json["version"])
    registry_status = "live"
    try:
        registry = fetch_json(NPM_PACKAGE_API)
        latest_version = registry.get("dist-tags", {}).get("latest")
        version_info = registry.get("versions", {}).get(version, {})
        dist = version_info.get("dist", {})
        published_at = registry.get("time", {}).get(version)
    except RuntimeError:
        registry_status = "cached-lock"
        existing_lock = MANIFESTS_ROOT / "sources.lock.json"
        previous: dict[str, Any] = {}
        if existing_lock.exists():
            payload = json.loads(existing_lock.read_text(encoding="utf-8"))
            previous = payload.get("typePackage") or {}
        latest_version = previous.get("registryLatestVersion") or previous.get("version") or version
        dist = {
            "tarball": previous.get("registryTarball"),
            "integrity": previous.get("registryIntegrity"),
            "shasum": previous.get("registryShasum"),
        }
        published_at = previous.get("publishedAt")
    declaration = extracted / "index.d.ts"
    text = declaration.read_text(encoding="utf-8")
    counts = {
        kind: len(re.findall(rf"^\s+{kind}\s+[A-Za-z_]", text, flags=re.MULTILINE))
        for kind in ("class", "enum", "interface", "type")
    }
    tarball = SOURCES_ROOT / "packages" / f"jlceda-pro-api-types-{version}.tgz"
    local_tarball_sha1 = sha1_file(tarball)
    return {
        "name": package_json.get("name"),
        "version": version,
        "registryStatus": registry_status,
        "registryLatestVersion": latest_version,
        "updateAvailable": latest_version != version,
        "license": package_json.get("license"),
        "publishedAt": published_at,
        "registryTarball": dist.get("tarball"),
        "registryIntegrity": dist.get("integrity"),
        "registryShasum": dist.get("shasum"),
        "localTarball": tarball.relative_to(MATERIALS_ROOT).as_posix(),
        "localTarballSha1": local_tarball_sha1,
        "localTarballSha256": sha256_file(tarball),
        "registryShasumMatches": (
            None if not dist.get("shasum") else local_tarball_sha1 == dist.get("shasum")
        ),
        "declarationPath": declaration.relative_to(MATERIALS_ROOT).as_posix(),
        "declarationSha256": sha256_file(declaration),
        "declarationCounts": counts,
        "trustLevel": "canonical-signature",
    }


def collect_skill_comparison(local_repositories: list[dict[str, Any]]) -> dict[str, Any]:
    snapshot_repo = next(
        item for item in local_repositories if item["name"] == "easyeda-api-skill"
    )
    snapshot_package = (
        MATERIALS_ROOT / snapshot_repo["localPath"] / "package.json"
    )
    snapshot_version = json.loads(snapshot_package.read_text(encoding="utf-8"))["version"]
    references_root = snapshot_package.parent / "references"
    reference_counts = {
        name: len(list((references_root / name).glob("*.md")))
        for name in ("classes", "enums", "interfaces", "types")
    }
    installed_package = Path.home() / ".codex" / "skills" / "easyeda-api-skill" / "package.json"
    installed_version = None
    if installed_package.exists():
        installed_version = json.loads(installed_package.read_text(encoding="utf-8"))["version"]
    return {
        "officialSnapshotVersion": snapshot_version,
        "officialSnapshotReferenceCounts": reference_counts,
        "installedCodexSkillVersion": installed_version,
        "status": (
            "MATCH"
            if installed_version == snapshot_version
            else "VERSION_DRIFT_REVIEW_REQUIRED"
        ),
        "note": "资料整理不自动升级本机已安装 Skill。",
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    MANIFESTS_ROOT.mkdir(parents=True, exist_ok=True)
    generated_at = utc_now()
    local_repositories = collect_local_repositories()
    type_package = collect_type_package()
    documents = collect_documents()
    repository_catalog_status = "live"
    try:
        catalog = collect_official_repository_catalog()
    except RuntimeError:
        repository_catalog_status = "cached-lock"
        catalog_path = MANIFESTS_ROOT / "official-repository-catalog.json"
        if not catalog_path.exists():
            raise
        catalog = json.loads(catalog_path.read_text(encoding="utf-8")).get(
            "repositories", []
        )

    lock = {
        "schemaVersion": "easyeda.official-materials-lock.v1",
        "generatedAt": generated_at,
        "sourcePolicy": {
            "canonicalSignature": "@jlceda/pro-api-types",
            "canonicalSemantics": "https://prodocs.lceda.cn/cn/api/",
            "officialImplementations": "https://github.com/easyeda",
            "discoveryOnly": "https://jlc-ext.com/",
        },
        "typePackage": type_package,
        "skillComparison": collect_skill_comparison(local_repositories),
        "documents": documents,
        "repositories": local_repositories,
    }
    write_json(MANIFESTS_ROOT / "sources.lock.json", lock)
    write_json(
        MANIFESTS_ROOT / "official-repository-catalog.json",
        {
            "schemaVersion": "easyeda.official-repository-catalog.v1",
            "generatedAt": generated_at,
            "organization": "easyeda",
            "catalogStatus": repository_catalog_status,
            "repositoryCount": len(catalog),
            "repositories": catalog,
        },
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "sourcesLock": str(MANIFESTS_ROOT / "sources.lock.json"),
                "repositoryCatalog": str(
                    MANIFESTS_ROOT / "official-repository-catalog.json"
                ),
                "localRepositoryCount": len(local_repositories),
                "officialRepositoryCount": len(catalog),
                "documentCount": len(documents),
                "typePackageVersion": type_package["version"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
