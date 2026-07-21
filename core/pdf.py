from django.template.loader import render_to_string


def render_week_dashboard_pdf(dashboard):
    """Render the week dashboard dict (from services.build_week_dashboard)
    to PDF bytes.

    weasyprint is imported lazily: it needs system libraries (pango) and
    the rest of the API must keep working without them. On macOS run the
    server with DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib (see README).
    """
    from weasyprint import HTML

    html = render_to_string('core/week_dashboard_pdf.html', dashboard)
    return HTML(string=html).write_pdf()
