from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Department, Profile, Role, User, UserRole


class UserRoleInline(admin.TabularInline):
    model = UserRole
    fk_name = 'user'
    extra = 1
    autocomplete_fields = ['role']
    readonly_fields = ['assigned_at']


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    extra = 0


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """
    This is deliberately the main place administrators grant roles
    (Reviewer, Journal Manager, News Editor, Administrator, ...) --
    exactly the "who can do what" control panel the architecture plan
    calls for, reusing Django's built-in admin rather than building a
    custom roles UI from scratch.
    """

    inlines = [ProfileInline, UserRoleInline]
    list_display = ('username', 'email', 'first_name', 'last_name', 'role_list', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'roles')
    search_fields = ('username', 'first_name', 'last_name', 'email')

    def role_list(self, obj):
        return ', '.join(obj.role_slugs()) or '—'
    role_list.short_description = 'Roles'


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'description')
    search_fields = ('name', 'slug')


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'short_name')
    search_fields = ('name', 'short_name')


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'department', 'class_year', 'is_public')
    list_filter = ('department', 'is_public')
    search_fields = ('user__username', 'user__first_name', 'user__last_name')
