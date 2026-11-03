# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""制度管理业务模型

设计原则（依据根目录《制度管理模块设计方案》）：
- 手册主记录（Manual）承载名称、编号、类别、业务归属（org_type/
  org_name，展示字段）、状态、所有者账号与编辑密码哈希；业务授权 =
  页面权限码（系统角色功能资格）∩ 逐本账号授权（ManualAuthorization）
  与所有者身份；tenant_id 仅作为数据模型约定保留，不参与任何归属、
  可见范围或编辑权判断。所有者自动拥有该手册范围内全部权限（查看/
  编辑/发布/授权/分工/密码，2026-10-31 第二轮），"制度管理员"权限码
  已废除，admin 概念收敛为平台超管。
- 新增制度文件（2026-11-02 简化）：上传文件直接建立该文件的当前草稿，
  不再额外保存原稿副本；每份上传文件各建一条 ManualFile 与一条草稿。
- 制度文件（ManualFile）是制度下 Word 文件的稳定条目：改名/排序/移除
  只影响待发布草稿集合，ID 永不复用、记录永不物理删除。
- 当前草稿（ManualDraft）按文件一条，编辑修订序号单调递增，
  用于阻止迟到回调、旧标签页或过期会话覆盖新内容。
- 发布版本（ManualVersion）不可变：版本保留制度级版本号，其文件快照
  （ManualVersionFile）完整记录该版有序文件清单，文件独立存储并记录
  SHA256，发布后绝不原地改写；version 上的旧单文件列保留为首个快照的
  兼容镜像（迁移不删旧数据）；废止只改变生效状态，不清除历史文件。
- 文件分工（2026-10-29 起）记录在制度文件（ManualFile）上：每份文件
  一名负责人与分工说明，负责人完成编制后可提交（记录草稿修订号，
  草稿再变更即失效）；旧章节分工（ManualChapter）为遗留只读数据，
  保留供人工核对，写入口已关闭。负责人必须持有该手册编制授权
  （can_edit）且仅负责人可编辑该文件（编辑密码只是附加验证）。
- 编辑会话（ManualEditSession）以文件为单位实现单写约束：同一文件
  同一时间仅一个可写会话，同一制度的不同文件可由不同账号并行编辑；
  支持密码重置、手册移交或授权撤销后的失效。
- 操作记录（ManualOperationLog）为手册维度时间线，操作人只到
  账号（科室共用账号不虚构个人身份）；另按全局规则调用
  record_audit_event 写模块审计。
