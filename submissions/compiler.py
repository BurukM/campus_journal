"""
PDF to HTML compilation engine for Campus Journal.

Locates the "Technical Design Brief" PDF (or variations such as "Design Brief",
with optional numbers/underscores/hyphens) within uploaded submission packages,
and compiles it into high-fidelity, responsive HTML.

Design goals:
- Zero distortion for tables, charts, vector graphs, diagrams, and figures.
- Crisp vector rendering with embedded raster images.
- Fully active, clickable links:
    * PDF link annotations (external URLs, internal page anchors).
    * Auto-detected plain text URLs and DOIs.
- Responsive scaling across desktop, tablet, and mobile devices.
"""

import io
import os
import re
import zipfile
import pymupdf
from django.utils import timezone


class BriefFileNotFoundError(Exception):
    """Raised when no suitable Technical Design Brief PDF is found in the archive."""
    pass


class BriefCompilationError(Exception):
    """Raised when PDF conversion fails."""
    pass


def find_technical_design_brief_file(file_names):
    """
    Search a list of file paths (from zipfile.namelist() or directory)
    and find the PDF that represents the Technical Design Brief.

    Handles:
    - Variations like numbers after it:
        'Technical Design Brief 1.pdf', 'technical_design_brief_2.pdf',
        'Technical-Design-Brief-v3.pdf', 'technical_design_brief_final.pdf'
    - Minor spelling variations or typos:
        'technical design brif.pdf', 'technical-design-brif-1.pdf'
    - 'Design brief' names:
        'Design Brief.pdf', 'design_brief_1.pdf', 'design-brief.pdf'
    - Files inside nested directories (e.g. 'my_project/Technical Design Brief.pdf')
    """
    # Filter only PDF files, excluding OS metadata like __MACOSX and ._ files
    pdf_candidates = [
        f for f in file_names
        if f.lower().endswith('.pdf')
        and not os.path.basename(f).startswith('._')
        and '__MACOSX' not in f
    ]

    if not pdf_candidates:
        return None

    # Priority 1: Contains 'technical', 'design', and 'brief' / 'brif'
    # Pattern handles spaces, underscores, hyphens, dots, and trailing numbers/labels
    pat_tech_design_brief = re.compile(
        r'technical[\s_.-]*design[\s_.-]*bri[ef]{1,2}',
        re.IGNORECASE,
    )
    for f in pdf_candidates:
        base = os.path.basename(f)
        if pat_tech_design_brief.search(base):
            return f

    # Priority 2: Contains 'design' and 'brief' / 'brif'
    pat_design_brief = re.compile(
        r'design[\s_.-]*bri[ef]{1,2}',
        re.IGNORECASE,
    )
    for f in pdf_candidates:
        base = os.path.basename(f)
        if pat_design_brief.search(base):
            return f

    # Priority 3: If exactly one PDF exists in the archive, use it
    if len(pdf_candidates) == 1:
        return pdf_candidates[0]

    return None


def extract_pdf_bytes_from_file(uploaded_file):
    """
    Given a Django File or FieldFile, extract the PDF bytes of the Technical Design Brief.
    Supports:
    - .zip archives containing the project files and the PDF.
    - Direct .pdf uploads.

    Returns:
        tuple (pdf_bytes, matched_filename)
    Raises:
        BriefFileNotFoundError if no matching PDF is found.
    """
    filename = getattr(uploaded_file, 'name', '') or ''
    uploaded_file.seek(0)
    file_bytes = uploaded_file.read()

    # Direct PDF upload check
    if filename.lower().endswith('.pdf') or file_bytes.startswith(b'%PDF'):
        return file_bytes, os.path.basename(filename) or 'technical_design_brief.pdf'

    # ZIP archive extraction
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes), 'r') as zf:
            namelist = zf.namelist()
            matched_name = find_technical_design_brief_file(namelist)
            if not matched_name:
                available_pdfs = [f for f in namelist if f.lower().endswith('.pdf') and not os.path.basename(f).startswith('._')]
                pdf_list_msg = f" Found PDFs in archive: {', '.join(available_pdfs)}" if available_pdfs else " No PDF files were found in the .zip archive."
                raise BriefFileNotFoundError(
                    "Could not find a PDF named 'Technical Design Brief' or 'Design Brief' "
                    "(e.g., 'Technical Design Brief.pdf', 'technical_design_brief_1.pdf') in the uploaded archive."
                    + pdf_list_msg
                )
            pdf_bytes = zf.read(matched_name)
            return pdf_bytes, os.path.basename(matched_name)
    except zipfile.BadZipFile:
        # Check if maybe it's a PDF despite extension
        if file_bytes.startswith(b'%PDF'):
            return file_bytes, os.path.basename(filename) or 'technical_design_brief.pdf'
        raise BriefCompilationError("Uploaded file is not a valid .zip archive or .pdf document.")


