from django.template.loader import render_to_string

# The roster gets posted on a wall, so it has to be one sheet. WeasyPrint has
# no shrink-to-fit, so render at the largest body size that still paginates to
# a single page. 5pt is the floor: below that nobody reads it from a corridor,
# and a second page becomes the lesser evil.
FONT_SIZES_PT = (10, 9, 8, 7, 6.5, 6, 5.5, 5)


def render_week_dashboard_pdf(dashboard):
    """Render the week dashboard dict (from services.build_week_dashboard)
    to PDF bytes, on a single page whenever the content allows it.

    weasyprint is imported lazily: it needs system libraries (pango) and
    the rest of the API must keep working without them. On macOS run the
    server with DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib (see README).
    """
    from weasyprint import HTML

    context = {**dashboard, 'groups': _rows(dashboard['groups'])}
    document = None
    for font_pt in FONT_SIZES_PT:
        html = render_to_string(
            'core/week_dashboard_pdf.html',
            {**context, 'font_pt': font_pt},
        )
        document = HTML(string=html).render()
        if len(document.pages) == 1:
            break
    return document.write_pdf()


def _rows(groups):
    """Print-oriented view of the dashboard groups.

    Only the groups on duty are printed -- a resting group has nothing to read
    on a duty roster, and dropping them buys the rest a bigger font.

    A group almost always sits in a single class, so repeating "(3eme A)"
    after every name costs a line per row and buys nothing. Hoist the classes
    into their own column and leave the names bare.
    """
    rows = []
    for group in groups:
        if not group['task']:
            continue
        classes = list(dict.fromkeys(
            student['school_class'] for student in group['students']
        ))
        rows.append({
            **group,
            'classes': ', '.join(classes),
            'names': [
                f"{student['last_name']} {student['first_name']}"
                for student in group['students']
            ],
        })
    return rows
