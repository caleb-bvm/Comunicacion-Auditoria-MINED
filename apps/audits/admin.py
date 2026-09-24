from django.contrib import admin

from .models import (
    ActivityLog,
    AuditCase,
    AuditDocument,
    AuditInquiry,
    AuditInquiryAttachment,
    AuditInquiryMessage,
    BusinessDayHoliday,
    CaseDecision,
    DeadlineExtension,
    Evidence,
    Finding,
    HistoricalRecommendation,
    Recommendation,
    Response,
    Review,
)


class NoDeleteAdminMixin:
    def has_delete_permission(self, request, obj=None):
        return False


class AuditInquiryMessageInline(admin.TabularInline):
    model = AuditInquiryMessage
    extra = 0
    can_delete = False
    readonly_fields = ("author", "body", "created_at")


@admin.register(AuditInquiry)
class AuditInquiryAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("id", "subject", "organization", "status", "priority", "assigned_auditor", "updated_at")
    list_filter = ("status", "priority", "category")
    search_fields = ("subject", "organization__name", "case__reference")
    readonly_fields = ("organization", "case", "created_by", "created_at", "updated_at", "closed_at")
    inlines = (AuditInquiryMessageInline,)


@admin.register(AuditInquiryAttachment)
class AuditInquiryAttachmentAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("original_filename", "inquiry", "uploaded_by", "uploaded_at")
    readonly_fields = ("inquiry", "message", "file", "original_filename", "size", "sha256", "uploaded_by", "uploaded_at")


class RecommendationInline(admin.StackedInline):
    model = Recommendation
    extra = 0
    can_delete = False


@admin.register(AuditCase)
class AuditCaseAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("reference", "audited_organization", "status", "assigned_auditor", "response_deadline")
    list_filter = ("status", "audited_organization__department")
    search_fields = ("reference", "title", "audited_organization__name", "audited_organization__code")
    autocomplete_fields = ("audited_organization", "assigned_auditor", "created_by")


@admin.register(Finding)
class FindingAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("case", "number", "title", "risk_level")
    list_filter = ("risk_level",)
    search_fields = ("case__reference", "title")
    inlines = (RecommendationInline,)


@admin.register(Recommendation)
class RecommendationAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("__str__", "responsible_organization", "deadline", "status")
    list_filter = ("status", "deadline", "responsible_organization__kind")
    search_fields = ("finding__case__reference", "text", "responsible_organization__name")


@admin.register(Response)
class ResponseAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("recommendation", "version", "declared_status", "school_board_period", "submitted_by", "submitted_at")
    list_filter = ("declared_status", "submitted_at")
    readonly_fields = ("submitted_at",)


@admin.register(Evidence)
class EvidenceAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("original_filename", "response", "category", "scan_status", "uploaded_at")
    list_filter = ("scan_status", "category")
    search_fields = ("original_filename", "description", "sha256")
    readonly_fields = ("sha256", "size", "uploaded_at")


@admin.register(Review)
class ReviewAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("response", "outcome", "reviewed_by", "reviewed_at")
    list_filter = ("outcome",)
    readonly_fields = ("reviewed_at",)


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "case", "ip_address")
    list_filter = ("action", "created_at")
    search_fields = ("actor__username", "case__reference", "target_id")
    readonly_fields = (
        "actor",
        "case",
        "action",
        "target_type",
        "target_id",
        "details",
        "ip_address",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CaseDecision)
class CaseDecisionAdmin(admin.ModelAdmin):
    list_display = ("requested_at", "case", "kind", "status", "requested_by", "decided_by")
    list_filter = ("kind", "status", "requested_at")
    search_fields = ("case__reference", "case__audited_organization__name", "decision_note")
    readonly_fields = (
        "case",
        "kind",
        "status",
        "request_note",
        "previous_case_status",
        "requested_by",
        "requested_at",
        "decision_note",
        "decided_by",
        "decided_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditDocument)
class AuditDocumentAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "reference",
        "title",
        "organization",
        "document_type",
        "version",
        "status",
        "uploaded_at",
    )
    list_filter = ("document_type", "status", "visibility", "organization__kind")
    search_fields = ("reference", "title", "organization__name", "original_filename")
    readonly_fields = ("original_filename", "size", "sha256", "uploaded_by", "uploaded_at")


@admin.register(HistoricalRecommendation)
class HistoricalRecommendationAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("source_document", "number", "responsible_organization", "status")
    list_filter = ("status", "source_document__organization")
    search_fields = ("source_document__reference", "text", "responsible_description")
    readonly_fields = ("recorded_by", "recorded_at")


@admin.register(DeadlineExtension)
class DeadlineExtensionAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "recommendation",
        "previous_deadline",
        "new_deadline",
        "business_days",
        "granted_by",
        "granted_at",
    )
    readonly_fields = (
        "recommendation",
        "previous_deadline",
        "business_days",
        "new_deadline",
        "reason",
        "granted_by",
        "granted_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(BusinessDayHoliday)
class BusinessDayHolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
