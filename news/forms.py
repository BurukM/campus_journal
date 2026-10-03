from django import forms
from submissions.models import Submission
from .models import NewsArticle, NewsCategory


class FeaturedResearchChoiceField(forms.ModelMultipleChoiceField):
    """Human-readable choice field showing research title and primary author."""

    def label_from_instance(self, obj):
        author_name = obj.primary_author.get_full_name() or obj.primary_author.username
        return f"{obj.title} — {author_name}"


class NewsArticleForm(forms.ModelForm):
    """Editorial form for creating and editing news articles."""

    category = forms.ModelChoiceField(
        queryset=NewsCategory.objects.all().order_by('name'),
        required=False,
        empty_label="Select a category",
    )
    related_submissions = FeaturedResearchChoiceField(
        queryset=Submission.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={'size': '5'}),
        help_text="Select published research projects discussed in or related to this article (hold Ctrl / Cmd to select multiple).",
    )

    class Meta:
        model = NewsArticle
        fields = [
            'title',
            'subtitle',
            'category',
            'featured_image',
            'featured_image_caption',
            'content',
            'related_submissions',
            'status',
        ]
        widgets = {
            'subtitle': forms.Textarea(attrs={'rows': 2, 'placeholder': 'A brief summary or deck describing the story.'}),
            'content': forms.Textarea(attrs={
                'rows': 16,
                'placeholder': 'Write your story in standard Markdown or HTML...\n\n## Subheading\nParagraph text...\n\n> Quote or callout...\n\n- Bullet point 1\n- Bullet point 2'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Dynamic query for published submissions with select_related to eliminate N+1 queries
        published_submissions = (
            Submission.objects.filter(status=Submission.PUBLISHED)
            .select_related('primary_author')
            .order_by('-published_at', '-created_at')
        )
        self.fields['related_submissions'].queryset = published_submissions
        if not published_submissions.exists():
            self.fields['related_submissions'].help_text = "No published research yet."

        # Ensure category queryset is ordered sensibly with the new categories easy to find
        self.fields['category'].queryset = NewsCategory.objects.all().order_by('name')

    def clean_category(self):
        category = self.cleaned_data.get('category')
        if not category:
            category, _ = NewsCategory.objects.get_or_create(
                slug='general',
                defaults={
                    'name': 'General',
                    'description': 'General campus news, announcements, and university updates.'
                }
            )
        return category