"""
from django.db import models

from apps.account.models import User
from libs.tenant_base_model import (TenantModelManager, TenantModelMixin,
                                    make_tenant_id)


class ManualCategory(models.Model, TenantModelMixin):
    """手册类别字典（业务数据，页面维护，不硬编码）"""
    # mixin 上的 manager 会被 Django 自动补的默认 Manager 遮蔽，
    # 必须逐模型显式重声明（全库约定，见 libs/tenant_base_model.py）
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    name = models.CharField(max_length=100, unique=True, verbose_name='类别名称')
    sort_order = models.IntegerField(default=0, verbose_name='排序')
    is_active = models.BooleanField(default=True, db_index=True, verbose_name='启用')
    created_by = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='创建人',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'tdyw_institution_category'
        verbose_name = '手册类别'
        verbose_name_plural = '手册类别'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.name


class Manual(models.Model, TenantModelMixin):
    """手册主记录

    授权模型（2026-10-31 第二轮改造）：所有者（owner）自动拥有该手册
    范围内全部权限——查看正式版本和草稿、管理账号授权与文件分工、
    设置/重置编辑密码、编辑任意文件草稿、提交编制、发布/废止/回退，
    按对象范围生效且不要求持有页面权限码或逐本授权；所有者可把手册
    移交给任一启用账号，平台超管（is_supper）可接管，原所有者移交后
    不再因所有者身份保有权能。"制度管理员"页面权限码已废除，
    后端不再识别任何管理权限码。
    """
    objects = TenantModelManager()

    STATUS_ACTIVE = 'active'        # 启用
    STATUS_ARCHIVED = 'archived'    # 归档/停用
    STATUS_CHOICES = (
        (STATUS_ACTIVE, '启用'),
        (STATUS_ARCHIVED, '归档'),
    )

    OWNER_DEPARTMENT = 'department'  # 部门手册
    OWNER_SECTION = 'section'        # 科室手册
    OWNER_CHOICES = (
        (OWNER_DEPARTMENT, '部门'),
        (OWNER_SECTION, '科室'),
    )

    tenant_id = make_tenant_id()
    name = models.CharField(max_length=255, verbose_name='手册名称')
    code = models.CharField(max_length=100, blank=True, default='', verbose_name='手册编号')
    category = models.ForeignKey(
        ManualCategory, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='manuals', verbose_name='手册类别',
    )
    # 归属类型/归属单位是业务展示字段（部门/科室），与"所有者"无关；
    # 2026-10-31 由 owner_type/owner_name 更名，verbose_name 不变语义
    org_type = models.CharField(
        max_length=20, choices=OWNER_CHOICES,
        default=OWNER_DEPARTMENT, verbose_name='业务归属类型',
    )
    org_name = models.CharField(max_length=255, blank=True, default='', verbose_name='归属单位')
    # 所有者账号（2026-10-31）：自动拥有该手册范围内全部权限（查看/
    # 编辑/发布/授权/分工/密码），移交后失权；账号删除时置空不阻塞。
    owner = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='institution_owned_manuals', verbose_name='所有者账号')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE,
        db_index=True, verbose_name='状态',
    )
    # 编辑密码只存 Django 密码哈希器结果，接口与日志不回传；
    # 设置/重置仅限手册所有者或平台超管（2026-10-31 第二轮）。
    password_hash = models.CharField(max_length=128, blank=True, default='', verbose_name='编辑密码哈希')
    password_updated_at = models.DateTimeField(null=True, blank=True, verbose_name='密码更新时间')
    password_fail_count = models.PositiveIntegerField(default=0, verbose_name='密码连续失败次数')
    password_locked_until = models.DateTimeField(null=True, blank=True, verbose_name='密码锁定截止时间')

    current_version = models.ForeignKey(
        'ManualVersion', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='当前生效版本',
    )

    created_by = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name='+', verbose_name='创建人')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'tdyw_institution_manual'
        verbose_name = '制度手册'
        verbose_name_plural = '制度手册'
        ordering = ['category__sort_order', 'id']
        indexes = [
            models.Index(fields=['name'], name='inst_manual_name_idx'),
            models.Index(fields=['code'], name='inst_manual_code_idx'),
            models.Index(fields=['status'], name='inst_manual_status_idx'),
            models.Index(fields=['category', 'status'], name='inst_manual_cat_status_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(status__in=['active', 'archived']),
                name='inst_manual_status_valid',
            ),
            models.CheckConstraint(
                check=models.Q(org_type__in=['department', 'section']),
                name='inst_manual_org_type_valid',
            ),
        ]

    def __str__(self):
        return f'{self.code} {self.name}'.strip()


class ManualAuthorization(models.Model, TenantModelMixin):
    """逐本账号授权（2026-10-31，替代手册 M2M 角色关联）

    系统角色（页面权限码）只决定功能资格（查看/编制/发布等入口能否
    打开）；具体可操作哪本手册由本表的逐本授权决定：
    - can_view：可查看手册元数据与详情入口及发布版（工作区之外的信息）。
    - can_edit：编制资格——非所有者的内容写路径要求文件负责人
      （ManualFile.owner）独占，资格本身不等于可编辑任意文件；
      仅 can_edit 不带来发布版可见性。
    - can_publish：发布域操作（发布/废止/回退/预检/长期保留标记）。
    手册所有者（Manual.owner）不依赖本表自动拥有该手册范围内全部
    权限（2026-10-31 第二轮）；平台超管（is_supper）除可见性外不
    自动取得编辑/发布等对象级权能；原"制度管理员"页面权限码已废除，
    后端不再识别。全 False 的行由服务层落为
    删除，不保留空授权行。管理操作见
    authorization_services.replace_manual_authorizations 与
    views_authorization。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    manual = models.ForeignKey(
        Manual, on_delete=models.CASCADE, related_name='account_grants',
        verbose_name='所属手册')
    account = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='institution_manual_grants',
        verbose_name='授权账号')
    can_view = models.BooleanField(default=False, verbose_name='可查看')
    can_edit = models.BooleanField(default=False, verbose_name='可编制')
    can_publish = models.BooleanField(default=False, verbose_name='可发布')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    updated_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='更新操作人')

    class Meta:
        db_table = 'tdyw_institution_authorization'
        verbose_name = '手册账号授权'
        verbose_name_plural = '手册账号授权'
        ordering = ['account_id']
        constraints = [
            models.UniqueConstraint(
                fields=['manual', 'account'], name='inst_auth_manual_account'),
        ]
        indexes = [
            models.Index(fields=['account'], name='inst_auth_account_idx'),
        ]

    def __str__(self):
        return f'{self.manual_id}:{self.account_id}'


