import io
import zipfile
import pymupdf
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from PIL import Image, ImageDraw

from accounts.models import Role, UserRole
from submissions.citations import generate_citations
from submissions.compiler import (
    BriefFileNotFoundError,
    compile_pdf_to_html,
    find_technical_design_brief_file,
)
from submissions.models import AuditLogEntry, Submission, SubmissionVersion

User = get_user_model()


def _create_sample_brief_pdf():
    """Generates an in-memory PDF with images, vector table, vector graph, and active links."""
    doc = pymupdf.open()
    page1 = doc.new_page(width=612, height=792)
    page2 = doc.new_page(width=612, height=792)

    # 1. Text & Heading
    p1 = doc[0]
    p1.insert_text((54, 54), 'Solar Tracker Technical Design Brief', fontsize=18)

    # 2. Embedded Raster Image
    img = Image.new('RGB', (160, 80), color=(50, 120, 180))
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), 'Circuit Diagram', fill=(255, 255, 255))
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    p1.insert_image(pymupdf.Rect(54, 80, 214, 160), stream=img_bytes.getvalue())

    # 3. Table with vector gridlines and data
    p1.draw_rect(pymupdf.Rect(54, 180, 500, 260), color=(0.2, 0.2, 0.2), fill=(0.96, 0.96, 0.96))
    p1.draw_line(pymupdf.Point(54, 210), pymupdf.Point(500, 210), color=(0.2, 0.2, 0.2), width=1.5)
    p1.insert_text((64, 200), 'Specification Parameter', fontsize=11)
    p1.insert_text((260, 200), 'Design Value', fontsize=11)
    p1.insert_text((64, 235), 'Operating Voltage', fontsize=10)
    p1.insert_text((260, 235), '12.0 VDC ± 0.5V', fontsize=10)

    # 4. Vector Graph (axes + curve)
    p1.draw_line(pymupdf.Point(54, 380), pymupdf.Point(320, 380), color=(0, 0, 0), width=1.5)
    p1.draw_line(pymupdf.Point(54, 380), pymupdf.Point(54, 290), color=(0, 0, 0), width=1.5)
    pts = [pymupdf.Point(54 + i * 26, 380 - (i ** 1.3) * 8) for i in range(10)]
    for i in range(len(pts) - 1):
        p1.draw_line(pts[i], pts[i + 1], color=(0.85, 0.15, 0.15), width=2)
    p1.insert_text((54, 400), 'Figure 1: Power Output over Incident Angle', fontsize=10)

    # 5. Active Clickable Links
    # Hyperlink annotation
    link_rect = pymupdf.Rect(54, 430, 280, 450)
    p1.insert_text((54, 444), 'External Project Source Code', fontsize=11, color=(0, 0, 0.8))
    p1.insert_link({'kind': pymupdf.LINK_URI, 'from': link_rect, 'uri': 'https://github.com/campus-journal/solar'})

    # Internal page anchor (points to page 2)
    goto_rect = pymupdf.Rect(54, 465, 260, 485)
    p1.insert_text((54, 480), 'See Appendix (Page 2)', fontsize=11, color=(0.1, 0.5, 0.1))
    p1.insert_link({'kind': pymupdf.LINK_GOTO, 'from': goto_rect, 'page': 1})

    # Plain text URL in text
    p1.insert_text((54, 510), 'Official documentation: https://solar-tracker.example.edu/docs', fontsize=10)

    # Page 2 content
    p2 = doc[1]
    p2.insert_text((54, 54), 'Appendix & Reference Data', fontsize=16)

    data = doc.tobytes()
    doc.close()
    return data


def _create_sample_zip(pdf_filename='Technical Design Brief 1.pdf', pdf_bytes=None):
    """Creates an in-memory zip file containing the specified PDF and supplementary files."""
    if pdf_bytes is None:
        pdf_bytes = _create_sample_brief_pdf()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr(f'project/{pdf_filename}', pdf_bytes)
        zf.writestr('project/readme.txt', 'Source files and simulation code.')
        zf.writestr('project/data.csv', 'time,voltage\n1,12.1\n2,12.2\n')
    buf.seek(0)
    return buf.getvalue()


