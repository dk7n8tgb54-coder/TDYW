# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.contrib import admin

from .models import (Manual, ManualAuthorization, ManualCategory,
                     ManualChapter, ManualDraft, ManualEditSession,
                     ManualOperationLog, ManualVersion)


@admin.register(ManualCategory)
class ManualCategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'sort_order', 'is_active', 'created_at')
    search_fields = ('name',)


class ManualChapterInline(admin.TabularInline):
    model = ManualChapter
    extra = 0


class ManualVersionInline(admin.TabularInline):
    model = ManualVersion
    extra = 0
    readonly_fields = ('published_at', 'file_hash')


@admin.register(Manual)
class ManualAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'code', 'category', 'org_type', 'org_name',
                    'owner', 'status', 'current_version', 'created_at')
    list_filter = ('status', 'org_type', 'category')
    search_fields = ('name', 'code', 'org_name')
    inlines = [ManualChapterInline, ManualVersionInline]


@admin.register(ManualAuthorization)
class ManualAuthorizationAdmin(admin.ModelAdmin):
    list_display = ('id', 'manual', 'account', 'can_view', 'can_edit',
                    'can_publish', 'updated_at', 'updated_by')
    search_fields = ('manual__name', 'account__username')


@admin.register(ManualDraft)
class ManualDraftAdmin(admin.ModelAdmin):
    list_display = ('id', 'manual', 'original_name', 'revision', 'last_saved_by', 'last_saved_at')


@admin.register(ManualVersion)
class ManualVersionAdmin(admin.ModelAdmin):
    list_display = ('id', 'manual', 'version_no', 'original_name', 'file_size',
                    'published_by', 'published_at', 'is_effective')


@admin.register(ManualEditSession)
class ManualEditSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'manual', 'user', 'session_key', 'revision_at_start',
                    'started_at', 'expires_at', 'revoked_at')


@admin.register(ManualOperationLog)
class ManualOperationLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'manual', 'user_name', 'action', 'version', 'created_at')