class ManualFile(models.Model, TenantModelMixin):
    """制度文件条目（一项制度下一份或多份 Word 文件的稳定清单项）

    - ID 稳定且永不复用：改名、排序、移除都只影响待发布发布集合，
      不改动历史版本引用；记录永不物理删除（手册级联删除除外）。
    - display_name 为用户可维护的显示名（发布快照沿用发布时点的值，
      历史快照名称不可变）。
    - is_removed=True 表示已从待发布清单移除：仅退出下一版候选集合，
      原稿、历史快照与 ID 全部保留（整版回退可重新纳入）。
    - 文件分工（2026-10-29，替代旧章节分工）：分工单位是整份文件，
      每份文件至多一名负责人与一段分工说明，字段就在本条目上——
      结构上不可能出现同一文件多条互相冲突的"当前分工"。被指派
      负责人必须持有该手册 can_edit 编制授权；此后仅负责人可编辑
      该文件（2026-10-31 负责人独占，编辑密码只是附加验证）。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    manual = models.ForeignKey(
        Manual, on_delete=models.CASCADE, related_name='files', verbose_name='所属手册')
    display_name = models.CharField(max_length=255, verbose_name='文件显示名')
    sort_order = models.IntegerField(default=0, verbose_name='排序')
    is_removed = models.BooleanField(default=False, db_index=True, verbose_name='已移除')
    removed_at = models.DateTimeField(null=True, blank=True, verbose_name='移除时间')
    # ---- 修订状态（2026-10-30）----
    # "本轮修订进行中"是显式持久状态，绝不凭文件哈希相等推断"修订已结束"：
    # - True：初始编制或某轮修订进行中（新文件默认 True；「开始修订」、任何
    #   草稿内容变更（保存/恢复/回退/重建）都会置 True；废止当前版本后全部
    #   置 True——生效集合已不存在，工作内容即待发布内容）。
    # - False：仅整套发布成功时对本次发布清单内文件置 False（修订轮结束），
    #   发布失败不改任何状态；工作副本（草稿）不因发布删除，只是不再以
    #   "有未发布草稿"的名义展示。
    # 注意：修订进行中 ≠ 有待发布变化。是否有内容/结构变化仍由
    # version_compare 按草稿哈希与生效快照（含改名/移除/排序）计算。
    revision_open = models.BooleanField(default=True, verbose_name='修订进行中')
    # ---- 文件分工（2026-10-29，替代旧章节分工 ManualChapter）----
    # 每份文件至多一名负责人：owner 为空即"未分配"；owner_name 为账号名
    # 快照（账号删除后仍可读）。被指派账号必须持有该手册 can_edit 编制
    # 授权（2026-10-31 起）；负责人独占编辑该文件，改派/撤权撤销在途会话。
    owner = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='文件负责人')
    owner_name = models.CharField(
        max_length=100, blank=True, default='', verbose_name='负责人账号名')
    assign_note = models.CharField(
        max_length=500, blank=True, default='', verbose_name='分工说明')
    assigned_at = models.DateTimeField(null=True, blank=True, verbose_name='最近分工时间')
    assigned_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='最近分工操作人')
    # 提交编制：负责人完成编制后的交接标记，记录提交时点的草稿修订号。
    # 提交状态按 submission_revision == 当前草稿 revision 计算判定——草稿
    # 再次保存、重建、回退或恢复都会推进 revision，提交状态随之自动失效，
    # 不依赖任何写路径记得"清除提交"（计算式失效，杜绝遗漏）。
    submission_revision = models.PositiveIntegerField(
        null=True, blank=True, verbose_name='提交时修订号')
    submitted_at = models.DateTimeField(
        null=True, blank=True, verbose_name='提交编制时间')
    submitted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='提交编制人')
    created_by = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name='+', verbose_name='创建人')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'tdyw_institution_file'
        verbose_name = '制度文件'
        verbose_name_plural = '制度文件'
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['manual', 'sort_order'], name='inst_file_manual_idx'),
        ]

    def __str__(self):
        return f'{self.manual_id}:{self.display_name}'


class ManualDraft(models.Model, TenantModelMixin):
    """当前草稿（每份制度文件至多一条工作文件记录，文件级单写会话）"""
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    # 冗余归属（file 已定所属制度）：普通外键——同一制度可有多份文件，
    # 每份各一条草稿；单写等业务约束以 file 为准
    manual = models.ForeignKey(
        Manual, on_delete=models.CASCADE, related_name='+', verbose_name='所属手册')
    file = models.OneToOneField(
        ManualFile, on_delete=models.CASCADE, related_name='draft', verbose_name='所属制度文件')
    file_path = models.CharField(max_length=500, blank=True, default='', verbose_name='相对存储路径')
    original_name = models.CharField(max_length=255, blank=True, default='', verbose_name='工作文件名')
    file_size = models.BigIntegerField(default=0, verbose_name='文件大小')
    file_hash = models.CharField(max_length=64, blank=True, default='', verbose_name='SHA256')
    # 编辑修订序号：每次保存/重建 +1，单调递增，用于拒绝迟到回调与旧会话覆盖
    revision = models.PositiveIntegerField(default=0, verbose_name='编辑修订序号')
    base_version = models.ForeignKey(
        'ManualVersion', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='基于发布版本')
    last_saved_by = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name='+', verbose_name='最后保存人')
    last_saved_at = models.DateTimeField(null=True, blank=True, verbose_name='最后保存时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'tdyw_institution_draft'
        verbose_name = '手册草稿'
        verbose_name_plural = '手册草稿'


class ManualVersion(models.Model, TenantModelMixin):
    """发布版本（制度级版本号；文件内容经 ManualVersionFile 快照承载）

    file_path/original_name/file_size/file_hash 是历史单文件模型的兼容
    镜像列：迁移时保存该版唯一文件快照的值，新发布时保存首个文件快照
    （清单首位）的值，供过渡期旧接口委托；权威数据以 ManualVersionFile
    为准，两处都在发布时一次写入、绝不改写。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    manual = models.ForeignKey(
        Manual, on_delete=models.CASCADE, related_name='versions', verbose_name='所属手册')
    version_no = models.PositiveIntegerField(verbose_name='版本号')
    file_path = models.CharField(max_length=500, verbose_name='相对存储路径')
    original_name = models.CharField(max_length=255, blank=True, default='', verbose_name='文件名')
    file_size = models.BigIntegerField(default=0, verbose_name='文件大小')
    file_hash = models.CharField(max_length=64, blank=True, default='', verbose_name='SHA256')
    change_note = models.TextField(default='', verbose_name='变更说明')
    published_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='+', verbose_name='发布人')
    published_at = models.DateTimeField(auto_now_add=True, verbose_name='发布时间')
    is_effective = models.BooleanField(default=True, verbose_name='是否生效')
    # ---- 发布版本保留策略（2026-10-29）----
    # 当前生效版本（manual.current_version 指向者）及整套文件永久受保护；
    # is_effective=False 仅表示不是当前生效版，不作为可清理依据。
    # 重要版本可设长期保留标记；历史版本按配置期限/数量保留，超过期限、
    # 未受保护且没有业务引用（无草稿以其为 base_version）才成为清理候选。
    long_term_protected = models.BooleanField(
        default=False, verbose_name='长期保留')
    # 整版文件清理状态：任一快照文件被清理即置 files_cleaned_at（整版标记
    # 为"不可完整使用"，关闭整套回退）；files_clean_status='' 未清理/
    # 'partial' 部分清理失败可重试/'cleaned' 整版文件已清理；失败说明存
    # files_clean_error，允许重试，不得伪装成功。版本号、发布人/时间、
    # 变更说明与 ManualVersionFile 快照行（含哈希）永久保留。
    files_cleaned_at = models.DateTimeField(
        null=True, blank=True, verbose_name='整版文件清理时间')
    FILES_CLEAN_UNTOUCHED = ''
    FILES_CLEAN_PARTIAL = 'partial'
    FILES_CLEAN_CLEANED = 'cleaned'
    files_clean_status = models.CharField(
        max_length=20, blank=True, default=FILES_CLEAN_UNTOUCHED,
        verbose_name='整版文件清理状态')
    files_clean_error = models.TextField(
        blank=True, default='', verbose_name='整版文件清理失败说明')

    class Meta:
        db_table = 'tdyw_institution_version'
        verbose_name = '手册发布版本'
        verbose_name_plural = '手册发布版本'
        ordering = ['-version_no']
        unique_together = (('manual', 'version_no'),)
        indexes = [
            models.Index(fields=['manual', 'version_no'], name='inst_ver_manual_no_idx'),
        ]

    def __str__(self):
        return f'{self.manual_id}-v{self.version_no}'