class BriefDetectionTests(TestCase):
    def test_finds_exact_name(self):
        names = ['src/main.py', 'docs/Technical Design Brief.pdf', 'README.md']
        self.assertEqual(find_technical_design_brief_file(names), 'docs/Technical Design Brief.pdf')

    def test_finds_numbers_after_name(self):
        names = ['code.py', 'technical_design_brief_1.pdf']
        self.assertEqual(find_technical_design_brief_file(names), 'technical_design_brief_1.pdf')

        names2 = ['Technical Design Brief 2.pdf', 'other.txt']
        self.assertEqual(find_technical_design_brief_file(names2), 'Technical Design Brief 2.pdf')

        names3 = ['sub/technical-design-brief-v3.pdf']
        self.assertEqual(find_technical_design_brief_file(names3), 'sub/technical-design-brief-v3.pdf')

    def test_finds_slight_spelling_variation(self):
        names = ['archive/technical design brif 1.pdf', 'data.csv']
        self.assertEqual(find_technical_design_brief_file(names), 'archive/technical design brif 1.pdf')

    def test_finds_design_brief_variations(self):
        names = ['data.csv', 'Design Brief.pdf']
        self.assertEqual(find_technical_design_brief_file(names), 'Design Brief.pdf')

        names2 = ['design_brief_1.pdf', 'extra.txt']
        self.assertEqual(find_technical_design_brief_file(names2), 'design_brief_1.pdf')

    def test_single_pdf_fallback(self):
        names = ['source.c', 'Solar_Tracker_Paper.pdf']
        self.assertEqual(find_technical_design_brief_file(names), 'Solar_Tracker_Paper.pdf')

    def test_returns_none_when_no_brief_found(self):
        names = ['data.csv', 'notes.txt', 'report.docx']
        self.assertIsNone(find_technical_design_brief_file(names))


class PdfCompilerTests(TestCase):
    def setUp(self):
        self.pdf_bytes = _create_sample_brief_pdf()

    def test_compile_preserves_vector_drawings_and_creates_html(self):
        html = compile_pdf_to_html(self.pdf_bytes, title='Solar Tracker')
        self.assertIn('Solar Tracker', html)
        self.assertIn('pdf-document-viewer', html)
        self.assertIn('<svg', html)
        self.assertIn('viewBox', html)
        # Check that page 1 and page 2 containers exist
        self.assertIn('id="pdf-page-1"', html)
        self.assertIn('id="pdf-page-2"', html)

    def test_compile_preserves_and_activates_links(self):
        html = compile_pdf_to_html(self.pdf_bytes)
        # 1. External link
        self.assertIn('href="https://github.com/campus-journal/solar"', html)
        self.assertIn('class="pdf-active-link"', html)
        self.assertIn('target="_blank"', html)

        # 2. Internal page navigation link
        self.assertIn('href="#pdf-page-2"', html)

        # 3. Plain text URL detected and turned into active link
        self.assertIn('href="https://solar-tracker.example.edu/docs"', html)


class SubmissionWorkflowIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='student1', email='student1@example.com', password='password123'
        )
        self.manager = User.objects.create_user(
            username='manager1', email='manager1@example.com', password='password123'
        )

        # Seed roles
        role_mgr, _ = Role.objects.get_or_create(slug=Role.JOURNAL_MANAGER, defaults={'name': 'Journal Manager'})
        UserRole.objects.create(user=self.manager, role=role_mgr)

        self.client = Client()
        self.client.login(username='student1', password='password123')

        self.submission = Submission.objects.create(
            title='Autonomous Solar Tracking Platform',
            abstract='A robust dual-axis solar tracking system for decentralized power.',
            keywords='solar, energy, tracker',
            primary_author=self.user,
            status=Submission.DRAFT,
        )

    def test_upload_version_compiles_technical_design_brief_automatically(self):
        zip_content = _create_sample_zip('Technical Design Brief 1.pdf')
        uploaded = SimpleUploadedFile(
            'solar_project.zip',
            zip_content,
            content_type='application/zip'
        )

        url = reverse('submissions:upload_version', kwargs={'pk': self.submission.pk})
        response = self.client.post(url, {'file': uploaded, 'notes': 'Initial files.'}, follow=True)
        self.assertEqual(response.status_code, 200)

        version = self.submission.latest_version()
        self.assertIsNotNone(version)
        self.assertEqual(version.compilation_status, SubmissionVersion.STATUS_COMPILED)
        self.assertEqual(version.brief_filename, 'Technical Design Brief 1.pdf')
        self.assertTrue(len(version.compiled_html) > 0)
        self.assertIn('class="pdf-active-link"', version.compiled_html)

        # Verify Audit Log
        audit_entry = self.submission.audit_log.filter(action='HTML_COMPILED').first()
        self.assertIsNotNone(audit_entry)
        self.assertIn('Technical Design Brief 1.pdf', audit_entry.message)

        # Verify preview on submission detail page
        detail_url = reverse('submissions:detail', kwargs={'pk': self.submission.pk})
        detail_resp = self.client.get(detail_url)
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, 'Compiled Technical Design Brief Preview')
        self.assertContains(detail_resp, 'HTML Compiled: Technical Design Brief 1.pdf')

    def test_upload_without_brief_sets_not_found_status(self):
        # Create a zip containing only unrelated files
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('code.py', 'print("hello")')
            zf.writestr('other_doc.docx', 'word doc')
        buf.seek(0)

        uploaded = SimpleUploadedFile(
            'no_brief.zip',
            buf.getvalue(),
            content_type='application/zip'
        )

        url = reverse('submissions:upload_version', kwargs={'pk': self.submission.pk})
        response = self.client.post(url, {'file': uploaded}, follow=True)
        self.assertEqual(response.status_code, 200)

        version = self.submission.latest_version()
        self.assertEqual(version.compilation_status, SubmissionVersion.STATUS_NOT_FOUND)
        self.assertIn('Could not find a PDF', version.compilation_error)

    def test_recompile_endpoint(self):
        zip_content = _create_sample_zip('technical_design_brief_2.pdf')
        uploaded = SimpleUploadedFile(
            'solar_project.zip',
            zip_content,
            content_type='application/zip'
        )
        self.client.post(
            reverse('submissions:upload_version', kwargs={'pk': self.submission.pk}),
            {'file': uploaded},
            follow=True
        )

        recompile_url = reverse('submissions:recompile', kwargs={'pk': self.submission.pk})
        resp = self.client.post(recompile_url, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'recompiled to responsive HTML successfully')

    def test_published_project_shows_compiled_html_publicly(self):
        zip_content = _create_sample_zip('Technical Design Brief.pdf')
        uploaded = SimpleUploadedFile(
            'project.zip',
            zip_content,
            content_type='application/zip'
        )
        self.client.post(
            reverse('submissions:upload_version', kwargs={'pk': self.submission.pk}),
            {'file': uploaded},
            follow=True
        )

        # Move submission to PUBLISHED
        self.submission.status = Submission.PUBLISHED
        self.submission.slug = 'autonomous-solar-tracking-platform'
        self.submission.save()

        # Public access without login
        anon_client = Client()
        project_url = reverse('projects:detail', kwargs={'slug': self.submission.slug})
        resp = anon_client.get(project_url)
        self.assertContains(resp, 'btn-see-more')
        self.assertContains(resp, 'See more')
        self.assertContains(resp, 'brief-expandable-section')
        self.assertContains(resp, 'Show less')
        self.assertContains(resp, 'Similar Articles')

    def test_similar_articles_displayed_in_sidebar(self):
        dept = self.submission.department
        # Create a second published article
        other_user = User.objects.create_user(
            username='author2', email='author2@example.com', password='password123'
        )
        sim_sub = Submission.objects.create(
            title='Solar Thermal Converter Unit',
            abstract='Advanced parabolic solar collection for thermal conversion.',
            keywords='solar, thermal, energy',
            department=dept,
            primary_author=other_user,
            status=Submission.PUBLISHED,
            slug='solar-thermal-converter-unit'
        )

        anon_client = Client()
        self.submission.status = Submission.PUBLISHED
        self.submission.slug = 'autonomous-solar-tracking-platform'
        self.submission.save()

        project_url = reverse('projects:detail', kwargs={'slug': self.submission.slug})
        resp = anon_client.get(project_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Similar Articles')
        self.assertContains(resp, 'Solar Thermal Converter Unit')
        self.assertContains(resp, sim_sub.slug)

    def test_citations_generation_and_bibtex_download(self):
        self.submission.status = Submission.PUBLISHED
        self.submission.slug = 'autonomous-solar-tracking-platform'
        self.submission.save()

        citations = generate_citations(self.submission)
        self.assertIn('Autonomous Solar Tracking Platform', citations['ieee'])
        self.assertIn('Autonomous Solar Tracking Platform', citations['apa'])
        self.assertIn('Autonomous Solar Tracking Platform', citations['mla'])
        self.assertIn('@article{', citations['bibtex'])

        # Test public detail page includes citation context
        anon_client = Client()
        detail_url = reverse('projects:detail', kwargs={'slug': self.submission.slug})
        resp = anon_client.get(detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('citations', resp.context)

        # Test download .bib endpoint
        bib_url = reverse('projects:bibtex', kwargs={'slug': self.submission.slug})
        bib_resp = anon_client.get(bib_url)
        self.assertEqual(bib_resp.status_code, 200)
        self.assertEqual(bib_resp['Content-Type'], 'application/x-bibtex; charset=utf-8')
        self.assertIn('attachment', bib_resp['Content-Disposition'])
        self.assertIn('@article{', bib_resp.content.decode('utf-8'))

    def test_unified_search(self):
        self.submission.status = Submission.PUBLISHED
        self.submission.slug = 'autonomous-solar-tracking-platform'
        self.submission.save()

        anon_client = Client()
        # Search query matching submission title
        resp = anon_client.get(reverse('search') + '?q=solar')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['projects']), 1)
        self.assertEqual(resp.context['projects'][0].pk, self.submission.pk)

        # Search query matching nothing
        empty_resp = anon_client.get(reverse('search') + '?q=nonexistenttermxyz')
        self.assertEqual(empty_resp.status_code, 200)
        self.assertEqual(len(empty_resp.context['projects']), 0)
