tdywuser@LAPTOP-VKNVF9F3:/mnt/e/TDYW/spug-3.0$ docker exec -i tdyw python - \
  < database_maintenance/collect_db_baseline.py
INFO [DocumentConfig] Document app ready
INFO [DocumentConfig] Registered 2 Celery Beat tasks
[Celery] Document tasks imported successfully
[Celery] RadioLicense tasks imported successfully
[Celery] Home tasks imported successfully
========================================================================
  数据库基线采集报告
  采集时间: 2026-07-23 19:18:42
========================================================================

========================================================================
  1. 镜像与 digest（需在宿主机执行以下命令并归档到本报告）
========================================================================
  # 数据库容器镜像 ID
  docker inspect --format='{{.Image}}' tdyw-db
  # 数据库容器镜像 repo digest（若有）
  docker inspect --format='{{json .RepoDigests}}' tdyw-db
  # 应用容器镜像 ID / digest
  docker inspect --format='{{.Image}}' tdyw
  docker inspect --format='{{json .RepoDigests}}' tdyw

========================================================================
  2. 数据库版本
========================================================================
  VERSION()                                : 10.8.2-MariaDB-1:10.8.2+maria~focal-log
  version_comment                          : mariadb.org binary distribution

========================================================================
  3. 持久性与复制相关运行参数
========================================================================
  innodb_flush_log_at_trx_commit           : 1
  sync_binlog                              : 1
  log_bin                                  : ON
  binlog_format                            : ROW
  binlog_expire_logs_seconds               : 604800
  innodb_doublewrite                       : ON
  server_id                                : 1
  gtid_strict_mode                         : OFF
  log_slave_updates                        : OFF
  read_only                                : OFF
  default_storage_engine                   : InnoDB
  innodb_buffer_pool_size                  : 2147483648
  max_connections                          : 300
  character_set_server                     : utf8mb4
  sql_mode                                 : STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION

========================================================================
  4. 表引擎分布
========================================================================
  引擎 InnoDB                                : 72 张表
  (全部业务表均为 InnoDB)

========================================================================
  5. 数据/索引大小
========================================================================
  表数量                                      : 72
  数据总大小                                    : 1.23 MB (1294336 bytes)
  索引总大小                                    : 3.69 MB (3866624 bytes)
  合计                                       : 4.92 MB (5160960 bytes)
  --- Top 10 大表（按 数据+索引） ---
  tdyw_document_transfer                   : 数据 16.00 KB / 索引 224.00 KB / 合计 240.00 KB
  audit_logs                               : 数据 80.00 KB / 索引 144.00 KB / 合计 224.00 KB
  django_celery_results_taskresult         : 数据 16.00 KB / 索引 192.00 KB / 合计 208.00 KB
  tdyw_regulation                          : 数据 16.00 KB / 索引 176.00 KB / 合计 192.00 KB
  tdyw_department_duty_log                 : 数据 16.00 KB / 索引 144.00 KB / 合计 160.00 KB
  tdyw_upgrade_records                     : 数据 16.00 KB / 索引 112.00 KB / 合计 128.00 KB
  tdyw_contract_agreement                  : 数据 16.00 KB / 索引 112.00 KB / 合计 128.00 KB
  tdyw_station_frequency_approval          : 数据 16.00 KB / 索引 96.00 KB / 合计 112.00 KB
  tdyw_document_folder_private             : 数据 16.00 KB / 索引 80.00 KB / 合计 96.00 KB
  tdyw_evidence_events                     : 数据 16.00 KB / 索引 80.00 KB / 合计 96.00 KB

========================================================================
  6. Migration 状态