class ManualVersionFile(models.Model, TenantModelMixin):
    """发布版本的文件快照（每版完整、有序、不可变的文件清单）

    - 发布时逐份复制草稿内容到 versions/ 独立存储并记录 SHA256，
      全部快照成功后才切换当前版本；发布后名称/顺序/路径/哈希不改写。
    - manual_file 指向稳定文件条目（PROTECT：文件条目永不物理删除），
      历史快照因此始终可追溯到"哪个文件条目"。
    - 整套回退以某版快照清单重建待发布草稿，不影响任何历史快照。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    version = models.ForeignKey(
        ManualVersion, on_delete=models.CASCADE, related_name='files', verbose_name='所属版本')
    manual_file = models.ForeignKey(
        ManualFile, on_delete=models.PROTECT, related_name='version_snapshots',
        verbose_name='制度文件条目')
    display_name = models.CharField(max_length=255, verbose_name='文件显示名')
    sort_order = models.IntegerField(default=0, verbose_name='排序')
    file_path = models.CharField(max_length=500, verbose_name='相对存储路径')
    file_size = models.BigIntegerField(default=0, verbose_name='文件大小')
    file_hash = models.CharField(max_length=64, blank=True, default='', verbose_name='SHA256')
    # 该快照物理文件被保留策略清理的时间；快照行（清单/名称/哈希）永久
    # 保留，cleaned_at 非空后不再提供该文件的预览/下载。部分快照清理失败
    # 时整版标为 partial 可重试，绝不删除快照行。
    cleaned_at = models.DateTimeField(null=True, blank=True, verbose_name='快照清理时间')

    class Meta:
        db_table = 'tdyw_institution_version_file'
        verbose_name = '版本文件快照'
        verbose_name_plural = '版本文件快照'
        ordering = ['sort_order', 'id']
        unique_together = (('version', 'manual_file'),)
        indexes = [
            models.Index(fields=['version', 'sort_order'], name='inst_vfile_ver_idx'),
        ]

    def __str__(self):
        return f'v{self.version_id}:{self.display_name}'


class ManualSubmission(models.Model, TenantModelMixin):
    """提交待发布核对（固定快照，2026-11-03）

    发布交接从"只记录草稿修订号"升级为"独立不可变文件副本"：有效负责人
    提交时把当前草稿复制到 submissions/ 独立存储并记录 SHA256，此后该
    文件内容写路径全部冻结，发布人预览/下载/最终发布都读取同一快照。
    记录只改状态、不覆盖：撤回/退回后旧快照不可再用于发布，重新提交产生
    新行；旧行（含操作人/时间/原因）永久保留可追溯。
    旧 ManualFile.submission_revision/submitted_at/submitted_by 列保留为
    历史流程数据，新流程不读取、不写入（见 AGENTS 2026-11-03 节）。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()

    STATUS_PENDING = 'pending'        # 待发布人核对（发布可用）
    STATUS_WITHDRAWN = 'withdrawn'    # 负责人撤回
    STATUS_RETURNED = 'returned'      # 发布人退回修改
    STATUS_PUBLISHED = 'published'    # 已随整套发布消费
    STATUS_CHOICES = (
        (STATUS_PENDING, '待发布人核对'),
        (STATUS_WITHDRAWN, '已撤回'),
        (STATUS_RETURNED, '已退回修改'),
        (STATUS_PUBLISHED, '已随版本发布'),
    )

    manual = models.ForeignKey(
        Manual, on_delete=models.CASCADE, related_name='submissions',
        verbose_name='所属手册')
    file = models.ForeignKey(
        ManualFile, on_delete=models.CASCADE, related_name='submissions',
        verbose_name='所属制度文件')
    # 提交时的草稿修订号：发布时据此证明"发布读到的是提交时固定内容"
    draft_revision = models.PositiveIntegerField(verbose_name='提交时修订序号')
    # 独立快照相对路径（submissions/，与 drafts/versions/ 生命周期隔离）
    file_path = models.CharField(max_length=500, verbose_name='快照相对存储路径')
    original_name = models.CharField(
        max_length=255, blank=True, default='', verbose_name='快照显示文件名')
    file_size = models.BigIntegerField(default=0, verbose_name='快照大小')
    file_hash = models.CharField(
        max_length=64, blank=True, default='', verbose_name='快照SHA256')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING,
        verbose_name='提交状态')

    submitted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='提交人账号')
    submitted_by_name = models.CharField(
        max_length=100, blank=True, default='', verbose_name='提交人账号名')
    submitted_at = models.DateTimeField(verbose_name='提交时间')

    withdrawn_at = models.DateTimeField(
        null=True, blank=True, verbose_name='撤回时间')
    withdrawn_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='撤回人账号')
    withdrawn_by_name = models.CharField(
        max_length=100, blank=True, default='', verbose_name='撤回人账号名')

    returned_at = models.DateTimeField(
        null=True, blank=True, verbose_name='退回时间')
    returned_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='退回人账号')
    returned_by_name = models.CharField(
        max_length=100, blank=True, default='', verbose_name='退回人账号名')
    return_reason = models.CharField(
        max_length=500, blank=True, default='', verbose_name='退回原因')

    published_version = models.ForeignKey(
        ManualVersion, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='随发布版本')
    consumed_at = models.DateTimeField(
        null=True, blank=True, verbose_name='随发布消费时间')
    # 快照物理文件清理时间：记录（含哈希/提交人/时间）永久保留可追溯，
    # 清理只针对已撤回/已退回/已发布的物理副本，不影响草稿与发布快照
    cleaned_at = models.DateTimeField(
        null=True, blank=True, verbose_name='快照物理文件清理时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        db_table = 'tdyw_institution_submission'
        verbose_name = '提交待发布核对快照'
        verbose_name_plural = '提交待发布核对快照'
        ordering = ['-id']
        indexes = [
            models.Index(fields=['file', 'status'], name='inst_sub_file_idx'),
            models.Index(fields=['manual', 'status'], name='inst_sub_manual_idx'),
        ]

    def __str__(self):
        return f'{self.manual_id}:{self.file_id}:{self.status}'


class ManualEditSession(models.Model, TenantModelMixin):
    """编辑会话（绑定制度文件、账号、草稿修订与有效期，文件级单写约束）

    manual 冗余保留用于制度级批量失效（密码重置/整套回退）与查询；
    单写判断以 (file, 活跃未过期) 为准——同一制度不同文件可并行各持
    一个会话，同一文件同时仅一个。
    """
    objects = TenantModelManager()
    tenant_id = make_tenant_id()
    manual = models.ForeignKey(
        Manual, on_delete=models.CASCADE, related_name='edit_sessions', verbose_name='所属手册')
    file = models.ForeignKey(
        ManualFile, on_delete=models.CASCADE, related_name='edit_sessions',
        verbose_name='编辑的制度文件')
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='institution_edit_sessions', verbose_name='会话账号')
    session_key = models.CharField(max_length=64, unique=True, verbose_name='会话标识')
    revision_at_start = models.PositiveIntegerField(default=0, verbose_name='开启时修订序号')
    started_at = models.DateTimeField(auto_now_add=True, verbose_name='开启时间')
    last_active_at = models.DateTimeField(null=True, blank=True, verbose_name='最后活跃时间')
    expires_at = models.DateTimeField(db_index=True, verbose_name='过期时间')
    revoked_at = models.DateTimeField(null=True, blank=True, verbose_name='失效时间')
    revoked_reason = models.CharField(max_length=255, blank=True, default='', verbose_name='失效原因')
    # 当前签发的 ONLYOFFICE document.key：回调 key 与其不一致即迟到/旧编辑
    # 实例回调，拒绝保存（防旧内容覆盖；多标签重新取配置即换 key）
    current_doc_key = models.CharField(
        max_length=64, blank=True, default='', verbose_name='当前编辑文档键')
    # 撤销时是否声明保留收尾回调（仅撤销端点 discard=false 显式置位，
    # 即"保存并结束编辑"确认成功后的撤销）：True 时本会话（同一
    # current_doc_key）的收尾 status-2/6 回调在撤销后仍允许按防线落盘
    # （editor_services._resolve_final_callback_session）；密码重置/
    # 整套回退/草稿恢复等批量失效不置位，收尾回调照旧拒绝。
    final_callback_allowed = models.BooleanField(
        default=False, verbose_name='撤销后保留收尾回调')

    class Meta:
        db_table = 'tdyw_institution_edit_session'
        verbose_name = '手册编辑会话'
        verbose_name_plural = '手册编辑会话'
        indexes = [
            models.Index(fields=['manual', 'revoked_at'], name='inst_sess_manual_idx'),
        ]


