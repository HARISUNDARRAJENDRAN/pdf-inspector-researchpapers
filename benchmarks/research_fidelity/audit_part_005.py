# Download transport overrides.
#
# arXiv's large-object responses can end early on hosted CI runners. The
# requests retry adapter only retries response headers, not an interrupted body,
# so resume partial files explicitly with HTTP Range requests. PMC moved its
# article datasets from the legacy FTP paths to a versioned public S3 structure
# in 2026; resolve each article version and its PDF through the current metadata
# objects instead of following stale OA-service FTP URLs.

PMC_S3_HTTPS = "https://pmc-oa-opendata.s3.amazonaws.com"


def valid_pdf_path(path: pathlib.Path) -> bool:
    if not path.exists() or path.stat().st_size < 5_000:
        return False
    with path.open("rb") as handle:
        header = handle.read(16).lstrip()
        handle.seek(max(0, path.stat().st_size - 8_192))
        tail = handle.read()
    return header.startswith(b"%PDF") and b"%%EOF" in tail


def resumable_download(
    session: Any,
    urls: Sequence[str],
    destination: pathlib.Path,
    *,
    validator: Any,
    attempts_per_url: int = 8,
) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    errors: list[str] = []

    if validator(destination):
        return str(destination)

    for url in urls:
        for attempt in range(attempts_per_url):
            offset = partial.stat().st_size if partial.exists() else 0
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            try:
                with session.get(
                    url,
                    headers=headers,
                    stream=True,
                    timeout=(30, 150),
                    allow_redirects=True,
                ) as response:
                    if response.status_code == 416 and validator(partial):
                        partial.replace(destination)
                        return url
                    response.raise_for_status()

                    # A server may ignore Range and return the full object. In
                    # that case restart rather than appending a duplicate body.
                    append = offset > 0 and response.status_code == 206
                    mode = "ab" if append else "wb"
                    with partial.open(mode) as handle:
                        for chunk in response.iter_content(chunk_size=1 << 20):
                            if chunk:
                                handle.write(chunk)
                        handle.flush()
                        os.fsync(handle.fileno())

                if validator(partial):
                    partial.replace(destination)
                    return url
                errors.append(
                    f"{url}: completed response failed validation at {partial.stat().st_size if partial.exists() else 0} bytes"
                )
            except Exception as exc:
                errors.append(f"{url}: attempt {attempt + 1}: {exc}")
            time.sleep(min(12.0, 0.8 * (2**attempt)))
        partial.unlink(missing_ok=True)

    raise AuditError(
        f"unable to download {destination.name}; last errors: "
        + " | ".join(errors[-6:])
    )


def source_archive_valid(path: pathlib.Path) -> bool:
    return path.exists() and path.stat().st_size >= 100


def download_arxiv(session: Any, paper: dict[str, Any], directory: pathlib.Path) -> None:
    source_id = paper["source_id"]
    bare_id = re.sub(r"v\d+$", "", source_id)
    pdf_path = directory / "paper.pdf"
    resumable_download(
        session,
        [
            f"https://arxiv.org/pdf/{source_id}",
            f"https://export.arxiv.org/pdf/{source_id}",
            f"https://arxiv.org/pdf/{bare_id}",
        ],
        pdf_path,
        validator=valid_pdf_path,
    )

    html_path = directory / "reference.html"
    source_path = directory / "source.bin"
    if not html_path.exists() and not source_path.exists():
        for url in (
            f"https://arxiv.org/html/{source_id}",
            f"https://arxiv.org/html/{bare_id}",
        ):
            try:
                data = get_bytes(session, url, timeout=120)
            except Exception:
                continue
            if arxiv_html_looks_valid(data):
                atomic_write(html_path, data)
                paper["reference_kind"] = "arxiv_html"
                break
        else:
            resumable_download(
                session,
                [
                    f"https://arxiv.org/e-print/{source_id}",
                    f"https://export.arxiv.org/e-print/{source_id}",
                    f"https://arxiv.org/e-print/{bare_id}",
                ],
                source_path,
                validator=source_archive_valid,
            )
            paper["reference_kind"] = "latex_source"
    elif html_path.exists():
        paper["reference_kind"] = "arxiv_html"
    else:
        paper["reference_kind"] = "latex_source"
    time.sleep(1.0)


def _pmc_s3_versions(session: Any, pmcid: str) -> list[int]:
    response = session.get(
        PMC_S3_HTTPS + "/",
        params={"list-type": "2", "prefix": f"{pmcid}.", "delimiter": "/"},
        timeout=60,
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    versions: list[int] = []
    for node in root.iter():
        if node.tag.split("}")[-1] != "Prefix" or not node.text:
            continue
        match = re.fullmatch(re.escape(pmcid) + r"\.(\d+)/", node.text)
        if match:
            versions.append(int(match.group(1)))
    return sorted(set(versions), reverse=True)


def _s3_https_url(value: str) -> str:
    if value.startswith("s3://pmc-oa-opendata/"):
        return PMC_S3_HTTPS + "/" + value.split("s3://pmc-oa-opendata/", 1)[1]
    return value


def _pmc_pdf_urls(session: Any, pmcid: str) -> list[str]:
    urls: list[str] = []
    for version in _pmc_s3_versions(session, pmcid):
        stem = f"{pmcid}.{version}"
        metadata_candidates = [
            f"{PMC_S3_HTTPS}/metadata/{stem}.json",
            f"{PMC_S3_HTTPS}/{stem}/{stem}.json",
        ]
        metadata: dict[str, Any] | None = None
        for metadata_url in metadata_candidates:
            try:
                response = session.get(metadata_url, timeout=60)
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                metadata = response.json()
                break
            except Exception:
                continue
        if metadata and metadata.get("pdf_url"):
            urls.append(_s3_https_url(str(metadata["pdf_url"])))
        # Metadata is authoritative, but the conventional object name gives a
        # useful fallback while an inventory update is propagating.
        urls.append(f"{PMC_S3_HTTPS}/{stem}/{stem}.pdf")
    return list(dict.fromkeys(urls))


def download_pmc(session: Any, paper: dict[str, Any], directory: pathlib.Path) -> None:
    pmcid = paper["source_id"]
    xml_path = directory / "reference.xml"
    if not xml_path.exists():
        xml_data = get_bytes(
            session,
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
            timeout=120,
        )
        if len(xml_data) < 1_000 or b"<article" not in xml_data[:20_000]:
            raise AuditError(f"invalid JATS XML for {pmcid}")
        atomic_write(xml_path, xml_data)
    paper["reference_kind"] = "pmc_jats"

    pdf_path = directory / "paper.pdf"
    urls = _pmc_pdf_urls(session, pmcid)
    if not urls:
        raise AuditError(f"PMC S3 has no versioned article objects for {pmcid}")
    resumable_download(session, urls, pdf_path, validator=valid_pdf_path)
