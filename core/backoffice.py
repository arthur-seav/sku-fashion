"""Generic back-office CRUD.

Most master data (brands, sizes, colors, shipping methods, coupons …) needs
the same four screens: a searchable list, a create form, an edit form and a
delete confirmation. `CrudViewSet` describes one entity; it produces the four
views and their URL patterns, all rendered by the shared templates in
`templates/backoffice/crud/`.

    class BrandViewSet(CrudViewSet):
        model = Brand
        form_class = BrandForm
        name = "brand"
        list_display = [("Name", "name"), ("Slug", "slug")]
        search_fields = ["name"]

    urlpatterns = [*BrandViewSet().urls()]
"""

from django.contrib import messages
from django.db.models import ProtectedError, Q
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from core.permissions import StaffRequiredMixin


class CrudViewSet:
    model = None
    form_class = None
    name = ""                 # URL name prefix, e.g. "brand" -> brand_list
    namespace = ""            # URL namespace of the including urls.py
    section = ""              # breadcrumb section, e.g. "Catalog"
    title = ""                # singular, defaults to model verbose_name
    title_plural = ""
    description = ""
    list_display = [("Name", "name")]
    search_fields = []
    ordering = None
    paginate_by = 25
    select_related = ()
    detail_url_name = ""      # optional: link rows to a custom detail page

    # ---- configuration helpers ---------------------------------------
    def get_title(self):
        return self.title or self.model._meta.verbose_name.title()

    def get_title_plural(self):
        return self.title_plural or self.model._meta.verbose_name_plural.title()

    def url_name(self, action):
        return f"{self.namespace}:{self.name}_{action}"

    def get_queryset(self, request):
        qs = self.model._default_manager.all()
        if self.select_related:
            qs = qs.select_related(*self.select_related)
        if self.ordering:
            qs = qs.order_by(*self.ordering)
        q = request.GET.get("q", "").strip()
        if q and self.search_fields:
            cond = Q()
            for field in self.search_fields:
                cond |= Q(**{f"{field}__icontains": q})
            qs = qs.filter(cond)
        return qs

    def row_url(self, obj):
        if self.detail_url_name:
            return reverse(self.detail_url_name, args=[obj.pk])
        return reverse(self.url_name("update"), args=[obj.pk])

    # ---- cell rendering ------------------------------------------------
    def render_cell(self, obj, accessor):
        value = accessor(obj) if callable(accessor) else self._resolve(obj, accessor)
        if isinstance(value, SafeString):
            return value
        if isinstance(value, bool):
            return format_html('<span class="badge {}">{}</span>',
                               "tone-success" if value else "tone-outline", "Yes" if value else "No")
        if value is None or value == "":
            return mark_safe('<span class="text-muted">—</span>')
        return format_html("{}", value)

    @staticmethod
    def _resolve(obj, dotted):
        value = obj
        for part in dotted.split("."):
            value = getattr(value, part, None)
            if value is None:
                return None
        return value() if callable(value) else value

    # ---- views & urls --------------------------------------------------
    list_view_class = None
    create_view_class = None
    update_view_class = None
    delete_view_class = None

    def urls(self):
        list_cls = self.list_view_class or CrudListView
        create_cls = self.create_view_class or CrudCreateView
        update_cls = self.update_view_class or CrudUpdateView
        delete_cls = self.delete_view_class or CrudDeleteView
        return [
            path(f"{self.name}s/", list_cls.as_view(viewset=self), name=f"{self.name}_list"),
            path(f"{self.name}s/new/", create_cls.as_view(viewset=self), name=f"{self.name}_create"),
            path(f"{self.name}s/<int:pk>/edit/", update_cls.as_view(viewset=self), name=f"{self.name}_update"),
            path(f"{self.name}s/<int:pk>/delete/", delete_cls.as_view(viewset=self), name=f"{self.name}_delete"),
        ]


class CrudMixin(StaffRequiredMixin):
    viewset = None

    def get_queryset(self):
        return self.viewset.get_queryset(self.request)

    def get_success_url(self):
        return reverse(self.viewset.url_name("list"))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        vs = self.viewset
        ctx.update({
            "vs": vs,
            "vs_title": vs.get_title(),
            "vs_title_plural": vs.get_title_plural(),
            "list_url": reverse(vs.url_name("list")),
            "create_url": reverse(vs.url_name("create")),
        })
        return ctx


class CrudListView(CrudMixin, ListView):
    template_name = "backoffice/crud/list.html"

    def get_queryset(self):
        qs = super().get_queryset()
        if not qs.ordered:  # aggregate queries drop Meta.ordering; keep paging stable
            qs = qs.order_by(*(self.viewset.model._meta.ordering or ["pk"]))
        return qs

    def get_paginate_by(self, queryset):
        return self.viewset.paginate_by

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        vs = self.viewset
        ctx["columns"] = [label for label, _ in vs.list_display]
        ctx["rows"] = [
            {
                "obj": obj,
                "url": vs.row_url(obj),
                "edit_url": reverse(vs.url_name("update"), args=[obj.pk]),
                "delete_url": reverse(vs.url_name("delete"), args=[obj.pk]),
                "cells": [vs.render_cell(obj, accessor) for _, accessor in vs.list_display],
            }
            for obj in ctx["object_list"]
        ]
        return ctx


class CrudFormMixin(CrudMixin):
    template_name = "backoffice/crud/form.html"

    def get_form_class(self):
        return self.viewset.form_class

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"{self.viewset.get_title()} “{self.object}” saved.")
        return response


class CrudCreateView(CrudFormMixin, CreateView):
    pass


class CrudUpdateView(CrudFormMixin, UpdateView):
    pass


class CrudDeleteView(CrudMixin, DeleteView):
    template_name = "backoffice/crud/confirm_delete.html"

    def form_valid(self, form):
        label = str(self.object)
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, f"“{label}” is still referenced by other records and cannot be "
                                         f"deleted. Deactivate it instead, where possible.")
            return redirect(self.get_success_url())
        messages.success(self.request, f"{self.viewset.get_title()} “{label}” deleted.")
        return response