class ManualChapter(models.Model, TenantModelMixin):
    """旧章节分工（2026-10-29 起为遗留只读数据）

    分工单位已改为整份制度文件（见 ManualFile 的 owner/assign_note 与
    提交编制字段）。本表只保留历史记录供人工核对——旧记录只关联制度、
    无法按章节名称猜测所属文件，在人工核对完成前绝不删除或改写；
    写接口（新增/编辑/删除/进度）已全部关闭并返回明确业务错误。
    """
    objects = TenantModelManager()

    PROGRESS_PENDING = 'pending'          # 待编制
    PROGRESS_IN_PROGRESS = 'in_progress'  # 编制中
    PROGRESS_SUBMITTED = 'submitted'      # 已提交
    PROGRESS_CHOICES = (
        (PROGRESS_PENDING, '待编制'),
        (PROGRESS_IN_PROGRESS, '编制中'),
        (PROGRESS_SUBMITTED, '已提交'),
    )

    tenant_id = make_tenant_id()
    manual = models.ForeignKey(
        Manual, on_delete=models.CASCADE, related_name='chapters', verbose_name='所属手册')
    title = models.CharField(max_length=255, verbose_name='章节或部分名称')
    owner = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='负责人账号')
    owner_name = models.CharField(max_length=100, blank=True, default='', verbose_name='负责人账号名')
    note = models.CharField(max_length=500, blank=True, default='', verbose_name='参与说明')
    progress = models.CharField(
        max_length=20, choices=PROGRESS_CHOICES, default=PROGRESS_PENDING,
        verbose_name='进度')
    sort_order = models.IntegerField(default=0, verbose_name='排序')
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name='提交时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'tdyw_institution_chapter'
        verbose_name = '章节分工'
        verbose_name_plural = '章节分工'
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['manual', 'sort_order'], name='inst_chap_manual_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(progress__in=['pending', 'in_progress', 'submitted']),
                name='inst_chap_progress_valid',
            ),
        ]


