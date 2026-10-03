from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, UserRole
from news.models import NewsArticle, NewsCategory
from submissions.models import Submission

User = get_user_model()


class NewsModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='editor1', email='editor1@test.com', password='password123'
        )
        self.category = NewsCategory.objects.create(name='Robotics & AI', slug='robotics-ai')

    def test_slug_auto_generation(self):
        article = NewsArticle.objects.create(
            title='Autonomous Rover Tested in Campus Quarry',
            category=self.category,
            author=self.user,
            content='Testing description...',
            status=NewsArticle.DRAFT
        )
        self.assertEqual(article.slug, 'autonomous-rover-tested-in-campus-quarry')

    def test_markdown_rendering_to_html(self):
        article = NewsArticle.objects.create(
            title='Markdown Test Article',
            category=self.category,
            author=self.user,
            content=(
                "## Key Findings\n\n"
                "We observed **significant** improvements.\n\n"
                "> A revolutionary breakthrough.\n\n"
                "- Item 1\n- Item 2\n"
            ),
            status=NewsArticle.DRAFT
        )
        html = article.get_content_html()
        self.assertIn('<h2>Key Findings</h2>', html)
        self.assertIn('<strong>significant</strong>', html)
        self.assertIn('<blockquote>', html)
        self.assertIn('<ul>', html)
        self.assertIn('<li>Item 1</li>', html)

    def test_reading_time_calculation(self):
        words = "word " * 450
        article = NewsArticle.objects.create(
            title='Long Read',
            category=self.category,
            author=self.user,
            content=words,
            status=NewsArticle.DRAFT
        )
        self.assertEqual(article.reading_time_minutes(), 2)


class PublicNewsAccessTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.author = User.objects.create_user(
            username='author1', email='author1@test.com', password='password123'
        )
        self.category = NewsCategory.objects.create(name='Campus Science', slug='campus-science')

        self.submission = Submission.objects.create(
            title='Deep Neural Telemetry for Low-Power Sensors',
            abstract='Sensor optimization for edge computing.',
            primary_author=self.author,
            status=Submission.PUBLISHED,
            slug='deep-neural-telemetry'
        )

        self.published_article = NewsArticle.objects.create(
            title='Sensors Team Achieves 90% Power Reduction',
            subtitle='Novel architecture powers edge nodes for months.',
            category=self.category,
            author=self.author,
            content='Full story text with **markdown**...',
            status=NewsArticle.PUBLISHED,
            published_at=timezone.now(),
            slug='sensors-team-achieves-power-reduction'
        )
        self.published_article.related_submissions.add(self.submission)

        self.draft_article = NewsArticle.objects.create(
            title='Confidential Lab Research Draft',
            category=self.category,
            author=self.author,
            content='Secret notes...',
            status=NewsArticle.DRAFT,
            slug='confidential-lab-draft'
        )

    def test_homepage_shows_news_and_published_projects_without_login(self):
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        # News block
        self.assertContains(resp, 'Latest Campus News &amp; Technology')
        self.assertContains(resp, 'Sensors Team Achieves 90% Power Reduction')
        # Published projects block
        self.assertContains(resp, 'Featured Published Research')
        self.assertContains(resp, 'Deep Neural Telemetry for Low-Power Sensors')

    def test_public_can_view_news_catalog(self):
        resp = self.client.get(reverse('news:list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Campus News &amp; Technology')
        self.assertContains(resp, 'Sensors Team Achieves 90% Power Reduction')
        self.assertNotContains(resp, 'Confidential Lab Research Draft')

    def test_public_can_view_published_article_detail(self):
        resp = self.client.get(reverse('news:detail', kwargs={'slug': self.published_article.slug}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Sensors Team Achieves 90% Power Reduction')
        self.assertContains(resp, 'Deep Neural Telemetry for Low-Power Sensors')
        self.assertContains(resp, '<strong>markdown</strong>')

    def test_public_cannot_view_draft_article(self):
        resp = self.client.get(reverse('news:detail', kwargs={'slug': self.draft_article.slug}))
        self.assertEqual(resp.status_code, 403)


class StaffEditorialDeskTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.student = User.objects.create_user(
            username='student_user', email='student@test.com', password='password123'
        )
        self.editor = User.objects.create_user(
            username='news_editor_user', email='editor@test.com', password='password123'
        )

        role_editor, _ = Role.objects.get_or_create(slug=Role.NEWS_EDITOR, defaults={'name': 'News Editor'})
        UserRole.objects.create(user=self.editor, role=role_editor)

        self.category = NewsCategory.objects.create(name='Innovation', slug='innovation')

    def test_student_cannot_access_editorial_desk(self):
        self.client.login(username='student_user', password='password123')
        resp = self.client.get(reverse('news:desk'))
        self.assertEqual(resp.status_code, 403)

        create_resp = self.client.get(reverse('news:create'))
        self.assertEqual(create_resp.status_code, 403)

    def test_news_editor_can_access_editorial_desk_and_compose(self):
        self.client.login(username='news_editor_user', password='password123')
        resp = self.client.get(reverse('news:desk'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Editorial News Desk')

        # Create article
        post_data = {
            'title': 'New Robotics Initiative Launched',
            'subtitle': 'Campus introduces interdisciplinary lab.',
            'category': self.category.pk,
            'content': '## Overview\n\nFull program description.',
            'status': NewsArticle.PUBLISHED,
        }
        create_resp = self.client.post(reverse('news:create'), post_data, follow=True)
        self.assertEqual(create_resp.status_code, 200)
        self.assertContains(create_resp, 'New Robotics Initiative Launched')

        article = NewsArticle.objects.get(title='New Robotics Initiative Launched')
        self.assertEqual(article.status, NewsArticle.PUBLISHED)
        self.assertIsNotNone(article.published_at)

    def test_news_editor_can_toggle_publish(self):
        self.client.login(username='news_editor_user', password='password123')
        article = NewsArticle.objects.create(
            title='Toggle Test Story',
            category=self.category,
            author=self.editor,
            content='Content here.',
            status=NewsArticle.PUBLISHED,
            slug='toggle-test-story'
        )

        # Toggle to unpublish
        toggle_url = reverse('news:toggle_publish', kwargs={'slug': article.slug})
        resp = self.client.post(toggle_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        article.refresh_from_db()
        self.assertEqual(article.status, NewsArticle.ARCHIVED)

    def test_create_news_draft_without_categories_succeeds_without_500(self):
        """When no categories exist in database (production-like empty state), creating a draft works and does not return 500."""
        self.client.login(username='news_editor_user', password='password123')
        # Wipe all categories in DB
        NewsCategory.objects.all().delete()
        self.assertEqual(NewsCategory.objects.count(), 0)

        post_data = {
            'title': 'Autonomous Glider Breakthrough',
            'subtitle': 'Tested in wind tunnel.',
            'category': '',
            'content': 'Draft story content.',
            'status': NewsArticle.DRAFT,
        }
        resp = self.client.post(reverse('news:create'), post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Autonomous Glider Breakthrough')
        article = NewsArticle.objects.get(title='Autonomous Glider Breakthrough')
        self.assertIsNotNone(article.category)
        self.assertEqual(article.category.slug, 'general')

    def test_create_news_draft_with_each_new_category(self):
        """Creating a news draft with each of the three new categories (Club Announcement, New Project, General) works."""
        self.client.login(username='news_editor_user', password='password123')

        new_categories = [
            ('Club Announcement', 'club-announcement'),
            ('New Project', 'new-project'),
            ('General', 'general'),
        ]

        for name, slug in new_categories:
            cat, _ = NewsCategory.objects.get_or_create(slug=slug, defaults={'name': name})
            title = f'Headline for {name}'
            post_data = {
                'title': title,
                'subtitle': f'Subtitle for {name}',
                'category': cat.pk,
                'content': f'Content for {name}',
                'status': NewsArticle.DRAFT,
            }
            resp = self.client.post(reverse('news:create'), post_data, follow=True)
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, title)
            art = NewsArticle.objects.get(title=title)
            self.assertEqual(art.category, cat)

    def test_featured_researches_lists_published_and_excludes_unpublished(self):
        """Featured researches field only lists published submissions and excludes drafts and non-published submissions."""
        self.client.login(username='news_editor_user', password='password123')

        pub1 = Submission.objects.create(
            title='Published Paper Alpha',
            abstract='Abstract alpha',
            primary_author=self.student,
            status=Submission.PUBLISHED,
            slug='published-paper-alpha',
            published_at=timezone.now(),
        )
        draft_sub = Submission.objects.create(
            title='Draft Paper Beta',
            abstract='Abstract beta',
            primary_author=self.student,
            status=Submission.DRAFT,
            slug='draft-paper-beta',
        )
        review_sub = Submission.objects.create(
            title='Review Paper Gamma',
            abstract='Abstract gamma',
            primary_author=self.student,
            status=Submission.UNDER_REVIEW,
            slug='review-paper-gamma',
        )

        resp = self.client.get(reverse('news:create'))
        self.assertEqual(resp.status_code, 200)
        # Should contain published paper with author label
        self.assertContains(resp, 'Published Paper Alpha')
        self.assertContains(resp, self.student.username)
        # Should not contain unpublished papers in choices
        self.assertNotContains(resp, 'Draft Paper Beta')
        self.assertNotContains(resp, 'Review Paper Gamma')

    def test_featured_researches_empty_state_and_persistence_on_edit(self):
        """Field works when no published submissions exist, and selected items persist on edit."""
        self.client.login(username='news_editor_user', password='password123')

        # 1. Empty state
        Submission.objects.filter(status=Submission.PUBLISHED).delete()
        resp = self.client.get(reverse('news:create'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No published research yet.')

        # Create draft with empty related_submissions
        cat, _ = NewsCategory.objects.get_or_create(slug='general', defaults={'name': 'General'})
        post_data = {
            'title': 'Empty Research Draft Story',
            'content': 'Story content without research.',
            'category': cat.pk,
            'status': NewsArticle.DRAFT,
            'related_submissions': [],
        }
        create_resp = self.client.post(reverse('news:create'), post_data, follow=True)
        self.assertEqual(create_resp.status_code, 200)
        article = NewsArticle.objects.get(title='Empty Research Draft Story')
        self.assertEqual(article.related_submissions.count(), 0)

        # 2. Add published submissions and edit article to link them
        sub1 = Submission.objects.create(
            title='Smart Prosthetics Design',
            abstract='Prosthetics paper.',
            primary_author=self.student,
            status=Submission.PUBLISHED,
            slug='smart-prosthetics-design',
            published_at=timezone.now(),
        )
        sub2 = Submission.objects.create(
            title='Bionic Sensor Network',
            abstract='Sensors paper.',
            primary_author=self.student,
            status=Submission.PUBLISHED,
            slug='bionic-sensor-network',
            published_at=timezone.now(),
        )

        # GET edit page should show them in options
        edit_url = reverse('news:edit', kwargs={'slug': article.slug})
        edit_get_resp = self.client.get(edit_url)
        self.assertEqual(edit_get_resp.status_code, 200)
        self.assertContains(edit_get_resp, 'Smart Prosthetics Design')
        self.assertContains(edit_get_resp, 'Bionic Sensor Network')

        # POST edit page to link sub1 and sub2
        edit_post_data = {
            'title': 'Empty Research Draft Story',
            'content': 'Updated story content with research.',
            'category': cat.pk,
            'status': NewsArticle.DRAFT,
            'related_submissions': [sub1.pk, sub2.pk],
        }
        edit_post_resp = self.client.post(edit_url, edit_post_data, follow=True)
        self.assertEqual(edit_post_resp.status_code, 200)

        article.refresh_from_db()
        self.assertEqual(article.related_submissions.count(), 2)
        self.assertIn(sub1, article.related_submissions.all())
        self.assertIn(sub2, article.related_submissions.all())

        # GET edit page again should have sub1 and sub2 selected
        edit_get_again = self.client.get(edit_url)
        self.assertEqual(edit_get_again.status_code, 200)
        self.assertContains(edit_get_again, f'value="{sub1.pk}" selected')
        self.assertContains(edit_get_again, f'value="{sub2.pk}" selected')

    def test_featured_image_upload_read_only_filesystem_does_not_return_500(self):
        """When the filesystem is read-only (like Vercel), uploading an image does not return 500."""
        from unittest.mock import patch
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.login(username='news_editor_user', password='password123')

        gif = (
            b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00'
            b'\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00'
            b'\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'
        )
        img = SimpleUploadedFile('cover.gif', gif, content_type='image/gif')

        cat, _ = NewsCategory.objects.get_or_create(slug='general', defaults={'name': 'General'})
        post_data = {
            'title': 'Read Only Storage Test Article',
            'content': 'Story content.',
            'category': cat.pk,
            'status': NewsArticle.DRAFT,
            'featured_image': img,
        }

        with patch('django.core.files.storage.FileSystemStorage._save', side_effect=OSError(30, 'Read-only file system: \'/var/task/media\'')):
            resp = self.client.post(reverse('news:create'), post_data, follow=True)
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, 'Read Only Storage Test Article')
            art = NewsArticle.objects.get(title='Read Only Storage Test Article')
            self.assertIsNotNone(art)


class SupabaseMediaStorageTests(TestCase):
    def test_supabase_media_storage_operations(self):
        from unittest.mock import MagicMock, patch
        from django.core.files.base import ContentFile
        from campus_journal.storage import SupabaseMediaStorage

        mock_client = MagicMock()
        mock_bucket_proxy = MagicMock()
        mock_client.storage.from_.return_value = mock_bucket_proxy
        mock_bucket_proxy.upload.return_value = {'Key': 'news/test.jpg'}
        mock_bucket_proxy.create_signed_url.return_value = {'signedURL': 'https://supabase.co/signed/news/test.jpg'}
        mock_bucket_proxy.exists.return_value = True
        mock_bucket_proxy.download.return_value = b'test-bytes'

        storage = SupabaseMediaStorage()

        with patch('campus_journal.storage.is_supabase_configured', return_value=True), \
             patch('campus_journal.storage.get_supabase_client', return_value=mock_client):

            # Test _save
            file_content = ContentFile(b'image-content', name='cover.jpg')
            saved_name = storage._save('news/featured/cover.jpg', file_content)
            self.assertEqual(saved_name, 'news/featured/cover.jpg')
            mock_bucket_proxy.upload.assert_called_once()

            # Test url
            url = storage.url('news/featured/cover.jpg')
            self.assertEqual(url, 'https://supabase.co/signed/news/test.jpg')

            # Test exists
            exists = storage.exists('news/featured/cover.jpg')
            self.assertTrue(exists)

            # Test delete
            storage.delete('news/featured/cover.jpg')
            mock_bucket_proxy.remove.assert_called_with(['news/featured/cover.jpg'])

            # Test _open
            opened = storage._open('news/featured/cover.jpg')
            self.assertEqual(opened.read(), b'test-bytes')


