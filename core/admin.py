from django.contrib import admin

from .models import (
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


@admin.register(SchoolYear)
class SchoolYearAdmin(admin.ModelAdmin):
    list_display = ['name', 'school', 'start_date', 'end_date']
    list_filter = ['school']


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
    list_display = ['name', 'school_year']
    list_filter = ['school_year']
    search_fields = ['name']


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
