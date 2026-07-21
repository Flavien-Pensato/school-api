import copy

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

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


class UserScopedPKField(serializers.PrimaryKeyRelatedField):
    """PrimaryKeyRelatedField whose queryset is filtered to the requesting
    user's schools — cross-school references fail validation with the same
    error as a nonexistent pk."""

    def get_queryset(self):
        return super().get_queryset().for_user(self.context['request'].user)


class SchoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = School
        fields = ['id', 'name']


class SchoolYearSerializer(serializers.ModelSerializer):
    school = UserScopedPKField(queryset=School.objects.all())

    class Meta:
        model = SchoolYear
        fields = ['id', 'school', 'name', 'start_date', 'end_date']

    def validate(self, attrs):
        start = attrs.get('start_date', getattr(self.instance, 'start_date', None))
        end = attrs.get('end_date', getattr(self.instance, 'end_date', None))
        if start and end and start >= end:
            raise serializers.ValidationError(
                'start_date must be before end_date.'
            )
        return attrs

    def create(self, validated_data):
        year = super().create(validated_data)
        year.generate_weeks()
        return year


class WeekSerializer(serializers.ModelSerializer):
    label = serializers.ReadOnlyField()

    class Meta:
        model = Week
        fields = ['id', 'school_year', 'start_date', 'label']


class ModelCleanMixin:
    """Surfaces the model's clean() cross-parent checks as DRF field errors."""

    def validate(self, attrs):
        instance = copy.copy(self.instance) if self.instance else self.Meta.model()
        for key, value in attrs.items():
            setattr(instance, key, value)
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, 'message_dict') else exc.messages
            )
        return attrs


class StudentSerializer(serializers.ModelSerializer):
    school = UserScopedPKField(queryset=School.objects.all())

    class Meta:
        model = Student
        fields = ['id', 'school', 'first_name', 'last_name', 'external_id']


class SchoolClassSerializer(serializers.ModelSerializer):
    school_year = UserScopedPKField(queryset=SchoolYear.objects.all())

    class Meta:
        model = SchoolClass
        fields = ['id', 'school_year', 'name']


class GroupSerializer(serializers.ModelSerializer):
    school_class = UserScopedPKField(queryset=SchoolClass.objects.all())

    class Meta:
        model = Group
        fields = ['id', 'school_class', 'name']


class EnrollmentSerializer(ModelCleanMixin, serializers.ModelSerializer):
    student = UserScopedPKField(queryset=Student.objects.all())
    school_year = UserScopedPKField(queryset=SchoolYear.objects.all())
    school_class = UserScopedPKField(queryset=SchoolClass.objects.all())
    group = UserScopedPKField(
        queryset=Group.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Enrollment
        fields = ['id', 'student', 'school_year', 'school_class', 'group']


class TaskSerializer(serializers.ModelSerializer):
    school = UserScopedPKField(queryset=School.objects.all())
    # explicit default so form/multipart POSTs missing the field don't get
    # DRF's unchecked-checkbox False
    is_active = serializers.BooleanField(default=True)

    class Meta:
        model = Task
        fields = ['id', 'school', 'name', 'is_active']


class AssignmentSerializer(ModelCleanMixin, serializers.ModelSerializer):
    week = UserScopedPKField(queryset=Week.objects.all())
    task = UserScopedPKField(queryset=Task.objects.all())
    group = UserScopedPKField(queryset=Group.objects.all())
    task_name = serializers.ReadOnlyField(source='task.name')
    group_name = serializers.ReadOnlyField(source='group.name')

    class Meta:
        model = Assignment
        fields = [
            'id', 'week', 'task', 'group',
            'task_name', 'group_name', 'is_manual',
        ]
        read_only_fields = ['is_manual']

    def save(self, **kwargs):
        # Any staff write through the API is an override the rotation
        # must respect on regeneration.
        return super().save(is_manual=True, **kwargs)


class StudentImportSerializer(serializers.Serializer):
    file = serializers.FileField()
    school_class = UserScopedPKField(queryset=SchoolClass.objects.all())


class ClassPresenceSerializer(ModelCleanMixin, serializers.ModelSerializer):
    week = UserScopedPKField(queryset=Week.objects.all())
    school_class = UserScopedPKField(queryset=SchoolClass.objects.all())

    class Meta:
        model = ClassPresence
        fields = ['id', 'week', 'school_class']
