from django.contrib import admin

from .models import Organization, SchoolBoardMember, SchoolBoardPeriod


class ReadOnlyHistoryAdminMixin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "email",
        "kind",
        "educational_center_type",
        "department",
        "municipality",
        "district",
        "is_active",
    )
    list_filter = (
        "kind",
        "educational_center_type",
        "department",
        "municipality",
        "district",
        "is_active",
    )
    search_fields = (
        "code",
        "name",
        "email",
        "educational_center_type",
        "department",
        "municipality",
        "district",
        "address",
    )


class SchoolBoardMemberInline(admin.TabularInline):
    model = SchoolBoardMember
    extra = 0
    can_delete = False
    readonly_fields = ("created_at", "updated_at")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SchoolBoardPeriod)
class SchoolBoardPeriodAdmin(ReadOnlyHistoryAdminMixin, admin.ModelAdmin):
    list_display = (
        "organization",
        "school_year_start",
        "school_year_end",
        "start_date",
        "end_date",
        "is_current",
    )
    list_filter = ("is_current", "school_year_start", "organization__department")
    search_fields = ("organization__code", "organization__name")
    autocomplete_fields = ("organization", "created_by", "updated_by")
    readonly_fields = ("created_at", "updated_at")
    inlines = (SchoolBoardMemberInline,)


@admin.register(SchoolBoardMember)
class SchoolBoardMemberAdmin(ReadOnlyHistoryAdminMixin, admin.ModelAdmin):
    list_display = ("full_name", "period", "position", "sector", "is_legal_representative", "left_on")
    list_filter = ("sector", "is_legal_representative", "left_on")
    search_fields = ("full_name", "identity_document", "period__organization__name")
    autocomplete_fields = ("period", "created_by", "updated_by")
    readonly_fields = ("created_at", "updated_at")
