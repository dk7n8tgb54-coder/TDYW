from django.core.management.base import BaseCommand
from django.core.cache import cache
from apps.account.models import User, Role
import json


class Command(BaseCommand):
    help = '清除所有用户的权限缓存'

    def handle(self, *args, **options):
        self.stdout.write('=== 清除所有用户的权限缓存 ===')
        count = 0
        for user in User.objects.filter(deleted_by_id__isnull=True):
            cache.delete(f'perms_{user.id}')
            user.set_perms_cache()
            count += 1
            self.stdout.write(f'已清除用户 {user.username} 的权限缓存')

        self.stdout.write(self.style.SUCCESS(f'\n总共清除了 {count} 个用户的权限缓存'))

        self.stdout.write('\n=== 检查所有角色的 page_perms ===')
        for role in Role.objects.all():
            if role.page_perms:
                try:
                    perms = json.loads(role.page_perms)
                    self.stdout.write(f'角色: {role.name}, 模块: {list(perms.keys())}')
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'角色: {role.name}, page_perms 解析失败: {e}'))
            else:
                self.stdout.write(f'角色: {role.name}, page_perms 为空')
