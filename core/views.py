from django.db import models
from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .pdf import render_week_dashboard_pdf

from .models import (
    Assignment,
    ClassPresence,
    Enrollment,
    Group,
    School,
    SchoolClass,
    SchoolYear,
    Student,
    Task,
    Week,
)
from .permissions import IsSchoolMember
from .serializers import (
    AssignmentSerializer,
    ClassPresenceSerializer,
    EnrollmentSerializer,
    GroupSerializer,
    SchoolClassSerializer,
    SchoolSerializer,
    SchoolYearSerializer,
    StudentImportSerializer,
    StudentSerializer,
    TaskSerializer,
    WeekSerializer,
)


class HealthCheckView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'status': 'ok'})


class SchoolScopedViewSetMixin:
    """Filters every queryset to the requesting user's schools. Detail
    access to another school's object 404s (existence not revealed);
    update/delete are covered because object lookup goes through
    get_queryset."""

    def get_queryset(self):
        return super().get_queryset().for_user(self.request.user)

    def filter_by_params(self, queryset, **param_to_field):
        """Apply ?param=value filters: filter_by_params(qs, school='school_id')."""
        for param, field in param_to_field.items():
            value = self.request.query_params.get(param)
            if value is not None:
                queryset = queryset.filter(**{field: value})
        return queryset


class SchoolViewSet(SchoolScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = School.objects.all()
    serializer_class = SchoolSerializer
    permission_classes = [IsSchoolMember]


class SchoolYearViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = SchoolYear.objects.all()
    serializer_class = SchoolYearSerializer
    permission_classes = [IsSchoolMember]

    def get_queryset(self):
        return self.filter_by_params(super().get_queryset(), school='school_id')

    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        return Response(services.build_year_stats(self.get_object()))


class WeekViewSet(SchoolScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Week.objects.all()
    serializer_class = WeekSerializer
    permission_classes = [IsSchoolMember]

    def get_queryset(self):
        qs = self.filter_by_params(
            super().get_queryset(), school_year='school_year_id'
        )
        date_param = self.request.query_params.get('date')
        if date_param is not None:
            # the week containing this date: start_date <= date < start_date + 7
            from datetime import date, timedelta
            target = date.fromisoformat(date_param)
            monday = target - timedelta(days=target.weekday())
            qs = qs.filter(start_date=monday)
        return qs

    @action(detail=True, methods=['post'], url_path='generate-assignments')
    def generate_assignments(self, request, pk=None):
        week = self.get_object()
        result = services.generate_week_assignments(week)
        serializer = AssignmentSerializer(
            result['assignments'], many=True, context={'request': request}
        )
        return Response({
            'assignments': serializer.data,
            'explanation': result['explanation'],
        })

    @action(detail=True, methods=['get'])
    def dashboard(self, request, pk=None):
        return Response(services.build_week_dashboard(self.get_object()))

    @action(detail=True, methods=['get'], url_path='dashboard/pdf')
    def dashboard_pdf(self, request, pk=None):
        week = self.get_object()
        pdf_bytes = render_week_dashboard_pdf(
            services.build_week_dashboard(week)
        )
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'inline; filename="semaine-{week.label}.pdf"'
        )
        return response


class AssignmentViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Assignment.objects.select_related('task', 'group')
    serializer_class = AssignmentSerializer
    permission_classes = [IsSchoolMember]

    def get_queryset(self):
        return self.filter_by_params(
            super().get_queryset(),
            week='week_id',
            group='group_id',
            task='task_id',
        )


class StudentViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Student.objects.all()
    serializer_class = StudentSerializer
    permission_classes = [IsSchoolMember]

    def get_queryset(self):
        qs = self.filter_by_params(super().get_queryset(), school='school_id')
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(
                models.Q(first_name__icontains=search)
                | models.Q(last_name__icontains=search)
            )
        return qs

    @action(
        detail=False,
        methods=['post'],
        parser_classes=[MultiPartParser],
        url_path='import',
        url_name='import',
    )
    def import_file(self, request):
        serializer = StudentImportSerializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        file = serializer.validated_data['file']
        school_class = serializer.validated_data['school_class']
        try:
            records = services.parse_student_file(file, file.name)
            counts = services.import_students(school_class, records)
        except services.ImportError_ as exc:
            return Response({'errors': exc.errors}, status=400)
        return Response(counts, status=201)


class SchoolClassViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = SchoolClass.objects.all()
    serializer_class = SchoolClassSerializer
    permission_classes = [IsSchoolMember]

    def get_queryset(self):
        return self.filter_by_params(
            super().get_queryset(), school_year='school_year_id'
        )


class GroupViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer
    permission_classes = [IsSchoolMember]

    def get_queryset(self):
        return self.filter_by_params(
            super().get_queryset(), school_class='school_class_id'
        )


class EnrollmentViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Enrollment.objects.select_related('student', 'group')
    serializer_class = EnrollmentSerializer
    permission_classes = [IsSchoolMember]

    def get_queryset(self):
        return self.filter_by_params(
            super().get_queryset(),
            school_year='school_year_id',
            school_class='school_class_id',
            group='group_id',
        )


class TaskViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Task.objects.all()
    serializer_class = TaskSerializer
    permission_classes = [IsSchoolMember]

    def get_queryset(self):
        return self.filter_by_params(super().get_queryset(), school='school_id')


class ClassPresenceViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = ClassPresence.objects.select_related('week', 'school_class')
    serializer_class = ClassPresenceSerializer
    permission_classes = [IsSchoolMember]

    def get_queryset(self):
        return self.filter_by_params(
            super().get_queryset(),
            week='week_id',
            school_year='week__school_year_id',
        )
