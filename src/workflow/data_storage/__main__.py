"""python -m src.workflow.data_storage <文件或目录> [--recursive] [--dry-run]"""

import argparse
import asyncio
import json
import os
from dataclasses import asdict, replace
from pathlib import Path

from .config import StorageConfig
from .data_load import SUPPORTED_EXTENSIONS
from .pipeline import ingest_document, prepare_document


def collect_files(path: Path, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise ValueError("输入路径不存在或不是文件/目录")
    files = []
    for root, directories, names in os.walk(path, followlinks=False):
        directories[:] = sorted(d for d in directories if not d.startswith(".")
                                and not (Path(root) / d).is_symlink())
        for name in sorted(names):
            candidate = Path(root) / name
            if candidate.suffix.lower() in SUPPORTED_EXTENSIONS and not candidate.is_symlink():
                files.append(candidate)
        if not recursive:
            break
    if not files:
        raise ValueError("目录内没有支持的文档")
    return files


async def run(args) -> int:
    config = StorageConfig.from_env()
    if args.collection:
        config = replace(config, collection_name=args.collection)
    files = collect_files(Path(args.path).expanduser(), args.recursive)
    if len(files) != 1 and args.document_id is not None:
        raise ValueError("--document-id 只能用于单个文件")
    report = {"mode": "dry_run" if args.dry_run else "ingest", "successes": [], "failures": []}
    for file in files:
        try:
            if args.dry_run:
                path, digest, chunks = await asyncio.to_thread(prepare_document, file, config)
                result = {"filename": path.name, "file_sha256": digest, "chunk_count": len(chunks)}
            else:
                result = asdict(await ingest_document(file, document_id=args.document_id, config=config))
            report["successes"].append({"source": str(file), **result})
            print(f"OK: {file.name} ({result['chunk_count']} chunks)")
        except Exception as exc:
            # SDK 和解析器异常可能含凭据或正文，仅报告类型；已知校验错误保留说明。
            message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
            report["failures"].append({"source": str(file), "error": message})
            print(f"FAILED: {file.name}: {message}")
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {target} (success={len(report['successes'])}, failed={len(report['failures'])})")
    return 1 if report["failures"] else 0


def main():
    parser = argparse.ArgumentParser(description="RAG 离线文档入库（会调用 Embedding 和 Milvus 服务）")
    parser.add_argument("path", help="单文件或目录")
    parser.add_argument("--recursive", action="store_true", help="递归扫描子目录")
    parser.add_argument("--dry-run", action="store_true", help="仅本地解析分块，不调用外部服务")
    parser.add_argument("--collection", help="覆盖 MILVUS_COLLECTION")
    parser.add_argument("--document-id", help="单文件的业务文档 ID，默认使用文件摘要")
    parser.add_argument("--report", default="output/ingestion_report.json", help="本次报告路径，会覆盖已有文件")
    args = parser.parse_args()
    try:
        code = asyncio.run(run(args))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"参数或文件错误：{exc}\n")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
