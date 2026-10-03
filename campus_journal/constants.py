"""Shared constants across campus_journal apps."""

from django import forms
from accounts.models import Department

DEPARTMENTS = [
    "Biomedical Engineering",
    "Mechanical Engineering",
    "Electrical Engineering",
    "Software Engineering",
    "Chemical Engineering",
    "Civil Engineering",
]

DEPARTMENT_CHOICES = [(dept, dept) for dept in DEPARTMENTS]


class DepartmentChoiceField(forms.ChoiceField):
    """
    Standardized dropdown field for the 6 canonical academic departments.
    Rejects values outside DEPARTMENTS while seamlessly converting the department
    name to the underlying Department model instance.
    """

    def __init__(self, *args, empty_label="Select your department", **kwargs):
        choices = [("", empty_label)] + [(d, d) for d in DEPARTMENTS]
        kwargs.setdefault("choices", choices)
        kwargs.setdefault("required", True)
        kwargs.setdefault("error_messages", {"required": "Select your department."})
        super().__init__(*args, **kwargs)

    def valid_value(self, value):
        if super().valid_value(value):
            return True
        # Allow resolving Department PK if the corresponding department is in the allowed list
        if str(value).isdigit():
            try:
                dept = Department.objects.get(pk=int(value))
                return dept.name in [c[0] for c in self.choices if c[0]]
            except Department.DoesNotExist:
                return False
        return False

    def to_python(self, value):
        val = super().to_python(value)
        if str(val).isdigit():
            try:
                dept = Department.objects.get(pk=int(val))
                if dept.name in [c[0] for c in self.choices if c[0]]:
                    return dept.name
            except Department.DoesNotExist:
                pass
        return val
