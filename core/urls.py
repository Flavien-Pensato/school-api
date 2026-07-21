from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core.views import (
    AssignmentViewSet,
    ClassPresenceViewSet,
    EnrollmentViewSet,
    GroupViewSet,
    HealthCheckView,
    SchoolClassViewSet,
    SchoolViewSet,
    SchoolYearViewSet,
    StudentViewSet,
    TaskViewSet,
    WeekViewSet,
)

router = DefaultRouter()
router.register('schools', SchoolViewSet, basename='school')
router.register('school-years', SchoolYearViewSet, basename='schoolyear')
router.register('weeks', WeekViewSet, basename='week')
router.register('students', StudentViewSet, basename='student')
router.register('classes', SchoolClassViewSet, basename='schoolclass')
router.register('groups', GroupViewSet, basename='group')
router.register('enrollments', EnrollmentViewSet, basename='enrollment')
router.register('tasks', TaskViewSet, basename='task')
router.register('presences', ClassPresenceViewSet, basename='classpresence')
router.register('assignments', AssignmentViewSet, basename='assignment')

urlpatterns = [
    path('health/', HealthCheckView.as_view(), name='health'),
    path('', include(router.urls)),
]
