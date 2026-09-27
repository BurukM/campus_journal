from django import forms
from submissions.models import Submission
from .models import NewsArticle, NewsCategory


class NewsArticleForm(forms.ModelForm):
    """Editorial form for creating and editing news articles."""

    related_submissions = forms.ModelMultipleChoiceField(
        queryset=Submission.objects.filter(status=Submission.PUBLISHED).order_by('-published_at'),
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