def compile_pdf_to_html(pdf_bytes_or_path, title='Technical Design Brief'):
    """
    Compiles PDF bytes or a file path into responsive, high-fidelity HTML.

    Preservation guarantees:
    - Tables, charts, graphs, curves, and vector illustrations are rendered as
      vector SVG paths with zero pixelation or distortion.
    - Embedded figures and raster images are preserved inline.
    - Mathematical symbols, equations, and fonts are preserved via vector glyphs.
    - All hyperlinks are active and clickable:
        * PDF URI links (web links, mailto, etc.)
        * PDF GOTO links (page-to-page navigation like Table of Contents or citations)
        * Auto-detected plain text URLs that were not explicitly linked in the PDF.
    - Fully responsive across desktop, tablet, and mobile with modern CSS styling.
    """
    try:
        if isinstance(pdf_bytes_or_path, (bytes, bytearray)):
            doc = pymupdf.open(stream=pdf_bytes_or_path, filetype='pdf')
        else:
            doc = pymupdf.open(pdf_bytes_or_path)
    except Exception as exc:
        raise BriefCompilationError(f"Failed to parse PDF document: {exc}") from exc

    pages_html = []
    total_pages = len(doc)
    if total_pages == 0:
        doc.close()
        raise BriefCompilationError("The PDF document contains no pages.")

    url_regex = re.compile(r'https?://[^\s)\]>"\';]+')

    for page_num in range(total_pages):
        page = doc[page_num]
        w = page.rect.width
        h = page.rect.height

        # 1. Render high-fidelity vector SVG (text_as_path=1 ensures equations,
        # vector charts, and table lines render identically on every device)
        svg = page.get_svg_image(text_as_path=1)

        # Ensure responsive scaling without distorting aspect ratio
        svg = re.sub(r'width="[^"]+"', 'width="100%"', svg, count=1)
        svg = re.sub(r'height="[^"]+"', 'height="100%"', svg, count=1)
        if 'viewBox' not in svg:
            svg = svg.replace('<svg ', f'<svg viewBox="0 0 {w} {h}" ', 1)

        # 2. Extract and index active links
        links = []
        covered_rects = []
        raw_links = page.get_links()

        for l in raw_links:
            rect = l.get('from')
            if not rect:
                continue
            covered_rects.append(rect)
            uri = l.get('uri')
            kind = l.get('kind')
            page_target = l.get('page')

            if kind == pymupdf.LINK_URI and uri:
                links.append({
                    'rect': rect,
                    'href': uri,
                    'external': True,
                    'title': f'External link: {uri}',
                })
            elif kind == pymupdf.LINK_GOTO and page_target is not None:
                target_page_num = page_target + 1
                links.append({
                    'rect': rect,
                    'href': f'#pdf-page-{target_page_num}',
                    'external': False,
                    'title': f'Navigate to Page {target_page_num}',
                })

        # 3. Detect plain text URLs on the page that lack link annotations
        page_text = page.get_text()
        found_urls = set(url_regex.findall(page_text))
        for url in found_urls:
            rects = page.search_for(url)
            for r in rects:
                # Do not duplicate if it significantly intersects an existing link annotation
                if not any(r.intersects(cr) for cr in covered_rects):
                    links.append({
                        'rect': r,
                        'href': url,
                        'external': True,
                        'title': f'Link: {url}',
                    })
                    covered_rects.append(r)

        # 4. Generate clickable HTML overlay links with percentage coordinates
        links_markup = []
        for l in links:
            r = l['rect']
            left = (r.x0 / w) * 100
            top = (r.y0 / h) * 100
            lw = ((r.x1 - r.x0) / w) * 100
            lh = ((r.y1 - r.y0) / h) * 100

            target_attr = ' target="_blank" rel="noopener noreferrer"' if l['external'] else ''
            links_markup.append(
                f'<a href="{l["href"]}"{target_attr} title="{l["title"]}" class="pdf-active-link" '
                f'style="position: absolute; left: {left:.3f}%; top: {top:.3f}%; '
                f'width: {lw:.3f}%; height: {lh:.3f}%; pointer-events: auto;"></a>'
            )

        page_markup = f'''
        <div class="pdf-page-container" id="pdf-page-{page_num + 1}" data-page="{page_num + 1}"
             style="position: relative; width: 100%; max-width: {w}px; aspect-ratio: {w}/{h}; margin: 0 auto 32px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); background: #ffffff; border-radius: 6px; overflow: hidden; border: 1px solid #e1e4e8;">
            {svg}
            <div class="pdf-links-layer" style="position: absolute; inset: 0; pointer-events: none;">
                {''.join(links_markup)}
            </div>
            <div class="pdf-page-indicator" style="position: absolute; bottom: 8px; right: 12px; font-size: 11px; color: #586069; background: rgba(255,255,255,0.9); padding: 3px 8px; border-radius: 4px; pointer-events: none; border: 1px solid #e1e4e8;">
                Page {page_num + 1} of {total_pages}
            </div>
        </div>
        '''
        pages_html.append(page_markup)

    doc.close()

    compiled_html = f'''
    <div class="pdf-document-root" id="pdf-document-viewer">
        <style>
            .pdf-document-root {{
                background: #f6f8fa;
                padding: 24px 16px;
                border-radius: 8px;
                border: 1px solid #d0d7de;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            }}
            .pdf-document-header {{
                max-width: 820px;
                margin: 0 auto 20px;
                display: flex;
                flex-wrap: wrap;
                justify-content: space-between;
                align-items: center;
                gap: 8px;
                padding: 8px 12px;
                background: #ffffff;
                border: 1px solid #e1e4e8;
                border-radius: 6px;
                font-size: 13px;
                color: #24292e;
            }}
            .pdf-active-link {{
                border-radius: 2px;
                border-bottom: 2px solid rgba(9, 105, 218, 0.45);
                background: rgba(9, 105, 218, 0.04);
                transition: background 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
            }}
            .pdf-active-link:hover {{
                background: rgba(9, 105, 218, 0.18) !important;
                border-bottom-color: #0969da;
                box-shadow: 0 0 0 2px rgba(9, 105, 218, 0.25);
                cursor: pointer;
            }}
            .pdf-page-container svg {{
                display: block;
                width: 100%;
                height: 100%;
            }}
            @media (max-width: 640px) {{
                .pdf-document-root {{
                    padding: 12px 6px;
                }}
                .pdf-page-container {{
                    margin-bottom: 20px !important;
                }}
            }}
        </style>
        <div class="pdf-document-header">
            <div>
                <strong>{title}</strong>
            </div>
            <div>
                <span class="muted">{total_pages} {'page' if total_pages == 1 else 'pages'} · Responsive Vector HTML</span>
            </div>
        </div>
        <div class="pdf-pages-feed">
            {''.join(pages_html)}
        </div>
    </div>
    '''
    return compiled_html


