from django import forms
from django.contrib import admin
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
        label='Nombre de groupes par classe',
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


# Admin is superuser territory (Keycloak realm role django-superuser); no
# per-school scoping here for v1 — staff use the API. If is_staff users ever
# get admin access, scope each ModelAdmin.get_queryset with .for_user().


class SchoolMembershipInline(admin.TabularInline):
    model = SchoolMembership
    extra = 0
    autocomplete_fields = ['user']


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']
    inlines = [SchoolMembershipInline]
    actions = ['generate_tasks']

    @admin.action(description='Générer les tâches par défaut')
    def generate_tasks(self, request, queryset):
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
        created = 0
        for school in queryset:
            _, school_created = school.generate_tasks(names)
            created += school_created
        self.message_user(
            request,
            f'{created} tâche(s) créée(s) sur {queryset.count()} école(s) ; '
            f'{len(names) * queryset.count() - created} déjà existante(s).',
        )


@admin.register(SchoolYear)
class SchoolYearAdmin(admin.ModelAdmin):
    list_display = ['name', 'school', 'start_date', 'end_date', 'week_count']
    list_filter = ['school']
    actions = ['generate_classes', 'generate_weeks']

    @admin.display(description='semaines')
    def week_count(self, obj):
        return obj.weeks.count()

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


@admin.register(Week)
class WeekAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'start_date', 'school_year']
    list_filter = ['school_year']
    ordering = ['start_date']


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ['last_name', 'first_name', 'school', 'external_id']
    list_filter = ['school']
    search_fields = ['last_name', 'first_name', 'external_id']


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ['name', 'school_year', 'group_count']
    list_filter = ['school_year']
    search_fields = ['name']
    actions = ['generate_groups']

    @admin.display(description='groupes')
    def group_count(self, obj):
        return obj.groups.count()

    @admin.action(description='Générer les groupes')
    def generate_groups(self, request, queryset):
        result = _confirm(
            self, request, queryset, GroupCountForm, 'generate_groups',
            title='Générer les groupes',
            description=(
                'Crée N groupes numérotés pour chaque classe sélectionnée. '
                'La numérotation se poursuit d’une classe à l’autre sur '
                'l’année : « 1 » … « 10 » pour la première, « 11 » … « 20 » '
                'pour la suivante. Les groupes existants sont conservés.'
            ),
            submit_label='Générer les groupes',
        )
        if not isinstance(result, GroupCountForm):
            return result

        count = result.cleaned_data['count']
        created = 0
        for school_class in queryset:
            _, class_created = school_class.generate_groups(count)
            created += class_created
        self.message_user(
            request,
            f'{created} groupe(s) créé(s) sur {queryset.count()} classe(s) ; '
            f'{count * queryset.count() - created} déjà existant(s).',
        )


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'school_class']
    list_filter = ['school_class__school_year']
    search_fields = ['name']


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ['student', 'school_class', 'group']
    list_filter = ['school_year']
    autocomplete_fields = ['student']


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['name', 'school', 'is_active']
    list_filter = ['school', 'is_active']
    search_fields = ['name']


@admin.register(ClassPresence)
class ClassPresenceAdmin(admin.ModelAdmin):
    list_display = ['school_class', 'week']
    list_filter = ['week__school_year']


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ['week', 'task', 'group', 'is_manual']
    list_filter = ['week__school_year', 'is_manual']