========================================================================
  已应用迁移数                                   : 165
  叶子节点数                                    : 23
  --- 叶子节点（migration 最新版本） ---
  account                                  : 0009_alter_history_created_at_alter_role_created_at_and_more
  auth                                     : 0012_alter_user_first_name_max_length
  checksheet                               : 0004_alter_checksheetdailysummary_id_and_more
  contenttypes                             : 0002_remove_content_type_name
  contract_agreement                       : 0004_alter_contractagreement_created_at_and_more
  department_duty_log                      : 0004_alter_departmentdutylog_created_at_and_more
  device                                   : 0008_alter_deviceevent_corrected_at_and_more
  django_celery_beat                       : 0019_alter_periodictasks_options
  django_celery_results                    : 0011_taskresult_periodic_task_name
  document                                 : 0014_alter_documentfileprivate_id_and_more
  duty                                     : 0004_alter_dutyrecord_created_at_and_more
  evidence                                 : 0004_alter_evidenceattachment_deleted_at_and_more
  fault                                    : 0004_alter_faultpart_archive_date_and_more
  home                                     : 0004_alter_announcement_created_at_and_more
  interference                             : 0005_alter_interference_closed_at_and_more
  logs                                     : 0007_alter_auditlog_id
  radio_license                            : 0012_alter_licensereminderack_created_at_and_more
  regulation                               : 0004_alter_regulation_updated_at_and_more
  runlog                                   : 0010_alter_eventtypeconfig_id_alter_runlog_id_and_more
  sessions                                 : 0001_initial
  setting                                  : 0002_alter_setting_id_alter_usersetting_id
  signature                                : 0004_alter_accountsignature_assigned_at_and_more
  upgrade                                  : 0016_alter_upgradeplanstep_created_at_and_more
  (无未应用迁移，迁移状态为最新)

========================================================================
  7. 账号授权摘要（不含密码）
