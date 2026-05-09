"""
Verifications admin.
"""

from django.contrib import admin
from .models import UploadedFile, Verification, VerificationJob


@admin.register(UploadedFile)
class UploadedFileAdmin(admin.ModelAdmin):
    list_display = ('original_filename', 'mime_type', 'size_bytes', 'owner_user', 'owner_organization', 'created_at')
    search_fields = ('original_filename', 'sha256', 'storage_key')
    readonly_fields = ('id', 'created_at')
    ordering = ('-created_at',)


@admin.register(Verification)
class VerificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'modality', 'status', 'trust_score', 'verdict', 'bits_charged', 'user', 'organization', 'created_at')
    list_filter = ('modality', 'status', 'verdict')
    search_fields = ('user__email', 'organization__name')
    readonly_fields = ('id', 'created_at', 'started_at', 'completed_at')
    ordering = ('-created_at',)


@admin.register(VerificationJob)
class VerificationJobAdmin(admin.ModelAdmin):
    list_display = ('verification', 'attempts', 'celery_task_id', 'ml_endpoint', 'started_at', 'completed_at')
    search_fields = ('celery_task_id', 'verification__id')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('-created_at',)
