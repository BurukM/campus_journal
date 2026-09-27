# Campus Journal — Full Academic Platform (Phases 1 through 6)

Users, roles/permissions, profiles, the research submission workflow,
and now the full reviewer-assignment and decision loop (screening →
assign → review → accept / revise / reject → resubmit). Built with
Django + PostgreSQL (runs on SQLite locally with zero setup).

## What's here

**Phase 1 — accounts**
- Custom `User` model (`accounts.User`)
- `Role` model + `UserRole` (records who granted a role and when) —
  student, reviewer, journal_manager, news_editor, administrator,
  club_advisor, super_admin
- `Profile` (public academic identity) and `Department`
- Signup / login / logout, a role-aware dashboard, public profile pages
- Django admin as the role-management console

**Phase 2 — submissions**
- `Submission` with a controlled state machine (the full 13-state enum
  from the plan is defined in `submissions/models.py`)
- `SubmissionVersion` — every file upload is a new version, never an
  overwrite
- `SubmissionAuthor` — ordered co-authorship
- `AuditLogEntry` — every status change and upload is recorded
- Student flow: create a draft, upload a `.zip`, submit for review, withdraw
- Journal Manager flow: a submission queue, move `SUBMITTED → SCREENING`

**Phase 3 — review**
- `Review` — one row per review round, doubling as the assignment
  record and the eventual decision (accept / revision required / reject)
- Journal Manager: assigns a reviewer (`SCREENING → ASSIGNED`) from a
  dropdown of users holding the Reviewer role
- Reviewer: begins the review (`ASSIGNED → UNDER_REVIEW`), then submits
  a decision with comments, which moves the submission to `ACCEPTED`,
  `REVISION_REQUIRED`, or `REJECTED`
- Student: after a revision request, must upload a new version before
  "Resubmit" becomes available (`REVISION_REQUIRED → RESUBMITTED`) —
  enforced by comparing the latest version's upload time against the
  review's decision time, not just its existence
- Reviewer resumes the same submission (`RESUBMITTED → UNDER_REVIEW`)
  and can go through another round
- All transition rules (who can move what, from where, to where) live
  in one place: `submissions/transitions.py`
- Every submission's "History" section shows the complete chain of
  status changes with who did what and when
**Phase 4 — publishing & compilation**
- Production & publishing pipeline: `ACCEPTED → IN_PRODUCTION → READY_TO_PUBLISH → PUBLISHED`
- Public project catalog: browse published papers at `/projects/` and read full articles at `/projects/<slug>/`
- Automated PDF → HTML compilation:
  - Scans uploaded archives to locate a PDF named **Technical Design Brief** (supports variations, numbers, hyphens/underscores, e.g. `Technical Design Brief 1.pdf`, `design_brief.pdf`).
  - Converts PDF into high-fidelity responsive HTML with zero distortion of figures, vector graphs, curves, and tables.
  - Preserves and activates all links: explicit PDF hyperlinks, internal page anchors (e.g. Table of Contents / citations), and plain-text URLs.
  - Interactive preview on the submission detail page and published presentation on the public project page.
**Phase 5 — campus news & editorial desk**
- Public news catalog (`/news/`) and reading view (`/news/<slug>/`)
- Category classification (`NewsCategory`) and full standard Markdown/HTML formatting
- Staff-only news drafting and management (`Role.NEWS_EDITOR`, `Role.ADMINISTRATOR`)
- Editorial desk (`/news/desk/`) with status metrics (Drafts, In Review, Published, Archived)
- Cross-linking: News articles can link directly to published campus research papers
- Public homepage (`/`): displays both the Latest News block and Featured Research block with zero login required

**Phase 6 — search, citations, notifications, & UI refresh**
- **Unified Global Search (`/search/`):**
  - Search across peer-reviewed published papers and campus news articles.
  - Multi-faceted filtering by type (`all`, `projects`, `news`), academic departments, and news categories.
  - Publicly accessible with zero login requirements.
- **Academic Citations Engine (`/projects/<slug>/`):**
  - Multi-format citations: IEEE, APA 7th, MLA 9th, and BibTeX.
  - Interactive citation switcher with 1-click clipboard copy and visual feedback.
  - Direct `.bib` citation download endpoint (`/projects/<slug>/cite.bib`).
- **In-App Notification Alerts (`/notifications/`):**
  - Live alerts on workflow events: reviewer assignments, review decisions, author resubmissions, and publications.
  - Global navigation bell with real-time unread count badge.
  - Mark individual notifications as read or batch mark all as read.
- **Lively Public UI Refresh:**
  - Modern typography (`Plus Jakarta Sans`), sleek navigation bar with search and notification shortcuts, and clean footer.
  - Lively Research Catalog (`/projects/`): hero banner, department filter pills, prominent cards with author avatars and publication metadata.
  - Interactive Research Reader (`/projects/<slug>/`): two-column layout, abstract card, citation box, similar articles suggestions, and smooth expandable Technical Design Brief viewer with top and bottom "Show less" controls.
  - Vibrant Campus Newsroom (`/news/` and `/news/<slug>/`): lead featured story, responsive cards with hover effects, reading time chips, and cross-linked research.
  - Preserved clean portal-like styling for editorial workflows (drafts, queues, and reviews).

## Run it locally

```bash
python3 -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env   # Windows: copy .env.example .env

python manage.py migrate
python manage.py seed_roles          # creates the standard role set
python manage.py seed_news_data      # creates news categories and sample story
python manage.py createsuperuser

python manage.py runserver
```

Visit:
- `http://127.0.0.1:8000/` — public home with latest news and featured research
- `http://127.0.0.1:8000/projects/` — public published projects directory
- `http://127.0.0.1:8000/news/` — public campus news catalog
- `http://127.0.0.1:8000/search/` — unified search across papers and news
- `http://127.0.0.1:8000/notifications/` — in-app notifications center
- `http://127.0.0.1:8000/accounts/access-requests/` — in-app role approval queue (Journal Managers & Administrators)
- `http://127.0.0.1:8000/news/desk/` — staff editorial news desk
- `http://127.0.0.1:8000/admin/` — Django admin console

## Switching to PostgreSQL

```bash
docker compose up -d          # starts Postgres on localhost:5432
# in .env:
DATABASE_URL=postgres://campus_journal:campus_journal@localhost:5432/campus_journal
python manage.py migrate
```

## Role Assignment & In-App Access Approval

- **Student / Author Accounts:** Instant access upon registration. Self-service and immediately active (`Role.STUDENT`).
- **Reviewer, Editorial Staff, & Administrator Accounts:**
  - Registrants choose their intended role on the signup page, select their academic department, and supply an affiliation/justification note.
  - Accounts are set to inactive (`is_active=False`) pending review.
  - Active administrators receive an in-app notification alert.
  - Administrators review applications at `/accounts/access-requests/` (also accessible from the Dashboard) and can approve or decline with 1-click.
  - Approving automatically activates the user account, assigns the requested role, and notifies the applicant.
  - If a pending applicant attempts to log in before approval, a helpful status message informs them their application is under review.


