from __future__ import annotations

import csv
import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree


MAX_UPLOAD_BYTES = 2 * 1024 * 1024
ALLOWED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".docx", ".xlsx"}


class SandboxViolation(ValueError):
    pass


def _validate_archive(archive: zipfile.ZipFile) -> None:
    if len(archive.infolist()) > 500:
        raise SandboxViolation("压缩包文件数量超过沙箱上限")
    expanded = 0
    for member in archive.infolist():
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts:
            raise SandboxViolation("检测到压缩包路径穿越")
        expanded += member.file_size
        if expanded > 20 * 1024 * 1024:
            raise SandboxViolation("解压后内容超过沙箱上限")


def _xml_text(raw: bytes) -> str:
    root = ElementTree.fromstring(raw)
    return " ".join(node.text.strip() for node in root.iter() if node.text and node.text.strip())


def _extract_office(content: bytes, extension: str) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        _validate_archive(archive)
        if extension == ".docx":
            names = ["word/document.xml"]
            chunks = []
            for name in names:
                try:
                    chunks.append(_xml_text(archive.read(name)))
                except (KeyError, ElementTree.ParseError):
                    continue
            return "\n".join(chunks)
        else:
            namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            shared_strings = []
            try:
                root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                for item in root.findall("x:si", namespace):
                    shared_strings.append("".join(item.itertext()).strip())
            except (KeyError, ElementTree.ParseError):
                pass

            rows = []
            names = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
            for name in names[:30]:
                try:
                    root = ElementTree.fromstring(archive.read(name))
                except (KeyError, ElementTree.ParseError):
                    continue
                for row in root.findall(".//x:sheetData/x:row", namespace):
                    values = []
                    for cell in row.findall("x:c", namespace):
                        cell_type = cell.attrib.get("t")
                        value_node = cell.find("x:v", namespace)
                        inline_node = cell.find("x:is", namespace)
                        value = ""
                        if cell_type == "inlineStr" and inline_node is not None:
                            value = "".join(inline_node.itertext()).strip()
                        elif value_node is not None and value_node.text is not None:
                            value = value_node.text.strip()
                            if cell_type == "s":
                                try:
                                    value = shared_strings[int(value)]
                                except (ValueError, IndexError):
                                    value = ""
                        if value:
                            values.append(value)
                    if values:
                        rows.append(" | ".join(values))
            return "\n".join(rows)


def inspect_document(filename: str, content: bytes) -> dict:
    """在一次性目录内解析知识文件，所有清理都放在 finally 中。

    不启动子进程、不使用 shell，也不把用户文件写到项目目录。生产环境可将此
    适配器替换为容器/微虚机沙箱，但 API 契约保持不变。
    """
    safe_name = Path(filename or "upload.txt").name
    if safe_name != filename or not safe_name:
        raise SandboxViolation("文件名包含非法路径")
    extension = Path(safe_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise SandboxViolation("仅支持 TXT、Markdown、CSV、JSON、DOCX、XLSX")
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise SandboxViolation("文件为空或超过 2MB")
    sandbox_dir = Path(tempfile.mkdtemp(prefix="ecom-kb-sandbox-"))
    try:
        mapped_file = sandbox_dir / safe_name
        mapped_file.write_bytes(content)
        if extension in {".docx", ".xlsx"}:
            text = _extract_office(content, extension)
        else:
            text = content.decode("utf-8", errors="strict")
            if extension == ".json":
                text = json.dumps(json.loads(text), ensure_ascii=False)
            elif extension == ".csv":
                rows = list(csv.reader(io.StringIO(text)))
                text = "\n".join(" | ".join(row) for row in rows[:1000])
        normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if not normalized:
            raise SandboxViolation("未提取到可用文本")
        return {"filename": safe_name, "extension": extension, "text": normalized[:50000], "bytes": len(content), "sandbox": "ephemeral_local_adapter", "cleanup": "finally"}
    except (UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise SandboxViolation(f"文件格式无效：{type(exc).__name__}") from exc
    finally:
        shutil.rmtree(sandbox_dir, ignore_errors=True)