========================================================================
  数据库账号共 3 个：
  mariadb.sys                              : @localhost
  root                                     : @%
  root                                     : @localhost
  --- 全局权限 (information_schema.USER_PRIVILEGES) ---
  'mariadb.sys'@'localhost'                : USAGE (GRANT: NO)
  'root'@'%'                               : ALTER (GRANT: YES)
  'root'@'%'                               : ALTER ROUTINE (GRANT: YES)
  'root'@'%'                               : BINLOG ADMIN (GRANT: YES)
  'root'@'%'                               : BINLOG MONITOR (GRANT: YES)
  'root'@'%'                               : BINLOG REPLAY (GRANT: YES)
  'root'@'%'                               : CONNECTION ADMIN (GRANT: YES)
  'root'@'%'                               : CREATE (GRANT: YES)
  'root'@'%'                               : CREATE ROUTINE (GRANT: YES)
  'root'@'%'                               : CREATE TABLESPACE (GRANT: YES)
  'root'@'%'                               : CREATE TEMPORARY TABLES (GRANT: YES)
  'root'@'%'                               : CREATE USER (GRANT: YES)
  'root'@'%'                               : CREATE VIEW (GRANT: YES)
  'root'@'%'                               : DELETE (GRANT: YES)
  'root'@'%'                               : DELETE HISTORY (GRANT: YES)
  'root'@'%'                               : DROP (GRANT: YES)
  'root'@'%'                               : EVENT (GRANT: YES)
  'root'@'%'                               : EXECUTE (GRANT: YES)
  'root'@'%'                               : FEDERATED ADMIN (GRANT: YES)
  'root'@'%'                               : FILE (GRANT: YES)
  'root'@'%'                               : INDEX (GRANT: YES)
  'root'@'%'                               : INSERT (GRANT: YES)
  'root'@'%'                               : LOCK TABLES (GRANT: YES)
  'root'@'%'                               : PROCESS (GRANT: YES)
  'root'@'%'                               : READ_ONLY ADMIN (GRANT: YES)
  'root'@'%'                               : REFERENCES (GRANT: YES)
  'root'@'%'                               : RELOAD (GRANT: YES)
  'root'@'%'                               : REPLICATION MASTER ADMIN (GRANT: YES)
  'root'@'%'                               : REPLICATION SLAVE (GRANT: YES)
  'root'@'%'                               : REPLICATION SLAVE ADMIN (GRANT: YES)
  'root'@'%'                               : SELECT (GRANT: YES)
  'root'@'%'                               : SET USER (GRANT: YES)
  'root'@'%'                               : SHOW DATABASES (GRANT: YES)
  'root'@'%'                               : SHOW VIEW (GRANT: YES)
  'root'@'%'                               : SHUTDOWN (GRANT: YES)
  'root'@'%'                               : SLAVE MONITOR (GRANT: YES)
  'root'@'%'                               : SUPER (GRANT: YES)
  'root'@'%'                               : TRIGGER (GRANT: YES)
  'root'@'%'                               : UPDATE (GRANT: YES)
  'root'@'localhost'                       : ALTER (GRANT: YES)
  'root'@'localhost'                       : ALTER ROUTINE (GRANT: YES)
  'root'@'localhost'                       : BINLOG ADMIN (GRANT: YES)
  'root'@'localhost'                       : BINLOG MONITOR (GRANT: YES)
  'root'@'localhost'                       : BINLOG REPLAY (GRANT: YES)
  'root'@'localhost'                       : CONNECTION ADMIN (GRANT: YES)
  'root'@'localhost'                       : CREATE (GRANT: YES)
  'root'@'localhost'                       : CREATE ROUTINE (GRANT: YES)
  'root'@'localhost'                       : CREATE TABLESPACE (GRANT: YES)
  'root'@'localhost'                       : CREATE TEMPORARY TABLES (GRANT: YES)
  'root'@'localhost'                       : CREATE USER (GRANT: YES)
  'root'@'localhost'                       : CREATE VIEW (GRANT: YES)
  'root'@'localhost'                       : DELETE (GRANT: YES)
  'root'@'localhost'                       : DELETE HISTORY (GRANT: YES)
  'root'@'localhost'                       : DROP (GRANT: YES)
  'root'@'localhost'                       : EVENT (GRANT: YES)
  'root'@'localhost'                       : EXECUTE (GRANT: YES)
  'root'@'localhost'                       : FEDERATED ADMIN (GRANT: YES)
  'root'@'localhost'                       : FILE (GRANT: YES)
  'root'@'localhost'                       : INDEX (GRANT: YES)
  'root'@'localhost'                       : INSERT (GRANT: YES)
  'root'@'localhost'                       : LOCK TABLES (GRANT: YES)
  'root'@'localhost'                       : PROCESS (GRANT: YES)
  'root'@'localhost'                       : READ_ONLY ADMIN (GRANT: YES)
  'root'@'localhost'                       : REFERENCES (GRANT: YES)
  'root'@'localhost'                       : RELOAD (GRANT: YES)
  'root'@'localhost'                       : REPLICATION MASTER ADMIN (GRANT: YES)
  'root'@'localhost'                       : REPLICATION SLAVE (GRANT: YES)
  'root'@'localhost'                       : REPLICATION SLAVE ADMIN (GRANT: YES)
  'root'@'localhost'                       : SELECT (GRANT: YES)
  'root'@'localhost'                       : SET USER (GRANT: YES)
  'root'@'localhost'                       : SHOW DATABASES (GRANT: YES)
  'root'@'localhost'                       : SHOW VIEW (GRANT: YES)
  'root'@'localhost'                       : SHUTDOWN (GRANT: YES)
  'root'@'localhost'                       : SLAVE MONITOR (GRANT: YES)
  'root'@'localhost'                       : SUPER (GRANT: YES)
  'root'@'localhost'                       : TRIGGER (GRANT: YES)
  'root'@'localhost'                       : UPDATE (GRANT: YES)
  --- 目标库 tdyw 的 SCHEMA 权限 ---
  (无该库的 schema 权限记录)
  应用连接账号                                   : root

========================================================================
  采集完成，全部成功。请将本输出归档到备份目录。
========================================================================