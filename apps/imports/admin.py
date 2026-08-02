from django.contrib import admin

from .models import ImportBatch


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = (
        "original_filename",
        "organization",
        "status",
        "uploaded_by",
        "created_at",
    )
    list_filter = ("status", "organization")
    search_fields = ("original_filename", "file_sha256", "uploaded_by__email")
    autocomplete_fields = ("organization", "uploaded_by")
    readonly_fields = (
        "id",
        "file_sha256",
        "storage_key",
        "created_at",
        "updated_at",
    )