class ManualOperationLog(models.Model, TenantModelMixin):
    """手册操作记录（手册维度时间线；操作人只到账号）"""
    objects = TenantModelManager()

    # 动作常量：create/create_draft/save_draft/publish/deprecate/rollback/
    # password_reset/config_change/download/chapter_update/delete
    # 历史记录可能含已下线的 upload_original（原稿体系移除前写入），仅作
    # 只读展示，不再产生该动作。
    tenant_id = make_tenant_id()
    manual = models.ForeignKey(
        Manual, on_delete=models.CASCADE, related_name='operation_logs', verbose_name='所属手册')
    user = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name='+', verbose_name='操作账号')
    user_name = models.CharField(max_length=100, blank=True, default='', verbose_name='操作账号名')
    # 涉及具体文件的动作（保存/增删/改名/排序）记录文件条目；制度级
    # 动作（创建/发布/回退）可为空。detail JSON 同时冗余 file_id/revision。
    file = models.ForeignKey(
        ManualFile, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='涉及制度文件')
    action = models.CharField(max_length=50, verbose_name='动作')
    version = models.ForeignKey(
        ManualVersion, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='关联版本')
    detail = models.TextField(blank=True, default='', verbose_name='详情JSON')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='操作时间')

    class Meta:
        db_table = 'tdyw_institution_operation_log'
        verbose_name = '手册操作记录'
        verbose_name_plural = '手册操作记录'
        ordering = ['-id']
        indexes = [
            models.Index(fields=['manual', 'created_at'], name='inst_oplog_manual_idx'),
        ]
