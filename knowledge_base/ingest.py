"""Ingest seed PDFs from knowledge_base/tariffs/ into PageIndex.

Idempotent by SHA-256 content hash: skips unchanged PDFs, re-uploads edited ones.
Persists registry after every successful upload so partial progress is saved.
Continues past per-PDF failures; exits non-zero if any PDF failed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import TypedDict

import requests
from dotenv import load_dotenv

logger = logging.getLogger("ingest")

PAGEINDEX_UPLOAD_URL = "https://api.pageindex.ai/doc/"


class RegistryEntry(TypedDict):
    doc_id: str
    sha256: str


class PageIndexError(Exception):
    """Raised when the PageIndex upload returns a non-2xx or malformed response."""


def sha256_of(path: Path) -> str:
    """SHA-256 hex digest of the file bytes."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_registry(path: Path) -> dict[str, RegistryEntry]:
    """Read the registry JSON or return {} if the file does not exist."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_registry(path: Path, registry: dict[str, RegistryEntry]) -> None:
    """Atomically write the registry so a crash mid-save cannot corrupt it."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8"
    )
    os.replace(tmp, path)


def pageindex_upload(pdf_bytes: bytes, filename: str, api_key: str) -> str:
    """POST the PDF to PageIndex and return the doc_id.

    Raises PageIndexError on any non-2xx response or missing doc_id in body.
    """
    response = requests.post(
        PAGEINDEX_UPLOAD_URL,
        headers={"api_key": api_key},
        files={"file": (filename, pdf_bytes, "application/pdf")},
        timeout=120,
    )
    if not response.ok:
        raise PageIndexError(
            f"upload failed: HTTP {response.status_code} — {response.text[:200]}"
        )
    try:
        body = response.json()
    except ValueError as e:
        raise PageIndexError(f"upload response was not JSON: {e}") from e
    doc_id = body.get("doc_id")
    if not doc_id:
        raise PageIndexError(f"upload response missing doc_id: {body}")
    return doc_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Upload PDFs from knowledge_base/tariffs/ to PageIndex.",
    )
    parser.add_argument(
        "--tariffs-dir",
        type=Path,
        default=Path("knowledge_base/tariffs"),
        help="Directory containing PDFs to ingest (default: %(default)s)",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("knowledge_base/doc_registry.json"),
        help="Path to registry JSON (default: %(default)s)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable DEBUG logging."
    )
    args = parser.parse_args(argv)

    load_dotenv()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    api_key = os.getenv("PAGEINDEX_API_KEY")
    if not api_key:
        logger.error(
            "PAGEINDEX_API_KEY not set. Export it in your shell or add it to .env."
        )
        return 1

    if not args.tariffs_dir.is_dir():
        logger.error(
            "Tariffs directory does not exist: %s. Create it and drop PDFs in.",
            args.tariffs_dir,
        )
        return 1

    pdfs = sorted(args.tariffs_dir.glob("*.pdf"))
    if not pdfs:
        logger.warning(
            "No PDFs found in %s — nothing to do.", args.tariffs_dir
        )
        return 0

    registry = load_registry(args.registry)
    uploaded, skipped = 0, 0
    failures: list[tuple[str, str]] = []

    for pdf in pdfs:
        filename = pdf.name
        sha = sha256_of(pdf)
        entry = registry.get(filename)
        if entry and entry.get("sha256") == sha:
            logger.info("%s: unchanged, skipped", filename)
            skipped += 1
            continue
        try:
            pdf_bytes = pdf.read_bytes()
            doc_id = pageindex_upload(pdf_bytes, filename, api_key)
            registry[filename] = {"doc_id": doc_id, "sha256": sha}
            save_registry(args.registry, registry)
            logger.info("%s: uploaded → %s", filename, doc_id)
            uploaded += 1
        except (PageIndexError, requests.RequestException) as e:
            logger.error("%s: %s", filename, e)
            failures.append((filename, str(e)))

    logger.info(
        "Summary: %d uploaded, %d skipped, %d failed",
        uploaded,
        skipped,
        len(failures),
    )
    if failures:
        for fn, err in failures:
            logger.error("FAILED: %s — %s", fn, err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
