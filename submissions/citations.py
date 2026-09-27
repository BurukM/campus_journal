import re
from django.utils import timezone


def format_author_names(submission, style='apa'):
    """Format primary author and co-authors according to standard academic styles."""
    authors = [submission.primary_author] + list(submission.authors.all())

    names = []
    for a in authors:
        first = a.first_name.strip()
        last = a.last_name.strip()
        if first and last:
            initial = f"{first[0]}."
            if style == 'apa':
                names.append(f"{last}, {initial}")
            elif style == 'mla':
                names.append(f"{last}, {first}")
            elif style == 'ieee':
                names.append(f"{initial} {last}")
            elif style == 'bibtex':
                names.append(f"{last}, {first}")
        else:
            names.append(a.username)

    if style == 'apa':
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return f"{names[0]} & {names[1]}"
        return f"{', '.join(names[:-1])}, & {names[-1]}"

    if style == 'mla':
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return f"{names[0]} and {names[1]}"
        return f"{names[0]} et al."

    if style == 'ieee':
        if len(names) <= 2:
            return ' and '.join(names)
        return f"{names[0]} et al."

    if style == 'bibtex':
        return ' and '.join(names)

    return ', '.join(names)


def generate_citations(submission, request=None):
    """Generates formatted academic citations in IEEE, APA 7, MLA 9, and BibTeX styles."""
    pub_date = submission.published_at or submission.updated_at or timezone.now()
    year = pub_date.year
    month_name = pub_date.strftime("%B")
    month_abbr = pub_date.strftime("%b")

    url = ""
    if request:
        url = request.build_absolute_uri(submission.get_absolute_url())
    elif submission.slug:
        url = f"/projects/{submission.slug}/"

    title = submission.title.strip()

    # IEEE Format (Engineering Standard)
    ieee_authors = format_author_names(submission, style='ieee')
    ieee = f'{ieee_authors}, "{title}," Campus Research Journal, vol. 1, {month_abbr}. {year}. [Online]. Available: {url}'

    # APA 7th Edition
    apa_authors = format_author_names(submission, style='apa')
    apa = f"{apa_authors} ({year}). {title}. Campus Research Journal. {url}"

    # MLA 9th Edition
    mla_authors = format_author_names(submission, style='mla')
    mla = f'{mla_authors}. "{title}." Campus Research Journal, {month_abbr}. {year}, {url}.'

    # BibTeX
    bibtex_authors = format_author_names(submission, style='bibtex')
    cite_key = f"cj_{year}_{re.sub(r'[^a-zA-Z0-9]', '', submission.slug[:18])}"
    bibtex = (
        f"@article{{{cite_key},\n"
        f"  author    = {{{bibtex_authors}}},\n"
        f"  title     = {{{title}}},\n"
        f"  journal   = {{Campus Research Journal}},\n"
        f"  year      = {{{year}}},\n"
        f"  month     = {{{month_abbr.lower()}}},\n"
        f"  url       = {{{url}}}\n"
        f"}}"
    )

    return {
        'ieee': ieee,
        'apa': apa,
        'mla': mla,
        'bibtex': bibtex,
        'cite_key': cite_key,
    }
