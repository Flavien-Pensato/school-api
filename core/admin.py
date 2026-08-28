from django import forms
from django.contrib import admin, messages
from django.shortcuts import render

from .models import (
    DEFAULT_CLASS_NAMES,
    DEFAULT_GROUP_COUNT,
    DEFAULT_TASK_NAMES,
    Assignment,
    ClassPresence,
    Enrollment,
    Group,
    School,
    SchoolClass,
    SchoolMembership,
    SchoolYear,
    Student,
    Task,
    Week,
)
from .permissions import is_school_member

class NamesForm(forms.Form):
    """One name per line; blank lines and duplicates ignored."""

    empty_error = 'Au moins un nom est requis.'

    names = forms.CharField(widget=forms.Textarea(attrs={'rows': 15, 'cols': 40}))

    def clean_names(self):
        names, seen = [], set()
        for line in self.cleaned_data['names'].splitlines():
            name = line.strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        if not names:
            raise forms.ValidationError(self.empty_error)
        return names


class ClassNamesForm(NamesForm):
    empty_error = 'Au moins une classe est requise.'

    names = forms.CharField(
        label='Classes (une par ligne)',
        widget=forms.Textarea(attrs={'rows': 15, 'cols': 40}),
        initial='\n'.join(DEFAULT_CLASS_NAMES),
    )


class TaskNamesForm(NamesForm):
    empty_error = 'Au moins une tâche est requise.'

    names = forms.CharField(
        label='Tâches (une par ligne)',
        widget=forms.Textarea(attrs={'rows': 15, 'cols': 40}),
        initial='\n'.join(DEFAULT_TASK_NAMES),
    )


class GroupCountForm(forms.Form):
    count = forms.IntegerField(
        label='Nombre de groupes pour l\'année',
        min_value=1,
        max_value=50,
        initial=DEFAULT_GROUP_COUNT,
    )


def _confirm(modeladmin, request, queryset, form_class, action_name, **context):
    """Render (or process) the intermediate confirmation page of an action.

    Returns the bound form once the superuser confirms, else the response to
    return from the action.
    """
    if request.POST.get('confirmed'):
        form = form_class(request.POST)
        if form.is_valid():
            return form
    else:
        form = form_class()
    return render(request, 'admin/core/generate_form.html', {
        **modeladmin.admin_site.each_context(request),
        'opts': modeladmin.model._meta,
        'queryset': queryset,
        'form': form,
        'action_name': action_name,
        'action_checkbox_name': admin.helpers.ACTION_CHECKBOX_NAME,
        **context,
    })


# School and Week stay superuser-only: tenancy and derived data.


