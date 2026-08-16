#!/usr/bin/env python3
"""Build and evaluate a broad research-paper PDF fidelity corpus.

The harness is intentionally external to the parser. It compares deterministic
Markdown output against source-derived structured references from arXiv HTML /
LaTeX and PubMed Central JATS XML, then emits per-document metrics and failure
clusters. No model is called by the production parser or by the metric code.
"""

from __future__ import annotations

import argparse
import collections
import csv
import dataclasses
import gzip
import hashlib
import html as html_module
import importlib
import io
import json
import math
import os
import pathlib
import random
import re
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import time
import unicodedata
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Iterator, Sequence
from urllib.parse import urlencode


ARXIV_CATEGORIES = [
    "cs.CL",
    "cs.LG",
    "cs.CV",
    "cs.SE",
    "math.NA",
    "math.PR",
    "stat.ML",
    "physics.comp-ph",
    "q-bio.NC",
    "econ.EM",
]
ARXIV_DATE_QUERY = "submittedDate:[202401010000 TO 202412312359]"
PMC_DATE_QUERY = "FIRST_PDATE:[2024-01-01 TO 2024-12-31]"
USER_AGENT = "LearnspaceResearchFidelityAudit/1.0 (public benchmark; contact via GitHub)"


@dataclasses.dataclass
class ReferenceDocument:
    title: str
    full_text: str
    core_text: str
    headings: list[str]
    paragraphs: list[str]
    captions: list[str]
    tables: list[list[list[str]]]
    equations: list[str]
    reference_kind: str
    reference_quality: str


class AuditError(RuntimeError):
    pass