def compile_submission_version(version):
    """
    Given a SubmissionVersion instance:
    1. Extracts the Technical Design Brief PDF.
    2. Compiles it to HTML.
    3. Saves compilation status, HTML, and timestamps on the SubmissionVersion.
    4. Records an audit log entry on the parent submission.

    Returns:
        bool: True if compilation succeeded, False otherwise.
    """
    from .models import AuditLogEntry

    if not version.file:
        version.compilation_status = version.STATUS_FAILED
        version.compilation_error = 'No uploaded file attached to this version.'
        version.save(update_fields=['compilation_status', 'compilation_error'])
        return False

    try:
        pdf_bytes, matched_name = extract_pdf_bytes_from_file(version.file)
        compiled_html = compile_pdf_to_html(
            pdf_bytes,
            title=f"{version.submission.title} — Technical Design Brief (v{version.version_number})"
        )

        version.compilation_status = version.STATUS_COMPILED
        version.brief_filename = matched_name
        version.compiled_html = compiled_html
        version.compilation_error = ''
        version.compiled_at = timezone.now()
        version.save(update_fields=[
            'compilation_status', 'brief_filename', 'compiled_html',
            'compilation_error', 'compiled_at'
        ])

        AuditLogEntry.objects.create(
            submission=version.submission,
            user=version.uploaded_by,
            action='HTML_COMPILED',
            message=f'Technical Design Brief ({matched_name}) compiled to HTML for version v{version.version_number}.',
        )
        return True

    except BriefFileNotFoundError as exc:
        version.compilation_status = version.STATUS_NOT_FOUND
        version.compilation_error = str(exc)
        version.save(update_fields=['compilation_status', 'compilation_error'])
        return False

    except Exception as exc:
        version.compilation_status = version.STATUS_FAILED
        version.compilation_error = f'Compilation failed: {exc}'
        version.save(update_fields=['compilation_status', 'compilation_error'])
        return False
