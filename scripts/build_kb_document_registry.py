#!/usr/bin/env python3
"""从清洗清单生成运行时知识库文档元数据表。

百炼的切片检索结果不保证返回文章尾部元数据。本脚本将导入时已经核验过的
文档信息压缩为一个可随应用部署的 JSON，用 document_id 恢复标题、发布平台、
日期和原文链接，并执行转载发布主体规则。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

FIELDS = (
    "title",
    "source_platform",
    "publisher",
    "evidence_level",
    "published_at",
    "source_url",
    "publisher_verification",
    "evidence_eligibility",
    "time_validity",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    documents: dict[str, dict[str, str]] = {}
    with args.manifest.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            document_id = str(record.get("document_id") or "").strip()
            if not document_id:
                raise ValueError(f"missing document_id at line {line_number}")
            if document_id in documents:
                raise ValueError(f"duplicate document_id: {document_id}")
            documents[document_id] = {
                field: str(record.get(field) or "") for field in FIELDS
            }

    payload = {
        "schema_version": "kb-document-registry-v1",
        "document_count": len(documents),
        "documents": documents,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(json.dumps({"documents": len(documents), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