def require_dependency(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise AuditError(
            f"missing Python dependency {name!r}; install benchmark requirements first"
        ) from exc


def requests_session() -> Any:
    requests = require_dependency("requests")
    session = requests.Session()
    retry_cls = require_dependency("urllib3").util.retry.Retry
    adapter_cls = requests.adapters.HTTPAdapter
    retry = retry_cls(
        total=5,
        connect=5,
        read=5,
        backoff_factor=0.8,
        status_forcelist=(408, 429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    adapter = adapter_cls(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def atomic_write(path: pathlib.Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")


def normalize_space(text: str) -> str:
    return " ".join(text.replace("\u00a0", " ").split())


def clean_display_text(text: str) -> str:
    text = html_module.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00ad", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def evenly_spaced(items: Sequence[Any], count: int) -> list[Any]:
    if count <= 0 or not items:
        return []
    if len(items) <= count:
        return list(items)
    if count == 1:
        return [items[len(items) // 2]]
    indexes = [round(i * (len(items) - 1) / (count - 1)) for i in range(count)]
    return [items[index] for index in indexes]


def select_arxiv(session: Any, total: int) -> list[dict[str, Any]]:
    per_category = max(1, math.ceil(total / len(ARXIV_CATEGORIES)))
    selected: list[dict[str, Any]] = []
    atom_ns = {"atom": "http://www.w3.org/2005/Atom"}
    for category in ARXIV_CATEGORIES:
        query = f"cat:{category} AND {ARXIV_DATE_QUERY}"
        params = {
            "search_query": query,
            "start": "0",
            "max_results": "100",
            "sortBy": "submittedDate",
            "sortOrder": "ascending",
        }
        url = "https://export.arxiv.org/api/query?" + urlencode(params)
        response = session.get(url, timeout=60)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        entries: list[dict[str, Any]] = []
        for entry in root.findall("atom:entry", atom_ns):
            abs_url = entry.findtext("atom:id", default="", namespaces=atom_ns)
            source_id = abs_url.rsplit("/", 1)[-1]
            if not source_id:
                continue
            title = clean_display_text(
                entry.findtext("atom:title", default="", namespaces=atom_ns)
            )
            published = entry.findtext(
                "atom:published", default="", namespaces=atom_ns
            )
            entries.append(
                {
                    "id": f"arxiv_{safe_id(source_id)}",
                    "provider": "arxiv",
                    "source_id": source_id,
                    "category": category,
                    "title": title,
                    "published": published,
                }
            )
        selected.extend(evenly_spaced(entries, per_category))
        time.sleep(3.0)
    deduped = {entry["source_id"]: entry for entry in selected}
    return list(deduped.values())[:total]


def pmc_journal_name(record: dict[str, Any]) -> str:
    journal_info = record.get("journalInfo") or {}
    journal = journal_info.get("journal") or {}
    return (
        journal.get("title")
        or record.get("journalTitle")
        or record.get("journalAbbreviation")
        or "unknown"
    )


def select_pmc(session: Any, total: int) -> list[dict[str, Any]]:
    queries = [
        f"OPEN_ACCESS:Y AND HAS_PDF:Y AND {PMC_DATE_QUERY}",
        f"OPEN_ACCESS:Y AND IN_EPMC:Y AND {PMC_DATE_QUERY}",
    ]
    records: list[dict[str, Any]] = []
    for query in queries:
        params = {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": "1000",
        }
        response = session.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params=params,
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        records = payload.get("resultList", {}).get("result", [])
        if records:
            break
    candidates: list[dict[str, Any]] = []
    for record in records:
        pmcid = record.get("pmcid")
        if not pmcid:
            continue
        journal = clean_display_text(pmc_journal_name(record))
        title = clean_display_text(record.get("title") or "")
        candidates.append(
            {
                "id": f"pmc_{safe_id(pmcid)}",
                "provider": "pmc",
                "source_id": pmcid,
                "journal": journal,
                "category": record.get("pubType") or "journal-article",
                "title": title,
                "published": record.get("firstPublicationDate") or "",
            }
        )
    candidates.sort(key=lambda item: (item["journal"].casefold(), item["source_id"]))
    chosen: list[dict[str, Any]] = []
    journal_counts: collections.Counter[str] = collections.Counter()
    for candidate in candidates:
        key = candidate["journal"].casefold()
        if journal_counts[key] >= 2:
            continue
        chosen.append(candidate)
        journal_counts[key] += 1
        if len(chosen) >= total:
            break
    if len(chosen) < total:
        seen = {item["source_id"] for item in chosen}
        for candidate in candidates:
            if candidate["source_id"] in seen:
                continue
            chosen.append(candidate)
            if len(chosen) >= total:
                break
    return chosen


def command_select(args: argparse.Namespace) -> None:
    session = requests_session()
    entries = select_arxiv(session, args.arxiv)
    entries.extend(select_pmc(session, args.pmc))
    manifest = {
        "schema": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "selection": {
            "arxiv_count": args.arxiv,
            "pmc_count": args.pmc,
            "arxiv_categories": ARXIV_CATEGORIES,
            "arxiv_date_query": ARXIV_DATE_QUERY,
            "pmc_date_query": PMC_DATE_QUERY,
        },
        "papers": entries,
    }
    out = pathlib.Path(args.out)
    atomic_write(out, json.dumps(manifest, indent=2, ensure_ascii=False).encode())
    print(f"selected {len(entries)} papers -> {out}")


def valid_pdf(data: bytes) -> bool:
    return len(data) > 5000 and data.lstrip().startswith(b"%PDF")


def get_bytes(session: Any, url: str, *, timeout: int = 120) -> bytes:
    response = session.get(url, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    return response.content


def arxiv_html_looks_valid(data: bytes) -> bool:
    if len(data) < 5000:
        return False
    lower = data[:20000].lower()
    return b"<html" in lower and (
        b"ltx_document" in lower or b"ltx_title" in lower or b"math" in lower
    )


def download_arxiv(session: Any, paper: dict[str, Any], directory: pathlib.Path) -> None:
    source_id = paper["source_id"]
    pdf_path = directory / "paper.pdf"
    if not pdf_path.exists():
        pdf = get_bytes(session, f"https://export.arxiv.org/pdf/{source_id}.pdf")
        if not valid_pdf(pdf):
            raise AuditError(f"invalid arXiv PDF for {source_id}")
        atomic_write(pdf_path, pdf)
    html_path = directory / "reference.html"
    source_path = directory / "source.bin"
    if not html_path.exists() and not source_path.exists():
        html_candidates = [
            f"https://arxiv.org/html/{source_id}",
            f"https://arxiv.org/html/{re.sub(r'v\\d+$', '', source_id)}",
        ]
        for url in html_candidates:
            try:
                data = get_bytes(session, url, timeout=90)
            except Exception:
                continue
            if arxiv_html_looks_valid(data):
                atomic_write(html_path, data)
                paper["reference_kind"] = "arxiv_html"
                break
        else:
            source = get_bytes(session, f"https://export.arxiv.org/e-print/{source_id}")
            atomic_write(source_path, source)
            paper["reference_kind"] = "latex_source"
    elif html_path.exists():
        paper["reference_kind"] = "arxiv_html"
    else:
        paper["reference_kind"] = "latex_source"
    time.sleep(1.0)


def replace_ftp_with_https(url: str) -> str:
    if url.startswith("ftp://ftp.ncbi.nlm.nih.gov/"):
        return "https://ftp.ncbi.nlm.nih.gov/" + url.split(
            "ftp://ftp.ncbi.nlm.nih.gov/", 1
        )[1]
    return url


def parse_pmc_oa_links(xml_data: bytes) -> dict[str, str]:
    links: dict[str, str] = {}
    root = ET.fromstring(xml_data)
    for link in root.findall(".//link"):
        fmt = (link.attrib.get("format") or "").lower()
        href = link.attrib.get("href") or ""
        if fmt and href:
            links[fmt] = replace_ftp_with_https(href)
    return links


def extract_pdf_from_tgz(data: bytes) -> bytes | None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = [member for member in archive.getmembers() if member.isfile()]
        pdf_members = [member for member in members if member.name.lower().endswith(".pdf")]
        if not pdf_members:
            return None
        pdf_members.sort(key=lambda member: member.size, reverse=True)
        handle = archive.extractfile(pdf_members[0])
        return handle.read() if handle else None


def download_pmc(session: Any, paper: dict[str, Any], directory: pathlib.Path) -> None:
    pmcid = paper["source_id"]
    xml_path = directory / "reference.xml"
    if not xml_path.exists():
        xml_data = get_bytes(
            session,
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
        )
        if len(xml_data) < 1000 or b"<article" not in xml_data[:10000]:
            raise AuditError(f"invalid JATS XML for {pmcid}")
        atomic_write(xml_path, xml_data)
    paper["reference_kind"] = "pmc_jats"

    pdf_path = directory / "paper.pdf"
    if pdf_path.exists():
        return
    oa_xml = get_bytes(
        session, f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmcid}"
    )
    links = parse_pmc_oa_links(oa_xml)
    pdf_data: bytes | None = None
    if "pdf" in links:
        candidate = get_bytes(session, links["pdf"])
        if valid_pdf(candidate):
            pdf_data = candidate
    if pdf_data is None and "tgz" in links:
        archive_data = get_bytes(session, links["tgz"], timeout=240)
        candidate = extract_pdf_from_tgz(archive_data)
        if candidate and valid_pdf(candidate):
            pdf_data = candidate
    if pdf_data is None:
        raise AuditError(f"PMC OA API did not yield a PDF for {pmcid}")
    atomic_write(pdf_path, pdf_data)


def count_pdf_pages(path: pathlib.Path) -> int:
    pypdf = require_dependency("pypdf")
    with path.open("rb") as handle:
        return len(pypdf.PdfReader(handle, strict=False).pages)


def command_download(args: argparse.Namespace) -> None:
    manifest_path = pathlib.Path(args.manifest)
    manifest = json.loads(manifest_path.read_text())
    root = pathlib.Path(args.root)
    session = requests_session()
    failures: list[dict[str, str]] = []
    for index, paper in enumerate(manifest["papers"], 1):
        directory = root / paper["id"]
        directory.mkdir(parents=True, exist_ok=True)
        print(f"[{index}/{len(manifest['papers'])}] download {paper['id']}", flush=True)
        try:
            if paper["provider"] == "arxiv":
                download_arxiv(session, paper, directory)
            elif paper["provider"] == "pmc":
                download_pmc(session, paper, directory)
            else:
                raise AuditError(f"unsupported provider {paper['provider']}")
            pdf_path = directory / "paper.pdf"
            paper["pdf_path"] = str(pdf_path.relative_to(root))
            paper["pdf_bytes"] = pdf_path.stat().st_size
            paper["page_count"] = count_pdf_pages(pdf_path)
            paper["download_status"] = "ok"
        except Exception as exc:
            paper["download_status"] = "failed"
            paper["download_error"] = str(exc)
            failures.append({"id": paper["id"], "error": str(exc)})
            print(f"download failed for {paper['id']}: {exc}", file=sys.stderr)
        atomic_write(
            manifest_path,
            json.dumps(manifest, indent=2, ensure_ascii=False).encode(),
        )
    print(f"downloaded {len(manifest['papers']) - len(failures)} papers; failures={len(failures)}")
    if failures and len(failures) > max(5, len(manifest["papers"]) // 5):
        raise AuditError(f"too many download failures: {len(failures)}")

