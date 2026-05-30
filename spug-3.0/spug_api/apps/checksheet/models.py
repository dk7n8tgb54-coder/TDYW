# Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import models
import json


class CheckSheetTemplate(models.Model):
    """检查表模板"""
    project = models.CharField('项目名称', max_length=100)
    check_items = models.TextField('检查项目列表', default='[]')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'tdyw_checksheet_template'
        verbose_name = '检查表模板'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        items = json.loads(self.check_items) if isinstance(self.check_items, str) else self.check_items
        return f'{self.project} ({len(items)}项)'

    def get_check_items(self):
        """获取检查项目列表"""
        if isinstance(self.check_items, str):
            return json.loads(self.check_items)
        return self.check_items

    def set_check_items(self, items):
        """设置检查项目列表"""
        self.check_items = json.dumps(items, ensure_ascii=False)


class CheckSheetRecord(models.Model):
    """检查记录"""
    template = models.ForeignKey(CheckSheetTemplate, on_delete=models.CASCADE, verbose_name='检查模板')
    year = models.CharField('年份', max_length=4)
    month = models.CharField('月份', max_length=2)
    day = models.IntegerField('日期')
    item_index = models.IntegerField('检查项索引')
    status = models.CharField('状态', max_length=10,
                            choices=[('NORMAL', '正常'), ('ABNORMAL', '异常'), ('UNCHECKED', '未检查')],
                            default='UNCHECKED')
    remark = models.TextField('备注', blank=True, null=True)
    rectification = models.TextField('发现问题及整改情况', blank=True, null=True)
    operator = models.CharField('操作人', max_length=50, blank=True, null=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'tdyw_checksheet_record'
        verbose_name = '检查记录'
        verbose_name_plural = verbose_name
        ordering = ['year', 'month', 'day', 'item_index']
        unique_together = ['template', 'year', 'month', 'day', 'item_index']

    def __str__(self):
        return f'{self.template.project} {self.year}-{self.month}-{self.day} 第{self.item_index + 1}项'


class CheckSheetDailySummary(models.Model):
    """每日检查汇总 - 存储每天的备注、整改情况和值班人员"""
    year = models.CharField('年份', max_length=4)
    month = models.CharField('月份', max_length=2)
    day = models.IntegerField('日期')
    operator = models.CharField('值班人员', max_length=50, blank=True, null=True)
    remark = models.TextField('备注', blank=True, null=True)
    rectification = models.TextField('发现问题及整改情况', blank=True, null=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'tdyw_checksheet_daily_summary'
        verbose_name = '每日检查汇总'
        verbose_name_plural = verbose_name
        unique_together = ['year', 'month', 'day']

    def __str__(self):
        return f'{self.year}-{self.month}-{self.day} 汇总'
