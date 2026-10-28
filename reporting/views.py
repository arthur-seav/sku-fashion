import csv

from django import forms
from django.http import HttpResponse
from django.views.generic import TemplateView

from core.forms import BootstrapFormMixin, DateInput
from core.permissions import StaffRequiredMixin

from .services import Period, ReportService


class PeriodForm(BootstrapFormMixin, forms.Form):
    start = forms.DateField(widget=DateInput())
    end = forms.DateField(widget=DateInput())
    group = forms.ChoiceField(choices=[("day", "By day"), ("month", "By month")], required=False)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("start") and cleaned.get("end") and cleaned["end"] < cleaned["start"]:
            raise forms.ValidationError("The end date must be on or after the start date.")
        return cleaned


class PeriodMixin:
    default_days = 30

    def get_period(self):
        default = Period.last_days(self.default_days)
        form = PeriodForm(self.request.GET or None, initial={"start": default.start, "end": default.end,
                                                             "group": "day"})
        self.period_form = form
        if form.is_bound and form.is_valid():
            return Period(form.cleaned_data["start"], form.cleaned_data["end"]), form.cleaned_data["group"] or "day"
        return default, "day"


class DashboardView(StaffRequiredMixin, TemplateView):
    template_name = "reporting/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(ReportService().dashboard())
        return ctx


class SalesReportView(StaffRequiredMixin, PeriodMixin, TemplateView):
    template_name = "reporting/sales.html"

    def get(self, request, *args, **kwargs):
        if request.GET.get("format") == "csv":
            return self.csv()
        return super().get(request, *args, **kwargs)

    def rows(self):
        period, group = self.get_period()
        return period, group, ReportService().sales_by(period, group)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        period, group, rows = self.rows()
        ctx.update(period=period, group=group, rows=rows, totals=ReportService.totals(rows), form=self.period_form)
        return ctx

    def csv(self):
        period, group, rows = self.rows()
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="sales_{period.start}_{period.end}.csv"'
        writer = csv.writer(response)
        writer.writerow(["period", "orders", "items", "gross", "discounts", "tax", "shipping", "revenue"])
        for r in rows:
            writer.writerow([r["bucket"], r["orders"], r["items"], r["gross"], r["discounts"], r["tax"],
                             r["shipping"], r["revenue"]])
        return response


class BestSellerView(StaffRequiredMixin, PeriodMixin, TemplateView):
    template_name = "reporting/best_sellers.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        period, _ = self.get_period()
        ctx.update(period=period, rows=ReportService().best_sellers(period), form=self.period_form)
        return ctx


class StockReportView(StaffRequiredMixin, TemplateView):
    template_name = "reporting/stock.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        kind = self.request.GET.get("kind", "alert")
        ctx.update(kind=kind, variants=ReportService.stock_report(kind), summary=ReportService.stock_summary())
        return ctx