class SchoolScopedAdmin:
    """Per-school scoping of a ModelAdmin for is_staff (non-superuser) users.

    Membership is the only gate: this project has no Permission rows and no
    auth Groups (`core.keycloak.sync_user_roles` rewrites is_staff /
    is_superuser from the Keycloak realm roles on every login, so hand-granted
    perms would be the only mutable state and would silently rot). A staff user
    with at least one SchoolMembership gets view/add/change/delete on this
    model, restricted to the rows and the FK choices of their own schools — the
    same isolation the API gets from `.for_user()` and `UserScopedPKField`. A
    staff user with no membership sees nothing.

    ModelAdmins without this mixin fall back to Django's Permission-based
    defaults, which with no Permission rows means superuser-only.

    Mix in first: `class TaskAdmin(SchoolScopedAdmin, admin.ModelAdmin)`, so
    that a later get_queryset override still runs `.for_user()`. ModelAdmin
    only — InlineModelAdmin.has_add_permission takes (request, obj).
    """

    def _is_member(self, request):
        # Cached per request: the index calls the has_* hooks once per model.
        if not hasattr(request, '_school_member'):
            request._school_member = is_school_member(request.user)
        return request._school_member

    def get_queryset(self, request):
        return super().get_queryset(request).for_user(request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Every scoped model's manager knows its own path to School, so no
        # per-FK lookup table; unscoped targets (auth.User) are left alone.
        manager = db_field.remote_field.model._default_manager
        if hasattr(manager, 'for_user'):
            kwargs['queryset'] = manager.for_user(request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_module_permission(self, request):
        return self._is_member(request)

    def has_view_permission(self, request, obj=None):
        return self._is_member(request)

    def has_add_permission(self, request):
        return self._is_member(request)

    def has_change_permission(self, request, obj=None):
        return self._is_member(request)

    def has_delete_permission(self, request, obj=None):
        return self._is_member(request)


class SchoolMembershipInline(admin.TabularInline):
    model = SchoolMembership
    extra = 0
    autocomplete_fields = ['user']


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']
    inlines = [SchoolMembershipInline]


@admin.register(SchoolYear)
class SchoolYearAdmin(SchoolScopedAdmin, admin.ModelAdmin):
    list_display = [
        'name', 'school', 'start_date', 'end_date', 'week_count',
        'group_count',
    ]
    list_filter = [('school', admin.RelatedOnlyFieldListFilter)]
    actions = [
        'generate_classes', 'generate_weeks', 'generate_groups',
        'reset_groups', 'generate_tasks',
    ]

    @admin.display(description='semaines')
    def week_count(self, obj):
        return obj.weeks.count()

    @admin.display(description='groupes')
    def group_count(self, obj):
        return obj.groups.count()

    @admin.action(description='Générer les semaines de l\'année')
    def generate_weeks(self, request, queryset):
        """Years created through the API get their weeks from
        SchoolYearSerializer.create; years created here need this action —
        without weeks the presence grid has no columns."""
        created = 0
        for year in queryset:
            before = year.weeks.count()
            created += len(year.generate_weeks()) - before
        self.message_user(
            request,
            f'{created} semaine(s) créée(s) sur {queryset.count()} année(s).',
        )

    @admin.action(description='Générer les classes de l\'année')
    def generate_classes(self, request, queryset):
        result = _confirm(
            self, request, queryset, ClassNamesForm, 'generate_classes',
            title='Générer les classes',
            description=(
                'Une classe par ligne. Les classes déjà existantes sont '
                'conservées telles quelles.'
            ),
            submit_label='Générer les classes',
        )
        if not isinstance(result, ClassNamesForm):
            return result

        names = result.cleaned_data['names']
        created = 0
        for year in queryset:
            _, year_created = year.generate_classes(names)
            created += year_created
        self.message_user(
            request,
            f'{created} classe(s) créée(s) sur {queryset.count()} année(s) ; '
            f'{len(names) * queryset.count() - created} déjà existante(s).',
        )

    @admin.action(description='Générer les groupes de l\'année')
    def generate_groups(self, request, queryset):
        result = _confirm(
            self, request, queryset, GroupCountForm, 'generate_groups',
            title='Générer les groupes',
            description=(
                'Crée les groupes « 1 » … « N » pour chaque année '
                'sélectionnée. Un groupe rassemble des élèves de n’importe '
                'quelle classe. Les groupes existants sont conservés.'
            ),
            submit_label='Générer les groupes',
        )
        if not isinstance(result, GroupCountForm):
            return result

        count = result.cleaned_data['count']
        created = 0
        for year in queryset:
            _, year_created = year.generate_groups(count)
            created += year_created
        self.message_user(
            request,
            f'{created} groupe(s) créé(s) sur {queryset.count()} année(s) ; '
            f'{count * queryset.count() - created} déjà existant(s).',
        )

    @admin.action(description='Réinitialiser les groupes de l\'année')
    def reset_groups(self, request, queryset):
        """Rebuild a year whose groups still follow the old per-class blocks.
        Destructive — see SchoolYear.reset_groups."""
        result = _confirm(
            self, request, queryset, GroupCountForm, 'reset_groups',
            title='Réinitialiser les groupes',
            description=(
                'Supprime TOUS les groupes des années sélectionnées, puis '
                'recrée « 1 » … « N ». Les élèves perdent leur groupe et les '
                'tâches déjà attribuées sur ces années sont effacées. '
                'Irréversible.'
            ),
            submit_label='Supprimer et recréer les groupes',
        )
        if not isinstance(result, GroupCountForm):
            return result

        count = result.cleaned_data['count']
        deleted = 0
        for year in queryset:
            _, year_deleted = year.reset_groups(count)
            deleted += year_deleted
        self.message_user(
            request,
            f'{deleted} groupe(s) supprimé(s), '
            f'{count * queryset.count()} recréé(s) sur '
            f'{queryset.count()} année(s).',
            messages.WARNING,
        )

    @admin.action(description='Générer les tâches par défaut')
    def generate_tasks(self, request, queryset):
        """Tasks belong to the school, not the year; this action lives here
        because SchoolAdmin is superuser-only."""
        result = _confirm(
            self, request, queryset, TaskNamesForm, 'generate_tasks',
            title='Générer les tâches',
            description=(
                'Une tâche par ligne, dans l\'ordre de rotation. Les tâches '
                'déjà existantes sont conservées telles quelles.'
            ),
            submit_label='Générer les tâches',
        )
        if not isinstance(result, TaskNamesForm):
            return result

        names = result.cleaned_data['names']
        # Distinct schools: selecting two years of the same school must not
        # generate its tasks twice.
        schools = {year.school for year in queryset}
        created = 0
        for school in schools:
            _, school_created = school.generate_tasks(names)
            created += school_created
        self.message_user(
            request,
            f'{created} tâche(s) créée(s) sur {len(schools)} école(s) ; '
            f'{len(names) * len(schools) - created} déjà existante(s).',
        )


@admin.register(Week)
class WeekAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'start_date', 'school_year']
    list_filter = ['school_year']
    ordering = ['start_date']


@admin.register(Student)
class StudentAdmin(SchoolScopedAdmin, admin.ModelAdmin):
    list_display = ['last_name', 'first_name', 'school', 'external_id']
    list_filter = [('school', admin.RelatedOnlyFieldListFilter)]
    search_fields = ['last_name', 'first_name', 'external_id']


@admin.register(SchoolClass)
class SchoolClassAdmin(SchoolScopedAdmin, admin.ModelAdmin):
    list_display = ['name', 'school_year']
    list_filter = [('school_year', admin.RelatedOnlyFieldListFilter)]
    search_fields = ['name']


@admin.register(Group)
class GroupAdmin(SchoolScopedAdmin, admin.ModelAdmin):
    list_display = ['name', 'school_year']
    list_select_related = ['school_year']
    list_filter = [('school_year', admin.RelatedOnlyFieldListFilter)]
    search_fields = ['name']


@admin.register(Enrollment)
class EnrollmentAdmin(SchoolScopedAdmin, admin.ModelAdmin):
    list_display = ['student', 'school_class', 'group']
    list_filter = [('school_year', admin.RelatedOnlyFieldListFilter)]
    autocomplete_fields = ['student']


@admin.register(Task)
class TaskAdmin(SchoolScopedAdmin, admin.ModelAdmin):
    list_display = ['name', 'school', 'is_active']
    list_filter = [('school', admin.RelatedOnlyFieldListFilter), 'is_active']
    search_fields = ['name']


@admin.register(ClassPresence)
class ClassPresenceAdmin(SchoolScopedAdmin, admin.ModelAdmin):
    list_display = ['school_class', 'week']
    list_filter = [('week__school_year', admin.RelatedOnlyFieldListFilter)]


@admin.register(Assignment)
class AssignmentAdmin(SchoolScopedAdmin, admin.ModelAdmin):
    list_display = ['week', 'task', 'group', 'is_manual']
    list_filter = [('week__school_year', admin.RelatedOnlyFieldListFilter), 'is_manual']
