from django.views.generic import TemplateView

from core.permissions import StaffRequiredMixin


class DashboardView(StaffRequiredMixin, TemplateView):
    template_name = "reporting/dashboard.html"
