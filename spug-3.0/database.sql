-- MariaDB dump 10.19  Distrib 10.8.2-MariaDB, for debian-linux-gnu (x86_64)
--
-- Host: 127.0.0.1    Database: tdyw
-- ------------------------------------------------------
-- Server version	10.8.2-MariaDB-1:10.8.2+maria~focal-log

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `audit_logs`
--

DROP TABLE IF EXISTS `audit_logs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `audit_logs` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `username` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `action` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `target_type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `target_id` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `target_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `detail` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `ip` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_success` tinyint(1) NOT NULL,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `request_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `response_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `prev_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `log_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `request_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `user_agent` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `audit_tenant_id_idx` (`tenant_id`,`id` DESC),
  KEY `audit_tenant_time_idx` (`tenant_id`,`created_at`),
  KEY `audit_action_idx` (`action`),
  KEY `audit_target_type_idx` (`target_type`),
  KEY `audit_username_idx` (`username`),
  KEY `audit_logs_request_hash_66b25bcf` (`request_hash`),
  KEY `audit_logs_log_hash_8e3bd5f8` (`log_hash`),
  KEY `audit_logs_request_id_441a87fc` (`request_id`),
  KEY `audit_tenant_ctime_id_idx` (`tenant_id`,`created_at` DESC,`id` DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `audit_logs`
--

LOCK TABLES `audit_logs` WRITE;
/*!40000 ALTER TABLE `audit_logs` DISABLE KEYS */;
/*!40000 ALTER TABLE `audit_logs` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `auth_group`
--

DROP TABLE IF EXISTS `auth_group`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `auth_group` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(150) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `auth_group`
--

LOCK TABLES `auth_group` WRITE;
/*!40000 ALTER TABLE `auth_group` DISABLE KEYS */;
/*!40000 ALTER TABLE `auth_group` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `auth_group_permissions`
--

DROP TABLE IF EXISTS `auth_group_permissions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `auth_group_permissions` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `group_id` int(11) NOT NULL,
  `permission_id` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_group_permissions_group_id_permission_id_0cd325b0_uniq` (`group_id`,`permission_id`),
  KEY `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` (`permission_id`),
  CONSTRAINT `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`),
  CONSTRAINT `auth_group_permissions_group_id_b120cbf9_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `auth_group_permissions`
--

LOCK TABLES `auth_group_permissions` WRITE;
/*!40000 ALTER TABLE `auth_group_permissions` DISABLE KEYS */;
/*!40000 ALTER TABLE `auth_group_permissions` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `auth_permission`
--

DROP TABLE IF EXISTS `auth_permission`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `auth_permission` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `content_type_id` int(11) NOT NULL,
  `codename` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_permission_content_type_id_codename_01ab375a_uniq` (`content_type_id`,`codename`),
  CONSTRAINT `auth_permission_content_type_id_2f476e4b_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=269 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `auth_permission`
--

LOCK TABLES `auth_permission` WRITE;
/*!40000 ALTER TABLE `auth_permission` DISABLE KEYS */;
INSERT INTO `auth_permission` VALUES
(1,'Can add permission',1,'add_permission'),
(2,'Can change permission',1,'change_permission'),
(3,'Can delete permission',1,'delete_permission'),
(4,'Can view permission',1,'view_permission'),
(5,'Can add group',2,'add_group'),
(6,'Can change group',2,'change_group'),
(7,'Can delete group',2,'delete_group'),
(8,'Can view group',2,'view_group'),
(9,'Can add user',3,'add_user'),
(10,'Can change user',3,'change_user'),
(11,'Can delete user',3,'delete_user'),
(12,'Can view user',3,'view_user'),
(13,'Can add content type',4,'add_contenttype'),
(14,'Can change content type',4,'change_contenttype'),
(15,'Can delete content type',4,'delete_contenttype'),
(16,'Can view content type',4,'view_contenttype'),
(17,'Can add session',5,'add_session'),
(18,'Can change session',5,'change_session'),
(19,'Can delete session',5,'delete_session'),
(20,'Can view session',5,'view_session'),
(21,'Can add history',6,'add_history'),
(22,'Can change history',6,'change_history'),
(23,'Can delete history',6,'delete_history'),
(24,'Can view history',6,'view_history'),
(25,'Can add role',7,'add_role'),
(26,'Can change role',7,'change_role'),
(27,'Can delete role',7,'delete_role'),
(28,'Can view role',7,'view_role'),
(29,'Can add user',8,'add_user'),
(30,'Can change user',8,'change_user'),
(31,'Can delete user',8,'delete_user'),
(32,'Can view user',8,'view_user'),
(33,'Can add 租户',9,'add_tenant'),
(34,'Can change 租户',9,'change_tenant'),
(35,'Can delete 租户',9,'delete_tenant'),
(36,'Can view 租户',9,'view_tenant'),
(37,'Can add setting',10,'add_setting'),
(38,'Can change setting',10,'change_setting'),
(39,'Can delete setting',10,'delete_setting'),
(40,'Can view setting',10,'view_setting'),
(41,'Can add user setting',11,'add_usersetting'),
(42,'Can change user setting',11,'change_usersetting'),
(43,'Can delete user setting',11,'delete_usersetting'),
(44,'Can view user setting',11,'view_usersetting'),
(45,'Can add 故障处置记录',12,'add_faultrecord'),
(46,'Can change 故障处置记录',12,'change_faultrecord'),
(47,'Can delete 故障处置记录',12,'delete_faultrecord'),
(48,'Can view 故障处置记录',12,'view_faultrecord'),
(49,'Can add 故障件',13,'add_faultpart'),
(50,'Can change 故障件',13,'change_faultpart'),
(51,'Can delete 故障件',13,'delete_faultpart'),
(52,'Can view 故障件',13,'view_faultpart'),
(53,'Can add 值班日志',14,'add_dutyrecord'),
(54,'Can change 值班日志',14,'change_dutyrecord'),
(55,'Can delete 值班日志',14,'delete_dutyrecord'),
(56,'Can view 值班日志',14,'view_dutyrecord'),
(57,'Can add 设备档案',15,'add_deviceresume'),
(58,'Can change 设备档案',15,'change_deviceresume'),
(59,'Can delete 设备档案',15,'delete_deviceresume'),
(60,'Can view 设备档案',15,'view_deviceresume'),
(61,'Can add 设备事件',16,'add_deviceevent'),
(62,'Can change 设备事件',16,'change_deviceevent'),
(63,'Can delete 设备事件',16,'delete_deviceevent'),
(64,'Can view 设备事件',16,'view_deviceevent'),
(65,'Can add 干扰记录',17,'add_interference'),
(66,'Can change 干扰记录',17,'change_interference'),
(67,'Can delete 干扰记录',17,'delete_interference'),
(68,'Can view 干扰记录',17,'view_interference'),
(69,'Can add navigation',18,'add_navigation'),
(70,'Can change navigation',18,'change_navigation'),
(71,'Can delete navigation',18,'delete_navigation'),
(72,'Can view navigation',18,'view_navigation'),
(73,'Can add notice',19,'add_notice'),
(74,'Can change notice',19,'change_notice'),
(75,'Can delete notice',19,'delete_notice'),
(76,'Can view notice',19,'view_notice'),
(77,'Can add 公告',20,'add_announcement'),
(78,'Can change 公告',20,'change_announcement'),
(79,'Can delete 公告',20,'delete_announcement'),
(80,'Can view 公告',20,'view_announcement'),
(81,'Can add 公告发布范围',21,'add_announcementscope'),
(82,'Can change 公告发布范围',21,'change_announcementscope'),
(83,'Can delete 公告发布范围',21,'delete_announcementscope'),
(84,'Can view 公告发布范围',21,'view_announcementscope'),
(85,'Can add 公告已读',22,'add_announcementread'),
(86,'Can change 公告已读',22,'change_announcementread'),
(87,'Can delete 公告已读',22,'delete_announcementread'),
(88,'Can view 公告已读',22,'view_announcementread'),
(89,'Can add 运行日志动态',23,'add_runlogupdate'),
(90,'Can change 运行日志动态',23,'change_runlogupdate'),
(91,'Can delete 运行日志动态',23,'delete_runlogupdate'),
(92,'Can view 运行日志动态',23,'view_runlogupdate'),
(93,'Can add 运行日志',24,'add_runlog'),
(94,'Can change 运行日志',24,'change_runlog'),
(95,'Can delete 运行日志',24,'delete_runlog'),
(96,'Can view 运行日志',24,'view_runlog'),
(97,'Can add 事件类型配置',25,'add_eventtypeconfig'),
(98,'Can change 事件类型配置',25,'change_eventtypeconfig'),
(99,'Can delete 事件类型配置',25,'delete_eventtypeconfig'),
(100,'Can view 事件类型配置',25,'view_eventtypeconfig'),
(101,'Can add 文件传输记录',26,'add_documenttransfer'),
(102,'Can change 文件传输记录',26,'change_documenttransfer'),
(103,'Can delete 文件传输记录',26,'delete_documenttransfer'),
(104,'Can view 文件传输记录',26,'view_documenttransfer'),
(105,'Can add 文档文件夹(公共)',27,'add_documentfolderpublic'),
(106,'Can change 文档文件夹(公共)',27,'change_documentfolderpublic'),
(107,'Can delete 文档文件夹(公共)',27,'delete_documentfolderpublic'),
(108,'Can view 文档文件夹(公共)',27,'view_documentfolderpublic'),
(109,'Can add 文档文件夹(私有)',28,'add_documentfolderprivate'),
(110,'Can change 文档文件夹(私有)',28,'change_documentfolderprivate'),
(111,'Can delete 文档文件夹(私有)',28,'delete_documentfolderprivate'),
(112,'Can view 文档文件夹(私有)',28,'view_documentfolderprivate'),
(113,'Can add 文档文件(公共)',29,'add_documentfilepublic'),
(114,'Can change 文档文件(公共)',29,'change_documentfilepublic'),
(115,'Can delete 文档文件(公共)',29,'delete_documentfilepublic'),
(116,'Can view 文档文件(公共)',29,'view_documentfilepublic'),
(117,'Can add 文档文件(私有)',30,'add_documentfileprivate'),
(118,'Can change 文档文件(私有)',30,'change_documentfileprivate'),
(119,'Can delete 文档文件(私有)',30,'delete_documentfileprivate'),
(120,'Can view 文档文件(私有)',30,'view_documentfileprivate'),
(121,'Can add 文档系统目录绑定',31,'add_documentsystemfolder'),
(122,'Can change 文档系统目录绑定',31,'change_documentsystemfolder'),
(123,'Can delete 文档系统目录绑定',31,'delete_documentsystemfolder'),
(124,'Can view 文档系统目录绑定',31,'view_documentsystemfolder'),
(125,'Can add 升级记录',32,'add_upgraderecord'),
(126,'Can change 升级记录',32,'change_upgraderecord'),
(127,'Can delete 升级记录',32,'delete_upgraderecord'),
(128,'Can view 升级记录',32,'view_upgraderecord'),
(129,'Can add 升级记录步骤',33,'add_upgraderecordstep'),
(130,'Can change 升级记录步骤',33,'change_upgraderecordstep'),
(131,'Can delete 升级记录步骤',33,'delete_upgraderecordstep'),
(132,'Can view 升级记录步骤',33,'view_upgraderecordstep'),
(133,'Can add 升级方案',34,'add_upgradetemplate'),
(134,'Can change 升级方案',34,'change_upgradetemplate'),
(135,'Can delete 升级方案',34,'delete_upgradetemplate'),
(136,'Can view 升级方案',34,'view_upgradetemplate'),
(137,'Can add 方案预设步骤',35,'add_upgradeplanstep'),
(138,'Can change 方案预设步骤',35,'change_upgradeplanstep'),
(139,'Can delete 方案预设步骤',35,'delete_upgradeplanstep'),
(140,'Can view 方案预设步骤',35,'view_upgradeplanstep'),
(141,'Can add 升级状态日志',36,'add_upgradestatuslog'),
(142,'Can change 升级状态日志',36,'change_upgradestatuslog'),
(143,'Can delete 升级状态日志',36,'delete_upgradestatuslog'),
(144,'Can view 升级状态日志',36,'view_upgradestatuslog'),
(145,'Can add 升级系统候选项',37,'add_upgradesystem'),
(146,'Can change 升级系统候选项',37,'change_upgradesystem'),
(147,'Can delete 升级系统候选项',37,'delete_upgradesystem'),
(148,'Can view 升级系统候选项',37,'view_upgradesystem'),
(149,'Can add 检查表模板',38,'add_checksheettemplate'),
(150,'Can change 检查表模板',38,'change_checksheettemplate'),
(151,'Can delete 检查表模板',38,'delete_checksheettemplate'),
(152,'Can view 检查表模板',38,'view_checksheettemplate'),
(153,'Can add 每日检查汇总',39,'add_checksheetdailysummary'),
(154,'Can change 每日检查汇总',39,'change_checksheetdailysummary'),
(155,'Can delete 每日检查汇总',39,'delete_checksheetdailysummary'),
(156,'Can view 每日检查汇总',39,'view_checksheetdailysummary'),
(157,'Can add 检查记录',40,'add_checksheetrecord'),
(158,'Can change 检查记录',40,'change_checksheetrecord'),
(159,'Can delete 检查记录',40,'delete_checksheetrecord'),
(160,'Can view 检查记录',40,'view_checksheetrecord'),
(161,'Can add 检查单提交批次',41,'add_checksheetsubmission'),
(162,'Can change 检查单提交批次',41,'change_checksheetsubmission'),
(163,'Can delete 检查单提交批次',41,'delete_checksheetsubmission'),
(164,'Can view 检查单提交批次',41,'view_checksheetsubmission'),
(165,'Can add audit log',42,'add_auditlog'),
(166,'Can change audit log',42,'change_auditlog'),
(167,'Can delete audit log',42,'delete_auditlog'),
(168,'Can view audit log',42,'view_auditlog'),
(169,'Can add 无线电台执照',43,'add_radiolicense'),
(170,'Can change 无线电台执照',43,'change_radiolicense'),
(171,'Can delete 无线电台执照',43,'delete_radiolicense'),
(172,'Can view 无线电台执照',43,'view_radiolicense'),
(173,'Can add 执照频率明细',44,'add_radiolicensefrequency'),
(174,'Can change 执照频率明细',44,'change_radiolicensefrequency'),
(175,'Can delete 执照频率明细',44,'delete_radiolicensefrequency'),
(176,'Can view 执照频率明细',44,'view_radiolicensefrequency'),
(177,'Can add 执照提醒确认',45,'add_licensereminderack'),
(178,'Can change 执照提醒确认',45,'change_licensereminderack'),
(179,'Can delete 执照提醒确认',45,'delete_licensereminderack'),
(180,'Can view 执照提醒确认',45,'view_licensereminderack'),
(181,'Can add 执照版本',46,'add_radiolicenseversion'),
(182,'Can change 执照版本',46,'change_radiolicenseversion'),
(183,'Can delete 执照版本',46,'delete_radiolicenseversion'),
(184,'Can view 执照版本',46,'view_radiolicenseversion'),
(185,'Can add 台站频率批复',47,'add_stationfrequencyapproval'),
(186,'Can change 台站频率批复',47,'change_stationfrequencyapproval'),
(187,'Can delete 台站频率批复',47,'delete_stationfrequencyapproval'),
(188,'Can view 台站频率批复',47,'view_stationfrequencyapproval'),
(189,'Can add 频率批复提醒确认',48,'add_stationfrequencyapprovalreminderack'),
(190,'Can change 频率批复提醒确认',48,'change_stationfrequencyapprovalreminderack'),
(191,'Can delete 频率批复提醒确认',48,'delete_stationfrequencyapprovalreminderack'),
(192,'Can view 频率批复提醒确认',48,'view_stationfrequencyapprovalreminderack'),
(193,'Can add 合同协议',49,'add_contractagreement'),
(194,'Can change 合同协议',49,'change_contractagreement'),
(195,'Can delete 合同协议',49,'delete_contractagreement'),
(196,'Can view 合同协议',49,'view_contractagreement'),
(197,'Can add 合同协议提醒确认',50,'add_contractagreementreminderack'),
(198,'Can change 合同协议提醒确认',50,'change_contractagreementreminderack'),
(199,'Can delete 合同协议提醒确认',50,'delete_contractagreementreminderack'),
(200,'Can view 合同协议提醒确认',50,'view_contractagreementreminderack'),
(201,'Can add 证据事件',51,'add_evidenceevent'),
(202,'Can change 证据事件',51,'change_evidenceevent'),
(203,'Can delete 证据事件',51,'delete_evidenceevent'),
(204,'Can view 证据事件',51,'view_evidenceevent'),
(205,'Can add 附件证据',52,'add_evidenceattachment'),
(206,'Can change 附件证据',52,'change_evidenceattachment'),
(207,'Can delete 附件证据',52,'delete_evidenceattachment'),
(208,'Can view 附件证据',52,'view_evidenceattachment'),
(209,'Can add 规章',53,'add_regulation'),
(210,'Can change 规章',53,'change_regulation'),
(211,'Can delete 规章',53,'delete_regulation'),
(212,'Can view 规章',53,'view_regulation'),
(213,'Can add 规章分类',54,'add_regulationcategory'),
(214,'Can change 规章分类',54,'change_regulationcategory'),
(215,'Can delete 规章分类',54,'delete_regulationcategory'),
(216,'Can view 规章分类',54,'view_regulationcategory'),
(217,'Can add 规章附件',55,'add_regulationattachment'),
(218,'Can change 规章附件',55,'change_regulationattachment'),
(219,'Can delete 规章附件',55,'delete_regulationattachment'),
(220,'Can view 规章附件',55,'view_regulationattachment'),
(221,'Can add 账号签名',56,'add_accountsignature'),
(222,'Can change 账号签名',56,'change_accountsignature'),
(223,'Can delete 账号签名',56,'delete_accountsignature'),
(224,'Can view 账号签名',56,'view_accountsignature'),
(225,'Can add 签名使用记录',57,'add_signatureusage'),
(226,'Can change 签名使用记录',57,'change_signatureusage'),
(227,'Can delete 签名使用记录',57,'delete_signatureusage'),
(228,'Can view 签名使用记录',57,'view_signatureusage'),
(229,'Can add 部门值班日志',58,'add_departmentdutylog'),
(230,'Can change 部门值班日志',58,'change_departmentdutylog'),
(231,'Can delete 部门值班日志',58,'delete_departmentdutylog'),
(232,'Can view 部门值班日志',58,'view_departmentdutylog'),
(233,'Can add task result',59,'add_taskresult'),
(234,'Can change task result',59,'change_taskresult'),
(235,'Can delete task result',59,'delete_taskresult'),
(236,'Can view task result',59,'view_taskresult'),
(237,'Can add chord counter',60,'add_chordcounter'),
(238,'Can change chord counter',60,'change_chordcounter'),
(239,'Can delete chord counter',60,'delete_chordcounter'),
(240,'Can view chord counter',60,'view_chordcounter'),
(241,'Can add group result',61,'add_groupresult'),
(242,'Can change group result',61,'change_groupresult'),
(243,'Can delete group result',61,'delete_groupresult'),
(244,'Can view group result',61,'view_groupresult'),
(245,'Can add crontab',62,'add_crontabschedule'),
(246,'Can change crontab',62,'change_crontabschedule'),
(247,'Can delete crontab',62,'delete_crontabschedule'),
(248,'Can view crontab',62,'view_crontabschedule'),
(249,'Can add interval',63,'add_intervalschedule'),
(250,'Can change interval',63,'change_intervalschedule'),
(251,'Can delete interval',63,'delete_intervalschedule'),
(252,'Can view interval',63,'view_intervalschedule'),
(253,'Can add periodic task',64,'add_periodictask'),
(254,'Can change periodic task',64,'change_periodictask'),
(255,'Can delete periodic task',64,'delete_periodictask'),
(256,'Can view periodic task',64,'view_periodictask'),
(257,'Can add periodic task track',65,'add_periodictasks'),
(258,'Can change periodic task track',65,'change_periodictasks'),
(259,'Can delete periodic task track',65,'delete_periodictasks'),
(260,'Can view periodic task track',65,'view_periodictasks'),
(261,'Can add solar event',66,'add_solarschedule'),
(262,'Can change solar event',66,'change_solarschedule'),
(263,'Can delete solar event',66,'delete_solarschedule'),
(264,'Can view solar event',66,'view_solarschedule'),
(265,'Can add clocked',67,'add_clockedschedule'),
(266,'Can change clocked',67,'change_clockedschedule'),
(267,'Can delete clocked',67,'delete_clockedschedule'),
(268,'Can view clocked',67,'view_clockedschedule');
/*!40000 ALTER TABLE `auth_permission` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `auth_user`
--

DROP TABLE IF EXISTS `auth_user`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `auth_user` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `password` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `last_login` datetime(6) DEFAULT NULL,
  `is_superuser` tinyint(1) NOT NULL,
  `username` varchar(150) COLLATE utf8mb4_unicode_ci NOT NULL,
  `first_name` varchar(150) COLLATE utf8mb4_unicode_ci NOT NULL,
  `last_name` varchar(150) COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` varchar(254) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_staff` tinyint(1) NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  `date_joined` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `auth_user`
--

LOCK TABLES `auth_user` WRITE;
/*!40000 ALTER TABLE `auth_user` DISABLE KEYS */;
/*!40000 ALTER TABLE `auth_user` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `auth_user_groups`
--

DROP TABLE IF EXISTS `auth_user_groups`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `auth_user_groups` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `group_id` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_user_groups_user_id_group_id_94350c0c_uniq` (`user_id`,`group_id`),
  KEY `auth_user_groups_group_id_97559544_fk_auth_group_id` (`group_id`),
  CONSTRAINT `auth_user_groups_group_id_97559544_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`),
  CONSTRAINT `auth_user_groups_user_id_6a12ed8b_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `auth_user_groups`
--

LOCK TABLES `auth_user_groups` WRITE;
/*!40000 ALTER TABLE `auth_user_groups` DISABLE KEYS */;
/*!40000 ALTER TABLE `auth_user_groups` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `auth_user_user_permissions`
--

DROP TABLE IF EXISTS `auth_user_user_permissions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `auth_user_user_permissions` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `permission_id` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `auth_user_user_permissions_user_id_permission_id_14a6b632_uniq` (`user_id`,`permission_id`),
  KEY `auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm` (`permission_id`),
  CONSTRAINT `auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`),
  CONSTRAINT `auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `auth_user_user_permissions`
--

LOCK TABLES `auth_user_user_permissions` WRITE;
/*!40000 ALTER TABLE `auth_user_user_permissions` DISABLE KEYS */;
/*!40000 ALTER TABLE `auth_user_user_permissions` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `django_celery_beat_clockedschedule`
--

DROP TABLE IF EXISTS `django_celery_beat_clockedschedule`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `django_celery_beat_clockedschedule` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `clocked_time` datetime(6) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `django_celery_beat_clockedschedule`
--

LOCK TABLES `django_celery_beat_clockedschedule` WRITE;
/*!40000 ALTER TABLE `django_celery_beat_clockedschedule` DISABLE KEYS */;
/*!40000 ALTER TABLE `django_celery_beat_clockedschedule` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `django_celery_beat_crontabschedule`
--

DROP TABLE IF EXISTS `django_celery_beat_crontabschedule`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `django_celery_beat_crontabschedule` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `minute` varchar(240) COLLATE utf8mb4_unicode_ci NOT NULL,
  `hour` varchar(96) COLLATE utf8mb4_unicode_ci NOT NULL,
  `day_of_week` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `day_of_month` varchar(124) COLLATE utf8mb4_unicode_ci NOT NULL,
  `month_of_year` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `timezone` varchar(63) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=13 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `django_celery_beat_crontabschedule`
--

LOCK TABLES `django_celery_beat_crontabschedule` WRITE;
/*!40000 ALTER TABLE `django_celery_beat_crontabschedule` DISABLE KEYS */;
INSERT INTO `django_celery_beat_crontabschedule` VALUES
(1,'0','4','*','*','*','Asia/Shanghai'),
(2,'0','2','*','*','*','Asia/Shanghai'),
(3,'0','3','*','*','*','Asia/Shanghai'),
(4,'*/10','*','*','*','*','Asia/Shanghai'),
(5,'0','5','*','*','*','Asia/Shanghai'),
(6,'0','*/6','*','*','*','Asia/Shanghai'),
(7,'0','6','*','*','*','Asia/Shanghai'),
(8,'0','8','*','*','*','Asia/Shanghai'),
(9,'5','8','*','*','*','Asia/Shanghai'),
(10,'10','8','*','*','*','Asia/Shanghai'),
(11,'5','*','*','*','*','Asia/Shanghai'),
(12,'0','*','*','*','*','Asia/Shanghai');
/*!40000 ALTER TABLE `django_celery_beat_crontabschedule` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `django_celery_beat_intervalschedule`
--

DROP TABLE IF EXISTS `django_celery_beat_intervalschedule`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `django_celery_beat_intervalschedule` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `every` int(11) NOT NULL,
  `period` varchar(24) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `django_celery_beat_intervalschedule`
--

LOCK TABLES `django_celery_beat_intervalschedule` WRITE;
/*!40000 ALTER TABLE `django_celery_beat_intervalschedule` DISABLE KEYS */;
INSERT INTO `django_celery_beat_intervalschedule` VALUES
(1,3600,'seconds');
/*!40000 ALTER TABLE `django_celery_beat_intervalschedule` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `django_celery_beat_periodictask`
--

DROP TABLE IF EXISTS `django_celery_beat_periodictask`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `django_celery_beat_periodictask` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `task` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `args` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `kwargs` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `queue` varchar(200) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `exchange` varchar(200) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `routing_key` varchar(200) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `expires` datetime(6) DEFAULT NULL,
  `enabled` tinyint(1) NOT NULL,
  `last_run_at` datetime(6) DEFAULT NULL,
  `total_run_count` int(10) unsigned NOT NULL CHECK (`total_run_count` >= 0),
  `date_changed` datetime(6) NOT NULL,
  `description` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `crontab_id` int(11) DEFAULT NULL,
  `interval_id` int(11) DEFAULT NULL,
  `solar_id` int(11) DEFAULT NULL,
  `one_off` tinyint(1) NOT NULL,
  `start_time` datetime(6) DEFAULT NULL,
  `priority` int(10) unsigned DEFAULT NULL CHECK (`priority` >= 0),
  `headers` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `clocked_id` int(11) DEFAULT NULL,
  `expire_seconds` int(10) unsigned DEFAULT NULL CHECK (`expire_seconds` >= 0),
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`),
  KEY `django_celery_beat_p_crontab_id_d3cba168_fk_django_ce` (`crontab_id`),
  KEY `django_celery_beat_p_interval_id_a8ca27da_fk_django_ce` (`interval_id`),
  KEY `django_celery_beat_p_solar_id_a87ce72c_fk_django_ce` (`solar_id`),
  KEY `django_celery_beat_p_clocked_id_47a69f82_fk_django_ce` (`clocked_id`),
  CONSTRAINT `django_celery_beat_p_clocked_id_47a69f82_fk_django_ce` FOREIGN KEY (`clocked_id`) REFERENCES `django_celery_beat_clockedschedule` (`id`),
  CONSTRAINT `django_celery_beat_p_crontab_id_d3cba168_fk_django_ce` FOREIGN KEY (`crontab_id`) REFERENCES `django_celery_beat_crontabschedule` (`id`),
  CONSTRAINT `django_celery_beat_p_interval_id_a8ca27da_fk_django_ce` FOREIGN KEY (`interval_id`) REFERENCES `django_celery_beat_intervalschedule` (`id`),
  CONSTRAINT `django_celery_beat_p_solar_id_a87ce72c_fk_django_ce` FOREIGN KEY (`solar_id`) REFERENCES `django_celery_beat_solarschedule` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=16 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `django_celery_beat_periodictask`
--

LOCK TABLES `django_celery_beat_periodictask` WRITE;
/*!40000 ALTER TABLE `django_celery_beat_periodictask` DISABLE KEYS */;
INSERT INTO `django_celery_beat_periodictask` VALUES
(1,'celery.backend_cleanup','celery.backend_cleanup','[]','{}',NULL,NULL,NULL,NULL,1,NULL,0,'2026-07-24 10:29:26.011037','',1,NULL,NULL,0,NULL,NULL,'{}',NULL,43200),
(2,'retry-clean-pending-files','apps.document.tasks.cleanup.retry_clean_pending_files','[]','{}','document.cleanup',NULL,NULL,NULL,1,NULL,0,'2026-07-24 10:29:26.034119','',NULL,1,NULL,0,NULL,NULL,'{}',NULL,NULL),
(3,'document-cleanup-old-chunks','apps.document.tasks.cleanup.cleanup_old_chunks','[]','{\"days\": 7}','document.cleanup',NULL,NULL,NULL,1,NULL,0,'2026-07-24 10:29:26.096499','',2,NULL,NULL,0,NULL,NULL,'{}',NULL,NULL),
(4,'document-cleanup-expired-transfers','apps.document.tasks.cleanup.cleanup_expired_transfers','[]','{}','document.cleanup',NULL,NULL,NULL,1,NULL,0,'2026-07-24 10:29:26.113367','',3,NULL,NULL,0,NULL,NULL,'{}',NULL,NULL),
(5,'document-check-merge-timeout','apps.document.tasks.timeout_checker.check_merge_timeout','[]','{\"timeout_minutes\": 30}','document.cleanup',NULL,NULL,NULL,1,NULL,0,'2026-07-24 10:29:26.129867','',4,NULL,NULL,0,NULL,NULL,'{}',NULL,NULL),
(6,'document-cleanup-stale-merging','apps.document.tasks.timeout_checker.cleanup_stale_merging_tasks','[]','{\"older_than_hours\": 24}','document.cleanup',NULL,NULL,NULL,1,NULL,0,'2026-07-24 10:29:26.187190','',5,NULL,NULL,0,NULL,NULL,'{}',NULL,NULL),
(7,'document-cleanup-orphan-transfers','apps.document.tasks.cleanup.orphan_transfers.cleanup_orphan_transfers','[]','{\"dry_run\": false}','document.cleanup',NULL,NULL,NULL,1,NULL,0,'2026-07-24 10:29:26.205186','',6,NULL,NULL,0,NULL,NULL,'{}',NULL,NULL),
(8,'document-cleanup-expired-pack-tasks','apps.document.tasks.pack.cleanup_expired_pack_tasks','[]','{\"max_age_hours\": 24}','document.pack',NULL,NULL,NULL,1,NULL,0,'2026-07-24 10:29:26.222558','',7,NULL,NULL,0,NULL,NULL,'{}',NULL,NULL),
(9,'radio-license-scan-expiration','apps.radio_license.tasks.scan_radio_license_expiration','[]','{}','radio_license',NULL,NULL,NULL,1,NULL,0,'2026-07-24 10:29:26.278997','',8,NULL,NULL,0,NULL,NULL,'{}',NULL,NULL),
(10,'radio-license-scan-approval-expiration','apps.radio_license.tasks.scan_approval_expiration','[]','{}','radio_license',NULL,NULL,NULL,1,NULL,0,'2026-07-24 10:29:26.297779','',9,NULL,NULL,0,NULL,NULL,'{}',NULL,NULL),
(11,'contract-agreement-scan-expiration','apps.contract_agreement.tasks.scan_contract_agreement_expiration','[]','{}','contract_agreement',NULL,NULL,NULL,1,NULL,0,'2026-07-24 10:29:26.316393','',10,NULL,NULL,0,NULL,NULL,'{}',NULL,NULL),
(12,'logs-cleanup-old-audit-logs','apps.logs.tasks.cleanup_old_audit_logs','[]','{\"days\": 60}','default',NULL,NULL,NULL,1,NULL,0,'2026-07-24 10:29:26.335026','',1,NULL,NULL,0,NULL,NULL,'{}',NULL,NULL),
(13,'announcement-sync-status','apps.home.tasks.sync_announcement_status','[]','{}','home.announcement',NULL,NULL,NULL,1,NULL,0,'2026-07-24 10:29:26.383346','',11,NULL,NULL,0,NULL,NULL,'{}',NULL,NULL),
(14,'cleanup-old-chunks-every-hour','apps.document.tasks.cleanup_old_chunks','[7]','{}','document.cleanup',NULL,NULL,NULL,1,NULL,0,'2026-07-24 10:29:26.401881','',12,NULL,NULL,0,NULL,NULL,'{}',NULL,NULL),
(15,'cleanup-expired-transfers-daily','apps.document.tasks.cleanup_expired_transfers','[30]','{}','document.cleanup',NULL,NULL,NULL,1,NULL,0,'2026-07-24 10:29:26.417017','',3,NULL,NULL,0,NULL,NULL,'{}',NULL,NULL);
/*!40000 ALTER TABLE `django_celery_beat_periodictask` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `django_celery_beat_periodictasks`
--

DROP TABLE IF EXISTS `django_celery_beat_periodictasks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `django_celery_beat_periodictasks` (
  `ident` smallint(6) NOT NULL,
  `last_update` datetime(6) NOT NULL,
  PRIMARY KEY (`ident`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `django_celery_beat_periodictasks`
--

LOCK TABLES `django_celery_beat_periodictasks` WRITE;
/*!40000 ALTER TABLE `django_celery_beat_periodictasks` DISABLE KEYS */;
INSERT INTO `django_celery_beat_periodictasks` VALUES
(1,'2026-07-24 10:29:26.417416');
/*!40000 ALTER TABLE `django_celery_beat_periodictasks` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `django_celery_beat_solarschedule`
--

DROP TABLE IF EXISTS `django_celery_beat_solarschedule`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `django_celery_beat_solarschedule` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `event` varchar(24) COLLATE utf8mb4_unicode_ci NOT NULL,
  `latitude` decimal(9,6) NOT NULL,
  `longitude` decimal(9,6) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `django_celery_beat_solar_event_latitude_longitude_ba64999a_uniq` (`event`,`latitude`,`longitude`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `django_celery_beat_solarschedule`
--

LOCK TABLES `django_celery_beat_solarschedule` WRITE;
/*!40000 ALTER TABLE `django_celery_beat_solarschedule` DISABLE KEYS */;
/*!40000 ALTER TABLE `django_celery_beat_solarschedule` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `django_celery_results_chordcounter`
--

DROP TABLE IF EXISTS `django_celery_results_chordcounter`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `django_celery_results_chordcounter` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `group_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `sub_tasks` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `count` int(10) unsigned NOT NULL CHECK (`count` >= 0),
  PRIMARY KEY (`id`),
  UNIQUE KEY `group_id` (`group_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `django_celery_results_chordcounter`
--

LOCK TABLES `django_celery_results_chordcounter` WRITE;
/*!40000 ALTER TABLE `django_celery_results_chordcounter` DISABLE KEYS */;
/*!40000 ALTER TABLE `django_celery_results_chordcounter` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `django_celery_results_groupresult`
--

DROP TABLE IF EXISTS `django_celery_results_groupresult`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `django_celery_results_groupresult` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `group_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `date_created` datetime(6) NOT NULL,
  `date_done` datetime(6) NOT NULL,
  `content_type` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `content_encoding` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `result` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `group_id` (`group_id`),
  KEY `django_cele_date_cr_bd6c1d_idx` (`date_created`),
  KEY `django_cele_date_do_caae0e_idx` (`date_done`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `django_celery_results_groupresult`
--

LOCK TABLES `django_celery_results_groupresult` WRITE;
/*!40000 ALTER TABLE `django_celery_results_groupresult` DISABLE KEYS */;
/*!40000 ALTER TABLE `django_celery_results_groupresult` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `django_celery_results_taskresult`
--

DROP TABLE IF EXISTS `django_celery_results_taskresult`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `django_celery_results_taskresult` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `task_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `content_type` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `content_encoding` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `result` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `date_done` datetime(6) NOT NULL,
  `traceback` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `meta` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `task_args` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `task_kwargs` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `task_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `worker` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `date_created` datetime(6) NOT NULL,
  `periodic_task_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `task_id` (`task_id`),
  KEY `django_cele_task_na_08aec9_idx` (`task_name`),
  KEY `django_cele_status_9b6201_idx` (`status`),
  KEY `django_cele_worker_d54dd8_idx` (`worker`),
  KEY `django_cele_date_cr_f04a50_idx` (`date_created`),
  KEY `django_cele_date_do_f59aad_idx` (`date_done`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `django_celery_results_taskresult`
--

LOCK TABLES `django_celery_results_taskresult` WRITE;
/*!40000 ALTER TABLE `django_celery_results_taskresult` DISABLE KEYS */;
/*!40000 ALTER TABLE `django_celery_results_taskresult` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `django_content_type`
--

DROP TABLE IF EXISTS `django_content_type`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `django_content_type` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `app_label` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `model` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `django_content_type_app_label_model_76bd3d3b_uniq` (`app_label`,`model`)
) ENGINE=InnoDB AUTO_INCREMENT=68 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `django_content_type`
--

LOCK TABLES `django_content_type` WRITE;
/*!40000 ALTER TABLE `django_content_type` DISABLE KEYS */;
INSERT INTO `django_content_type` VALUES
(6,'account','history'),
(7,'account','role'),
(9,'account','tenant'),
(8,'account','user'),
(2,'auth','group'),
(1,'auth','permission'),
(3,'auth','user'),
(39,'checksheet','checksheetdailysummary'),
(40,'checksheet','checksheetrecord'),
(41,'checksheet','checksheetsubmission'),
(38,'checksheet','checksheettemplate'),
(4,'contenttypes','contenttype'),
(49,'contract_agreement','contractagreement'),
(50,'contract_agreement','contractagreementreminderack'),
(58,'department_duty_log','departmentdutylog'),
(16,'device','deviceevent'),
(15,'device','deviceresume'),
(67,'django_celery_beat','clockedschedule'),
(62,'django_celery_beat','crontabschedule'),
(63,'django_celery_beat','intervalschedule'),
(64,'django_celery_beat','periodictask'),
(65,'django_celery_beat','periodictasks'),
(66,'django_celery_beat','solarschedule'),
(60,'django_celery_results','chordcounter'),
(61,'django_celery_results','groupresult'),
(59,'django_celery_results','taskresult'),
(30,'document','documentfileprivate'),
(29,'document','documentfilepublic'),
(28,'document','documentfolderprivate'),
(27,'document','documentfolderpublic'),
(31,'document','documentsystemfolder'),
(26,'document','documenttransfer'),
(14,'duty','dutyrecord'),
(52,'evidence','evidenceattachment'),
(51,'evidence','evidenceevent'),
(13,'fault','faultpart'),
(12,'fault','faultrecord'),
(20,'home','announcement'),
(22,'home','announcementread'),
(21,'home','announcementscope'),
(18,'home','navigation'),
(19,'home','notice'),
(17,'interference','interference'),
(42,'logs','auditlog'),
(45,'radio_license','licensereminderack'),
(43,'radio_license','radiolicense'),
(44,'radio_license','radiolicensefrequency'),
(46,'radio_license','radiolicenseversion'),
(47,'radio_license','stationfrequencyapproval'),
(48,'radio_license','stationfrequencyapprovalreminderack'),
(53,'regulation','regulation'),
(55,'regulation','regulationattachment'),
(54,'regulation','regulationcategory'),
(25,'runlog','eventtypeconfig'),
(24,'runlog','runlog'),
(23,'runlog','runlogupdate'),
(5,'sessions','session'),
(10,'setting','setting'),
(11,'setting','usersetting'),
(56,'signature','accountsignature'),
(57,'signature','signatureusage'),
(35,'upgrade','upgradeplanstep'),
(32,'upgrade','upgraderecord'),
(33,'upgrade','upgraderecordstep'),
(36,'upgrade','upgradestatuslog'),
(37,'upgrade','upgradesystem'),
(34,'upgrade','upgradetemplate');
/*!40000 ALTER TABLE `django_content_type` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `django_migrations`
--

DROP TABLE IF EXISTS `django_migrations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `django_migrations` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `app` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `applied` datetime(6) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=166 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `django_migrations`
--

LOCK TABLES `django_migrations` WRITE;
/*!40000 ALTER TABLE `django_migrations` DISABLE KEYS */;
INSERT INTO `django_migrations` VALUES
(1,'account','0001_initial','2026-07-24 10:28:58.976612'),
(2,'account','0002_alter_role_is_global_admin_default','2026-07-24 10:28:58.994198'),
(3,'account','0003_add_tenant_id_index','2026-07-24 10:28:59.088969'),
(4,'account','0004_tenant_model','2026-07-24 10:28:59.122457'),
(5,'account','0005_populate_tenants','2026-07-24 10:28:59.129812'),
(6,'account','0006_role_tenant_system','2026-07-24 10:28:59.196243'),
(7,'account','0007_role_perms_version','2026-07-24 10:28:59.235131'),
(8,'account','0008_alter_history_id_alter_role_id_alter_user_id','2026-07-24 10:28:59.693502'),
(9,'account','0009_alter_history_created_at_alter_role_created_at_and_more','2026-07-24 10:28:59.868482'),
(10,'contenttypes','0001_initial','2026-07-24 10:28:59.897058'),
(11,'contenttypes','0002_remove_content_type_name','2026-07-24 10:28:59.931535'),
(12,'auth','0001_initial','2026-07-24 10:29:00.177366'),
(13,'auth','0002_alter_permission_name_max_length','2026-07-24 10:29:00.203618'),
(14,'auth','0003_alter_user_email_max_length','2026-07-24 10:29:00.218456'),
(15,'auth','0004_alter_user_username_opts','2026-07-24 10:29:00.225731'),
(16,'auth','0005_alter_user_last_login_null','2026-07-24 10:29:00.248044'),
(17,'auth','0006_require_contenttypes_0002','2026-07-24 10:29:00.250770'),
(18,'auth','0007_alter_validators_add_error_messages','2026-07-24 10:29:00.256322'),
(19,'auth','0008_alter_user_username_max_length','2026-07-24 10:29:00.272268'),
(20,'auth','0009_alter_user_last_name_max_length','2026-07-24 10:29:00.287368'),
(21,'auth','0010_alter_group_name_max_length','2026-07-24 10:29:00.301707'),
(22,'auth','0011_update_proxy_permissions','2026-07-24 10:29:00.310220'),
(23,'auth','0012_alter_user_first_name_max_length','2026-07-24 10:29:00.326410'),
(24,'checksheet','0001_initial','2026-07-24 10:29:00.405384'),
(25,'checksheet','0002_auto_20260625_2355','2026-07-24 10:29:00.424141'),
(26,'checksheet','0003_evidence_submission','2026-07-24 10:29:00.555636'),
(27,'checksheet','0004_alter_checksheetdailysummary_id_and_more','2026-07-24 10:29:00.714070'),
(28,'contract_agreement','0001_initial','2026-07-24 10:29:00.930339'),
(29,'contract_agreement','0002_three_state_and_responsible_user','2026-07-24 10:29:01.025804'),
(30,'contract_agreement','0003_alter_contractagreement_id_and_more','2026-07-24 10:29:01.159062'),
(31,'contract_agreement','0004_alter_contractagreement_created_at_and_more','2026-07-24 10:29:01.295609'),
(32,'department_duty_log','0001_init_department_duty_log','2026-07-24 10:29:01.532238'),
(33,'department_duty_log','0002_remove_department_name','2026-07-24 10:29:01.559911'),
(34,'department_duty_log','0003_alter_departmentdutylog_id','2026-07-24 10:29:01.695425'),
(35,'department_duty_log','0004_alter_departmentdutylog_created_at_and_more','2026-07-24 10:29:01.893606'),
(36,'device','0001_initial','2026-07-24 10:29:02.114019'),
(37,'device','0002_fix_responsible_user_id_null','2026-07-24 10:29:02.157855'),
(38,'device','0003_fix_related_user_id_null','2026-07-24 10:29:02.191433'),
(39,'device','0004_device_sn_tenant_unique_and_choices','2026-07-24 10:29:02.270354'),
(40,'device','0005_evidence_fields','2026-07-24 10:29:02.411418'),
(41,'device','0006_alter_deviceresume_is_deleted','2026-07-24 10:29:02.420418'),
(42,'device','0007_alter_deviceevent_id_alter_deviceresume_id','2026-07-24 10:29:02.483911'),
(43,'device','0008_alter_deviceevent_corrected_at_and_more','2026-07-24 10:29:02.860815'),
(44,'django_celery_beat','0001_initial','2026-07-24 10:29:02.954326'),
(45,'django_celery_beat','0002_auto_20161118_0346','2026-07-24 10:29:02.998625'),
(46,'django_celery_beat','0003_auto_20161209_0049','2026-07-24 10:29:03.017503'),
(47,'django_celery_beat','0004_auto_20170221_0000','2026-07-24 10:29:03.022827'),
(48,'django_celery_beat','0005_add_solarschedule_events_choices','2026-07-24 10:29:03.027101'),
(49,'django_celery_beat','0006_auto_20180322_0932','2026-07-24 10:29:03.085638'),
(50,'django_celery_beat','0007_auto_20180521_0826','2026-07-24 10:29:03.122511'),
(51,'django_celery_beat','0008_auto_20180914_1922','2026-07-24 10:29:03.135649'),
(52,'django_celery_beat','0006_auto_20180210_1226','2026-07-24 10:29:03.145390'),
(53,'django_celery_beat','0006_periodictask_priority','2026-07-24 10:29:03.161279'),
(54,'django_celery_beat','0009_periodictask_headers','2026-07-24 10:29:03.184538'),
(55,'django_celery_beat','0010_auto_20190429_0326','2026-07-24 10:29:03.250447'),
(56,'django_celery_beat','0011_auto_20190508_0153','2026-07-24 10:29:03.302015'),
(57,'django_celery_beat','0012_periodictask_expire_seconds','2026-07-24 10:29:03.319631'),
(58,'django_celery_beat','0013_auto_20200609_0727','2026-07-24 10:29:03.325789'),
(59,'django_celery_beat','0014_remove_clockedschedule_enabled','2026-07-24 10:29:03.340331'),
(60,'django_celery_beat','0015_edit_solarschedule_events_choices','2026-07-24 10:29:03.345760'),
(61,'django_celery_beat','0016_alter_crontabschedule_timezone','2026-07-24 10:29:03.352395'),
(62,'django_celery_beat','0017_alter_crontabschedule_month_of_year','2026-07-24 10:29:03.358908'),
(63,'django_celery_beat','0018_improve_crontab_helptext','2026-07-24 10:29:03.364596'),
(64,'django_celery_beat','0019_alter_periodictasks_options','2026-07-24 10:29:03.369153'),
(65,'django_celery_results','0001_initial','2026-07-24 10:29:03.397183'),
(66,'django_celery_results','0002_add_task_name_args_kwargs','2026-07-24 10:29:03.431560'),
(67,'django_celery_results','0003_auto_20181106_1101','2026-07-24 10:29:03.436361'),
(68,'django_celery_results','0004_auto_20190516_0412','2026-07-24 10:29:03.492132'),
(69,'django_celery_results','0005_taskresult_worker','2026-07-24 10:29:03.518007'),
(70,'django_celery_results','0006_taskresult_date_created','2026-07-24 10:29:03.609339'),
(71,'django_celery_results','0007_remove_taskresult_hidden','2026-07-24 10:29:03.623484'),
(72,'django_celery_results','0008_chordcounter','2026-07-24 10:29:03.637847'),
(73,'django_celery_results','0009_groupresult','2026-07-24 10:29:03.851686'),
(74,'django_celery_results','0010_remove_duplicate_indices','2026-07-24 10:29:03.858350'),
(75,'django_celery_results','0011_taskresult_periodic_task_name','2026-07-24 10:29:03.873300'),
(76,'document','0001_initial','2026-07-24 10:29:04.446866'),
(77,'document','0002_add_thumbnail_path','2026-07-24 10:29:04.489018'),
(78,'document','0003_transfer_add_merging_choice','2026-07-24 10:29:04.501642'),
(79,'document','0004_folder_unique_constraints','2026-07-24 10:29:04.555805'),
(80,'document','0005_folder_unique_key','2026-07-24 10:29:04.796094'),
(81,'document','0006_auto_20260627_0807','2026-07-24 10:29:04.835201'),
(82,'document','0007_document_list_indexes','2026-07-24 10:29:04.927262'),
(83,'document','0008_transfer_cleanup_index','2026-07-24 10:29:04.949156'),
(84,'document','0009_document_system_folder','2026-07-24 10:29:04.993380'),
(85,'document','0010_transfer_system_folder','2026-07-24 10:29:05.072377'),
(86,'document','0011_rename_party_building_documents','2026-07-24 10:29:05.098994'),
(87,'document','0012_system_folder_unique_folder','2026-07-24 10:29:05.201520'),
(88,'document','0013_disk_usage_aggregate_index','2026-07-24 10:29:05.224003'),
(89,'document','0014_alter_documentfileprivate_id_and_more','2026-07-24 10:29:05.880564'),
(90,'duty','0001_initial','2026-07-24 10:29:05.941231'),
(91,'duty','0002_auto_20260627_0807','2026-07-24 10:29:05.954046'),
(92,'duty','0003_alter_dutyrecord_id','2026-07-24 10:29:05.989011'),
(93,'duty','0004_alter_dutyrecord_created_at_and_more','2026-07-24 10:29:06.105030'),
(94,'evidence','0001_initial','2026-07-24 10:29:06.250312'),
(95,'evidence','0002_evidenceattachment_ev_att_obj_del_time_idx','2026-07-24 10:29:06.270880'),
(96,'evidence','0003_alter_evidenceattachment_id_alter_evidenceevent_id','2026-07-24 10:29:06.335463'),
(97,'evidence','0004_alter_evidenceattachment_deleted_at_and_more','2026-07-24 10:29:06.437947'),
(98,'fault','0001_initial','2026-07-24 10:29:06.565742'),
(99,'fault','0002_auto_20260627_0807','2026-07-24 10:29:06.587052'),
(100,'fault','0003_alter_faultpart_id_alter_faultrecord_id','2026-07-24 10:29:06.657068'),
(101,'fault','0004_alter_faultpart_archive_date_and_more','2026-07-24 10:29:07.053131'),
(102,'home','0001_initial','2026-07-24 10:29:07.105185'),
(103,'home','0002_announcement_models','2026-07-24 10:29:07.406410'),
(104,'home','0003_alter_announcement_id_alter_announcementread_id_and_more','2026-07-24 10:29:07.682059'),
(105,'home','0004_alter_announcement_created_at_and_more','2026-07-24 10:29:08.102032'),
(106,'interference','0001_initial','2026-07-24 10:29:08.165637'),
(107,'interference','0002_auto_20260627_0807','2026-07-24 10:29:08.180233'),
(108,'interference','0003_evidence_status_flow','2026-07-24 10:29:08.860973'),
(109,'interference','0004_alter_interference_id','2026-07-24 10:29:08.904781'),
(110,'interference','0005_alter_interference_closed_at_and_more','2026-07-24 10:29:09.298162'),
(111,'logs','0001_initial','2026-07-24 10:29:09.313310'),
(112,'logs','0002_add_audit_indexes','2026-07-24 10:29:09.383864'),
(113,'logs','0003_audit_hash_fields','2026-07-24 10:29:09.551324'),
(114,'logs','0004_remove_dup_indexes','2026-07-24 10:29:09.584395'),
(115,'logs','0005_audit_tenant_ctime_id_idx','2026-07-24 10:29:09.600852'),
(116,'logs','0006_time_field_to_datetime','2026-07-24 10:29:09.639023'),
(117,'logs','0007_alter_auditlog_id','2026-07-24 10:29:09.682343'),
(118,'radio_license','0001_initial','2026-07-24 10:29:09.949218'),
(119,'radio_license','0002_add_attachment_model','2026-07-24 10:29:10.052506'),
(120,'radio_license','0003_add_reminder_model','2026-07-24 10:29:10.160670'),
(121,'radio_license','0004_remove_is_deleted','2026-07-24 10:29:10.222348'),
(122,'radio_license','0005_add_reminder_ack','2026-07-24 10:29:10.345805'),
(123,'radio_license','0006_auto_20260627_0807','2026-07-24 10:29:10.371053'),
(124,'radio_license','0007_evidence_attachment_version','2026-07-24 10:29:10.886066'),
(125,'radio_license','0008_remove_radiolicenseattachment','2026-07-24 10:29:10.898555'),
(126,'radio_license','0009_remove_radiolicensereminder','2026-07-24 10:29:10.911359'),
(127,'radio_license','0010_station_frequency_approval','2026-07-24 10:29:11.187979'),
(128,'radio_license','0011_alter_licensereminderack_id_alter_radiolicense_id_and_more','2026-07-24 10:29:11.708572'),
(129,'radio_license','0012_alter_licensereminderack_created_at_and_more','2026-07-24 10:29:12.141669'),
(130,'regulation','0001_initial','2026-07-24 10:29:12.658516'),
(131,'regulation','0002_remove_attachment_is_primary','2026-07-24 10:29:12.690958'),
(132,'regulation','0003_alter_regulation_id_alter_regulationattachment_id_and_more','2026-07-24 10:29:13.160809'),
(133,'regulation','0004_alter_regulation_updated_at_and_more','2026-07-24 10:29:13.349254'),
(134,'runlog','0001_initial','2026-07-24 10:29:13.634338'),
(135,'runlog','0003_add_event_type_config','2026-07-24 10:29:13.723524'),
(136,'runlog','0004_remove_event_type_tenant_id','2026-07-24 10:29:13.907449'),
(137,'runlog','0005_auto_20260604_1609','2026-07-24 10:29:13.982127'),
(138,'runlog','0006_add_duty_person_to_runlogupdate','2026-07-24 10:29:14.013937'),
(139,'runlog','0007_evidence_fields','2026-07-24 10:29:14.201357'),
(140,'runlog','0008_alter_runlog_status','2026-07-24 10:29:14.220854'),
(141,'runlog','0009_time_field_to_datetime','2026-07-24 10:29:14.758743'),
(142,'runlog','0010_alter_eventtypeconfig_id_alter_runlog_id_and_more','2026-07-24 10:29:14.897501'),
(143,'sessions','0001_initial','2026-07-24 10:29:14.924366'),
(144,'setting','0001_initial','2026-07-24 10:29:15.058079'),
(145,'setting','0002_alter_setting_id_alter_usersetting_id','2026-07-24 10:29:15.118490'),
(146,'signature','0001_initial','2026-07-24 10:29:15.161088'),
(147,'signature','0002_signatureusage','2026-07-24 10:29:15.249663'),
(148,'signature','0003_alter_accountsignature_id_alter_signatureusage_id','2026-07-24 10:29:15.313469'),
(149,'signature','0004_alter_accountsignature_assigned_at_and_more','2026-07-24 10:29:15.460141'),
(150,'upgrade','0001_initial','2026-07-24 10:29:15.917538'),
(151,'upgrade','0002_auto_20260627_0807','2026-07-24 10:29:16.089939'),
(152,'upgrade','0003_upgrade_attachment','2026-07-24 10:29:16.303235'),
(153,'upgrade','0004_merge_plan','2026-07-24 10:29:16.506626'),
(154,'upgrade','0005_drop_upgrade_attachment','2026-07-24 10:29:16.519616'),
(155,'upgrade','0006_status_log','2026-07-24 10:29:16.577144'),
(156,'upgrade','0007_step_phase','2026-07-24 10:29:16.624154'),
(157,'upgrade','0008_status_log_flow','2026-07-24 10:29:16.735579'),
(158,'upgrade','0009_status_log_action_labels','2026-07-24 10:29:16.741941'),
(159,'upgrade','0010_alter_upgradestatuslog_action','2026-07-24 10:29:16.748279'),
(160,'upgrade','0011_record_create_fields','2026-07-24 10:29:17.030041'),
(161,'upgrade','0012_upgrade_system','2026-07-24 10:29:17.180539'),
(162,'upgrade','0013_upgradeplanstep_upg_plan_tenant_seq_idx_and_more','2026-07-24 10:29:17.466418'),
(163,'upgrade','0014_tenant_isolate_upgrade_systems','2026-07-24 10:29:17.507568'),
(164,'upgrade','0015_alter_upgradeplanstep_id_alter_upgraderecord_id_and_more','2026-07-24 10:29:17.750710'),
(165,'upgrade','0016_alter_upgradeplanstep_created_at_and_more','2026-07-24 10:29:18.302813');
/*!40000 ALTER TABLE `django_migrations` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `django_session`
--

DROP TABLE IF EXISTS `django_session`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `django_session` (
  `session_key` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `session_data` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `expire_date` datetime(6) NOT NULL,
  PRIMARY KEY (`session_key`),
  KEY `django_session_expire_date_a5c62663` (`expire_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `django_session`
--

LOCK TABLES `django_session` WRITE;
/*!40000 ALTER TABLE `django_session` DISABLE KEYS */;
/*!40000 ALTER TABLE `django_session` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `login_histories`
--

DROP TABLE IF EXISTS `login_histories`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `login_histories` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `username` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `type` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `ip` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `agent` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `message` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_success` tinyint(1) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `login_histories`
--

LOCK TABLES `login_histories` WRITE;
/*!40000 ALTER TABLE `login_histories` DISABLE KEYS */;
/*!40000 ALTER TABLE `login_histories` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `navigations`
--

DROP TABLE IF EXISTS `navigations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `navigations` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `title` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `desc` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `logo` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `links` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `sort_id` int(11) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `navigations_sort_id_774e1730` (`sort_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `navigations`
--

LOCK TABLES `navigations` WRITE;
/*!40000 ALTER TABLE `navigations` DISABLE KEYS */;
/*!40000 ALTER TABLE `navigations` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `notices`
--

DROP TABLE IF EXISTS `notices`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `notices` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `title` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `content` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_stress` tinyint(1) NOT NULL,
  `read_ids` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `sort_id` int(11) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `notices_sort_id_353baeb9` (`sort_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `notices`
--

LOCK TABLES `notices` WRITE;
/*!40000 ALTER TABLE `notices` DISABLE KEYS */;
/*!40000 ALTER TABLE `notices` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `roles`
--

DROP TABLE IF EXISTS `roles`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `roles` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `desc` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `page_perms` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `deploy_perms` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `group_perms` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_global_admin` tinyint(1) NOT NULL DEFAULT 0,
  `created_at` datetime(6) NOT NULL,
  `created_by_id` bigint(20) NOT NULL,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_system` tinyint(1) NOT NULL,
  `perms_version` int(10) unsigned NOT NULL CHECK (`perms_version` >= 0),
  PRIMARY KEY (`id`),
  KEY `roles_tenant_id_2f74b73b` (`tenant_id`),
  KEY `roles_is_system_a18c3012` (`is_system`),
  KEY `roles_perms_version_922740e7` (`perms_version`),
  KEY `roles_created_by_id_4f97b4da_fk` (`created_by_id`),
  CONSTRAINT `roles_created_by_id_4f97b4da_fk` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `roles`
--

LOCK TABLES `roles` WRITE;
/*!40000 ALTER TABLE `roles` DISABLE KEYS */;
/*!40000 ALTER TABLE `roles` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `settings`
--

DROP TABLE IF EXISTS `settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `settings` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `key` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `desc` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `key` (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `settings`
--

LOCK TABLES `settings` WRITE;
/*!40000 ALTER TABLE `settings` DISABLE KEYS */;
/*!40000 ALTER TABLE `settings` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_account_signatures`
--

DROP TABLE IF EXISTS `tdyw_account_signatures`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_account_signatures` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_id` bigint(20) NOT NULL,
  `current_attachment_id` bigint(20) DEFAULT NULL,
  `version` int(10) unsigned NOT NULL CHECK (`version` >= 0),
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `assigned_by_id` bigint(20) DEFAULT NULL,
  `assigned_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `assigned_at` datetime(6) NOT NULL,
  `disabled_by_id` bigint(20) DEFAULT NULL,
  `disabled_by_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `disabled_at` datetime(6) DEFAULT NULL,
  `remark` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `user_id` (`user_id`),
  KEY `sig_tenant_status_idx` (`tenant_id`,`status`),
  KEY `tdyw_account_signatures_tenant_id_f02b94d8` (`tenant_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_account_signatures`
--

LOCK TABLES `tdyw_account_signatures` WRITE;
/*!40000 ALTER TABLE `tdyw_account_signatures` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_account_signatures` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_announcement_reads`
--

DROP TABLE IF EXISTS `tdyw_announcement_reads`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_announcement_reads` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_id` int(11) NOT NULL,
  `username` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `nickname` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `read_at` datetime(6) NOT NULL,
  `announcement_id` bigint(20) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_announcement_read_user` (`announcement_id`,`user_id`),
  KEY `ann_read_user_idx` (`user_id`,`announcement_id`),
  KEY `ann_read_notice_idx` (`announcement_id`,`user_id`),
  CONSTRAINT `tdyw_announcement_reads_announcement_id_b39bad9c_fk` FOREIGN KEY (`announcement_id`) REFERENCES `tdyw_announcements` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_announcement_reads`
--

LOCK TABLES `tdyw_announcement_reads` WRITE;
/*!40000 ALTER TABLE `tdyw_announcement_reads` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_announcement_reads` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_announcement_scopes`
--

DROP TABLE IF EXISTS `tdyw_announcement_scopes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_announcement_scopes` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `tenant_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `announcement_id` bigint(20) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_announcement_scope_tenant` (`announcement_id`,`tenant_id`),
  KEY `ann_scope_tenant_idx` (`tenant_id`),
  CONSTRAINT `tdyw_announcement_scopes_announcement_id_f0f661d0_fk` FOREIGN KEY (`announcement_id`) REFERENCES `tdyw_announcements` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_announcement_scopes`
--

LOCK TABLES `tdyw_announcement_scopes` WRITE;
/*!40000 ALTER TABLE `tdyw_announcement_scopes` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_announcement_scopes` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_announcements`
--

DROP TABLE IF EXISTS `tdyw_announcements`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_announcements` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `title` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `content` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `scope_type` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `publish_department_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `publish_department_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `effective_start_at` datetime(6) NOT NULL,
  `effective_end_at` datetime(6) DEFAULT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `published_at` datetime(6) DEFAULT NULL,
  `published_by_id` int(11) DEFAULT NULL,
  `published_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `withdrawn_at` datetime(6) DEFAULT NULL,
  `withdrawn_by_id` int(11) DEFAULT NULL,
  `withdrawn_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_important` tinyint(1) NOT NULL,
  `is_deleted` tinyint(1) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `created_by_id` int(11) DEFAULT NULL,
  `created_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `updated_at` datetime(6) DEFAULT NULL,
  `updated_by_id` int(11) DEFAULT NULL,
  `updated_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `deleted_at` datetime(6) DEFAULT NULL,
  `deleted_by_id` int(11) DEFAULT NULL,
  `deleted_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ann_status_time_idx` (`status`,`published_at`,`id`),
  KEY `ann_scope_idx` (`scope_type`,`status`),
  KEY `ann_pub_dept_idx` (`publish_department_id`,`published_at`),
  KEY `ann_effective_idx` (`effective_start_at`,`effective_end_at`),
  KEY `ann_deleted_idx` (`is_deleted`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_announcements`
--

LOCK TABLES `tdyw_announcements` WRITE;
/*!40000 ALTER TABLE `tdyw_announcements` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_announcements` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_checksheet_daily_summary`
--

DROP TABLE IF EXISTS `tdyw_checksheet_daily_summary`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_checksheet_daily_summary` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `year` varchar(4) COLLATE utf8mb4_unicode_ci NOT NULL,
  `month` varchar(2) COLLATE utf8mb4_unicode_ci NOT NULL,
  `day` int(11) NOT NULL,
  `operator` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `remark` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `rectification` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `operator_user_id` int(11) DEFAULT NULL,
  `operator_name_snapshot` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `tdyw_checksheet_daily_summary_year_month_day_e53924fb_uniq` (`year`,`month`,`day`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_checksheet_daily_summary`
--

LOCK TABLES `tdyw_checksheet_daily_summary` WRITE;
/*!40000 ALTER TABLE `tdyw_checksheet_daily_summary` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_checksheet_daily_summary` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_checksheet_record`
--

DROP TABLE IF EXISTS `tdyw_checksheet_record`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_checksheet_record` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `year` varchar(4) COLLATE utf8mb4_unicode_ci NOT NULL,
  `month` varchar(2) COLLATE utf8mb4_unicode_ci NOT NULL,
  `day` int(11) NOT NULL,
  `item_index` int(11) NOT NULL,
  `status` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `remark` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `rectification` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `operator` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `template_id` bigint(20) NOT NULL,
  `operator_user_id` int(11) DEFAULT NULL,
  `operator_name_snapshot` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `operator_department_snapshot` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `submitted_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `tdyw_checksheet_record_template_id_year_month_d_d4a1f0cb_uniq` (`template_id`,`year`,`month`,`day`,`item_index`),
  CONSTRAINT `tdyw_checksheet_record_template_id_2097b6bc_fk` FOREIGN KEY (`template_id`) REFERENCES `tdyw_checksheet_template` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_checksheet_record`
--

LOCK TABLES `tdyw_checksheet_record` WRITE;
/*!40000 ALTER TABLE `tdyw_checksheet_record` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_checksheet_record` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_checksheet_submission`
--

DROP TABLE IF EXISTS `tdyw_checksheet_submission`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_checksheet_submission` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `project` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `year` varchar(4) COLLATE utf8mb4_unicode_ci NOT NULL,
  `month` varchar(2) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `submitted_by_id` int(11) DEFAULT NULL,
  `submitted_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `submitted_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `reviewed_by_id` int(11) DEFAULT NULL,
  `reviewed_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `reviewed_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `review_comment` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `voided_by_id` int(11) DEFAULT NULL,
  `voided_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `voided_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `void_reason` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `snapshot_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `cs_sub_obj_idx` (`tenant_id`,`project`,`year`,`month`),
  KEY `cs_sub_status_idx` (`tenant_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_checksheet_submission`
--

LOCK TABLES `tdyw_checksheet_submission` WRITE;
/*!40000 ALTER TABLE `tdyw_checksheet_submission` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_checksheet_submission` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_checksheet_template`
--

DROP TABLE IF EXISTS `tdyw_checksheet_template`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_checksheet_template` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `project` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `check_items` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `tdyw_checksheet_template_project_58bbbbbb_uniq` (`project`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_checksheet_template`
--

LOCK TABLES `tdyw_checksheet_template` WRITE;
/*!40000 ALTER TABLE `tdyw_checksheet_template` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_checksheet_template` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_contract_agreement`
--

DROP TABLE IF EXISTS `tdyw_contract_agreement`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_contract_agreement` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `contract_name` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `contract_type` varchar(30) COLLATE utf8mb4_unicode_ci NOT NULL,
  `valid_start_date` date NOT NULL,
  `valid_end_date` date NOT NULL,
  `has_fee` tinyint(1) NOT NULL,
  `fee_amount` decimal(12,2) DEFAULT NULL,
  `fee_currency` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `fee_detail` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `signing_party` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `remark` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `last_remind_at` datetime(6) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) DEFAULT NULL,
  `created_by_id` bigint(20) NOT NULL,
  `updated_by_id` bigint(20) DEFAULT NULL,
  `responsible_user_id` int(11) DEFAULT NULL,
  `responsible_user_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_contra_tenant_8811a0_idx` (`tenant_id`,`created_at` DESC,`id` DESC),
  KEY `tdyw_contra_tenant_f8adba_idx` (`tenant_id`,`contract_type`),
  KEY `tdyw_contra_tenant_1880dc_idx` (`tenant_id`,`status`),
  KEY `tdyw_contra_tenant_f97a10_idx` (`tenant_id`,`valid_end_date`),
  KEY `tdyw_contra_tenant_a34e30_idx` (`tenant_id`,`has_fee`),
  KEY `tdyw_contract_agreement_created_by_id_a9224bad_fk_users_id` (`created_by_id`),
  KEY `tdyw_contract_agreement_updated_by_id_b7f0b70d_fk_users_id` (`updated_by_id`),
  CONSTRAINT `tdyw_contract_agreement_created_by_id_a9224bad_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_contract_agreement_updated_by_id_b7f0b70d_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_contract_agreement`
--

LOCK TABLES `tdyw_contract_agreement` WRITE;
/*!40000 ALTER TABLE `tdyw_contract_agreement` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_contract_agreement` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_contract_agreement_reminder_ack`
--

DROP TABLE IF EXISTS `tdyw_contract_agreement_reminder_ack`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_contract_agreement_reminder_ack` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_id` int(11) NOT NULL,
  `user_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `ack_valid_to` date NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `agreement_id` bigint(20) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_contract_user_valid_end` (`tenant_id`,`agreement_id`,`user_id`,`ack_valid_to`),
  KEY `tdyw_cara_user_idx` (`tenant_id`,`user_id`,`agreement_id`),
  KEY `tdyw_contract_agreement_reminder_ack_agreement_id_b6059f55_fk` (`agreement_id`),
  CONSTRAINT `tdyw_contract_agreement_reminder_ack_agreement_id_b6059f55_fk` FOREIGN KEY (`agreement_id`) REFERENCES `tdyw_contract_agreement` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_contract_agreement_reminder_ack`
--

LOCK TABLES `tdyw_contract_agreement_reminder_ack` WRITE;
/*!40000 ALTER TABLE `tdyw_contract_agreement_reminder_ack` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_contract_agreement_reminder_ack` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_department_duty_log`
--

DROP TABLE IF EXISTS `tdyw_department_duty_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_department_duty_log` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `duty_date` date NOT NULL,
  `duty_person_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `mains_voltage` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `ups_voltage` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `weather` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `duty_record` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `remark` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `version` int(10) unsigned NOT NULL CHECK (`version` >= 0),
  `signature_usage_id` bigint(20) DEFAULT NULL,
  `signed_by_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `signed_at` datetime(6) DEFAULT NULL,
  `signature_version` int(10) unsigned DEFAULT NULL CHECK (`signature_version` >= 0),
  `signature_sha256` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `business_snapshot_hash` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) DEFAULT NULL,
  `deleted_at` datetime(6) DEFAULT NULL,
  `voided_at` datetime(6) DEFAULT NULL,
  `void_reason` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_by_id` bigint(20) NOT NULL,
  `deleted_by_id` bigint(20) DEFAULT NULL,
  `duty_person_id` bigint(20) NOT NULL,
  `signed_by_id` bigint(20) DEFAULT NULL,
  `supersedes_id` bigint(20) DEFAULT NULL,
  `updated_by_id` bigint(20) DEFAULT NULL,
  `voided_by_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `signature_usage_id` (`signature_usage_id`),
  KEY `tdyw_department_duty_log_created_by_id_04d77a74_fk_users_id` (`created_by_id`),
  KEY `tdyw_department_duty_log_deleted_by_id_598a8c60_fk_users_id` (`deleted_by_id`),
  KEY `tdyw_department_duty_log_signed_by_id_e758d328_fk_users_id` (`signed_by_id`),
  KEY `tdyw_department_duty_log_updated_by_id_1e58b0a9_fk_users_id` (`updated_by_id`),
  KEY `tdyw_department_duty_log_voided_by_id_4d503202_fk_users_id` (`voided_by_id`),
  KEY `department_duty_status_date_ix` (`status`,`deleted_at`,`duty_date`),
  KEY `department_duty_person_date_ix` (`duty_person_id`,`duty_date`),
  KEY `tdyw_department_duty_log_supersedes_id_53ea537c_fk` (`supersedes_id`),
  CONSTRAINT `tdyw_department_duty_log_created_by_id_04d77a74_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_department_duty_log_deleted_by_id_598a8c60_fk_users_id` FOREIGN KEY (`deleted_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_department_duty_log_duty_person_id_fa758da0_fk_users_id` FOREIGN KEY (`duty_person_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_department_duty_log_signed_by_id_e758d328_fk_users_id` FOREIGN KEY (`signed_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_department_duty_log_supersedes_id_53ea537c_fk` FOREIGN KEY (`supersedes_id`) REFERENCES `tdyw_department_duty_log` (`id`),
  CONSTRAINT `tdyw_department_duty_log_updated_by_id_1e58b0a9_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_department_duty_log_voided_by_id_4d503202_fk_users_id` FOREIGN KEY (`voided_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_department_duty_log`
--

LOCK TABLES `tdyw_department_duty_log` WRITE;
/*!40000 ALTER TABLE `tdyw_department_duty_log` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_department_duty_log` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_device_event`
--

DROP TABLE IF EXISTS `tdyw_device_event`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_device_event` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `device_resume_id` int(11) NOT NULL,
  `device_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `device_sn` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `event_type` int(11) NOT NULL,
  `event_time` datetime(6) DEFAULT NULL,
  `event_title` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `fault_part` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `fault_phenomenon_cause` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `maintenance_measures` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `related_user_id` int(11) DEFAULT NULL,
  `related_user_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `repair_time` datetime(6) DEFAULT NULL,
  `remark` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_deleted` tinyint(1) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `created_by_id` bigint(20) NOT NULL,
  `correction_event_id` int(11) DEFAULT NULL,
  `correction_reason` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `corrected_by_id` int(11) DEFAULT NULL,
  `corrected_at` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_device_tenant__808d01_idx` (`tenant_id`,`device_resume_id`),
  KEY `tdyw_device_tenant__384ccf_idx` (`tenant_id`,`event_time` DESC,`id` DESC),
  KEY `tdyw_device_event_created_by_id_138c4387_fk_users_id` (`created_by_id`),
  CONSTRAINT `tdyw_device_event_created_by_id_138c4387_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_device_event`
--

LOCK TABLES `tdyw_device_event` WRITE;
/*!40000 ALTER TABLE `tdyw_device_event` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_device_event` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_device_resume`
--

DROP TABLE IF EXISTS `tdyw_device_resume`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_device_resume` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `device_sn` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `device_name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `device_model` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `frequency` varchar(30) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `call_sign` varchar(30) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `install_location` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `geo_coordinate` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `device_purpose` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `manufacturer` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `install_unit` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `use_unit` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `install_time` datetime(6) DEFAULT NULL,
  `enable_time` datetime(6) DEFAULT NULL,
  `current_status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `responsible_user_id` int(11) DEFAULT NULL,
  `responsible_user_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `remark` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_deleted` tinyint(1) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) DEFAULT NULL,
  `created_by_id` bigint(20) NOT NULL,
  `updated_by_id` bigint(20) DEFAULT NULL,
  `deleted_at` datetime(6) DEFAULT NULL,
  `deleted_by_id` int(11) DEFAULT NULL,
  `delete_reason` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `snapshot_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_device_resume_tenant_sn` (`tenant_id`,`device_sn`),
  KEY `tdyw_device_tenant__c5b9c0_idx` (`tenant_id`,`current_status`),
  KEY `tdyw_device_tenant__817230_idx` (`tenant_id`,`created_at` DESC,`id` DESC),
  KEY `tdyw_device_resume_created_by_id_127d521e_fk_users_id` (`created_by_id`),
  KEY `tdyw_device_resume_updated_by_id_6f5b1b07_fk_users_id` (`updated_by_id`),
  CONSTRAINT `tdyw_device_resume_created_by_id_127d521e_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_device_resume_updated_by_id_6f5b1b07_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_device_resume`
--

LOCK TABLES `tdyw_device_resume` WRITE;
/*!40000 ALTER TABLE `tdyw_device_resume` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_device_resume` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_document_file_private`
--

DROP TABLE IF EXISTS `tdyw_document_file_private`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_document_file_private` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `physical_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `file_path` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `display_name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `file_size` bigint(20) NOT NULL,
  `file_type` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_deleted` tinyint(1) NOT NULL,
  `deleted_at` datetime(6) DEFAULT NULL,
  `is_pending_clean` tinyint(1) NOT NULL,
  `clean_retry_count` int(11) NOT NULL,
  `last_clean_attempt` datetime(6) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `created_by_id` bigint(20) DEFAULT NULL,
  `folder_id` bigint(20) DEFAULT NULL,
  `thumbnail_path` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_document_file_private_created_by_id_da16bed4_fk_users_id` (`created_by_id`),
  KEY `doc_pri_file_list_idx` (`folder_id`,`tenant_id`,`is_deleted`,`created_at` DESC,`id` DESC),
  KEY `doc_pri_file_diskusage_idx` (`tenant_id`,`is_deleted`,`file_size`),
  CONSTRAINT `tdyw_document_file_private_created_by_id_da16bed4_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_document_file_private_folder_id_55c2e9b4_fk` FOREIGN KEY (`folder_id`) REFERENCES `tdyw_document_folder_private` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_document_file_private`
--

LOCK TABLES `tdyw_document_file_private` WRITE;
/*!40000 ALTER TABLE `tdyw_document_file_private` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_document_file_private` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_document_file_public`
--

DROP TABLE IF EXISTS `tdyw_document_file_public`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_document_file_public` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `physical_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `file_path` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `display_name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `file_size` bigint(20) NOT NULL,
  `file_type` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_deleted` tinyint(1) NOT NULL,
  `deleted_at` datetime(6) DEFAULT NULL,
  `is_pending_clean` tinyint(1) NOT NULL,
  `clean_retry_count` int(11) NOT NULL,
  `last_clean_attempt` datetime(6) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `created_by_id` bigint(20) DEFAULT NULL,
  `folder_id` bigint(20) DEFAULT NULL,
  `thumbnail_path` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_file_name_folder_public` (`name`,`folder_id`),
  KEY `tdyw_document_file_public_created_by_id_73d25980_fk_users_id` (`created_by_id`),
  KEY `doc_pub_file_list_idx` (`folder_id`,`is_deleted`,`created_at` DESC,`id` DESC),
  CONSTRAINT `tdyw_document_file_public_created_by_id_73d25980_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_document_file_public_folder_id_8cad2651_fk` FOREIGN KEY (`folder_id`) REFERENCES `tdyw_document_folder_public` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_document_file_public`
--

LOCK TABLES `tdyw_document_file_public` WRITE;
/*!40000 ALTER TABLE `tdyw_document_file_public` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_document_file_public` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_document_folder_private`
--

DROP TABLE IF EXISTS `tdyw_document_folder_private`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_document_folder_private` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `name` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `is_deleted` tinyint(1) NOT NULL,
  `deleted_at` datetime(6) DEFAULT NULL,
  `created_by_id` bigint(20) DEFAULT NULL,
  `deleted_by_id` bigint(20) DEFAULT NULL,
  `parent_id` bigint(20) DEFAULT NULL,
  `unique_key` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `tdyw_document_folder_private_unique_key_7e422acc_uniq` (`unique_key`),
  KEY `tdyw_document_folder_private_created_by_id_a82f201e_fk_users_id` (`created_by_id`),
  KEY `tdyw_document_folder_private_deleted_by_id_b6204bcd_fk_users_id` (`deleted_by_id`),
  KEY `tdyw_document_folder_private_unique_key_7e422acc` (`unique_key`),
  KEY `doc_pri_folder_list_idx` (`parent_id`,`tenant_id`,`is_deleted`,`created_at` DESC,`id` DESC),
  CONSTRAINT `tdyw_document_folder_private_created_by_id_a82f201e_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_document_folder_private_deleted_by_id_b6204bcd_fk_users_id` FOREIGN KEY (`deleted_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_document_folder_private_parent_id_fefe565e_fk` FOREIGN KEY (`parent_id`) REFERENCES `tdyw_document_folder_private` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_document_folder_private`
--

LOCK TABLES `tdyw_document_folder_private` WRITE;
/*!40000 ALTER TABLE `tdyw_document_folder_private` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_document_folder_private` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_document_folder_public`
--

DROP TABLE IF EXISTS `tdyw_document_folder_public`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_document_folder_public` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `name` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `is_deleted` tinyint(1) NOT NULL,
  `deleted_at` datetime(6) DEFAULT NULL,
  `created_by_id` bigint(20) DEFAULT NULL,
  `deleted_by_id` bigint(20) DEFAULT NULL,
  `parent_id` bigint(20) DEFAULT NULL,
  `unique_key` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `tdyw_document_folder_public_unique_key_e3b64f76_uniq` (`unique_key`),
  KEY `tdyw_document_folder_public_created_by_id_c9dfe5f1_fk_users_id` (`created_by_id`),
  KEY `tdyw_document_folder_public_deleted_by_id_295c5c49_fk_users_id` (`deleted_by_id`),
  KEY `tdyw_document_folder_public_unique_key_e3b64f76` (`unique_key`),
  KEY `doc_pub_folder_list_idx` (`parent_id`,`is_deleted`,`created_at` DESC,`id` DESC),
  CONSTRAINT `tdyw_document_folder_public_created_by_id_c9dfe5f1_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_document_folder_public_deleted_by_id_295c5c49_fk_users_id` FOREIGN KEY (`deleted_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_document_folder_public_parent_id_f19bc78b_fk` FOREIGN KEY (`parent_id`) REFERENCES `tdyw_document_folder_public` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_document_folder_public`
--

LOCK TABLES `tdyw_document_folder_public` WRITE;
/*!40000 ALTER TABLE `tdyw_document_folder_public` DISABLE KEYS */;
INSERT INTO `tdyw_document_folder_public` VALUES
(1,'党建文档','2026-07-24 10:29:19.328008','2026-07-24 10:29:19.328078',0,NULL,NULL,NULL,NULL,'56ddd015e49021d70f4101445cb830f4');
/*!40000 ALTER TABLE `tdyw_document_folder_public` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_document_system_folder`
--

DROP TABLE IF EXISTS `tdyw_document_system_folder`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_document_system_folder` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `code` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_public` tinyint(1) NOT NULL,
  `protected` tinyint(1) NOT NULL,
  `description` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `folder_id` bigint(20) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`),
  UNIQUE KEY `tdyw_document_system_folder_folder_id_ede5f15b_uniq` (`folder_id`),
  CONSTRAINT `tdyw_document_system_folder_folder_id_ede5f15b_fk` FOREIGN KEY (`folder_id`) REFERENCES `tdyw_document_folder_public` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_document_system_folder`
--

LOCK TABLES `tdyw_document_system_folder` WRITE;
/*!40000 ALTER TABLE `tdyw_document_system_folder` DISABLE KEYS */;
INSERT INTO `tdyw_document_system_folder` VALUES
(1,'party_building_documents','党建文档',1,1,'党建文档系统业务根目录，受保护不可删除/重命名/移动','2026-07-24 10:29:19.334648','2026-07-24 10:29:19.334667',1);
/*!40000 ALTER TABLE `tdyw_document_system_folder` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_document_transfer`
--

DROP TABLE IF EXISTS `tdyw_document_transfer`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_document_transfer` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `transfer_type` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `file_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `file_size` bigint(20) NOT NULL,
  `file_path` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `file_hash` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `folder_id` int(11) DEFAULT NULL,
  `is_public` tinyint(1) NOT NULL,
  `total_chunks` int(11) NOT NULL,
  `uploaded_chunks` int(11) NOT NULL,
  `progress` int(11) NOT NULL,
  `transferred_size` bigint(20) NOT NULL,
  `speed` double NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `started_at` datetime(6) DEFAULT NULL,
  `completed_at` datetime(6) DEFAULT NULL,
  `updated_at` datetime(6) NOT NULL,
  `error_message` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `celery_task_id` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `user_id` bigint(20) DEFAULT NULL,
  `system_folder` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_transfer_tenant_user` (`tenant_id`,`user_id`),
  KEY `idx_transfer_tenant_status` (`tenant_id`,`status`),
  KEY `idx_transfer_tenant_hash` (`tenant_id`,`file_hash`),
  KEY `idx_transfer_user_status` (`user_id`,`status`),
  KEY `idx_transfer_created` (`created_at`),
  KEY `tdyw_document_transfer_tenant_id_3892c6f8` (`tenant_id`),
  KEY `tdyw_document_transfer_transfer_type_6f1ea466` (`transfer_type`),
  KEY `tdyw_document_transfer_status_98dff9a8` (`status`),
  KEY `tdyw_document_transfer_file_hash_12bf949f` (`file_hash`),
  KEY `tdyw_document_transfer_created_at_ec5c97fa` (`created_at`),
  KEY `tdyw_document_transfer_celery_task_id_cd3e8a95` (`celery_task_id`),
  KEY `transfer_status_updated_idx` (`status`,`updated_at`),
  KEY `idx_transfer_user_scope` (`user_id`,`is_public`,`system_folder`),
  KEY `tdyw_document_transfer_system_folder_2b15f6c1` (`system_folder`),
  CONSTRAINT `tdyw_document_transfer_user_id_b48d001e_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_document_transfer`
--

LOCK TABLES `tdyw_document_transfer` WRITE;
/*!40000 ALTER TABLE `tdyw_document_transfer` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_document_transfer` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_duty_records`
--

DROP TABLE IF EXISTS `tdyw_duty_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_duty_records` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `duty_person` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `reporter` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `department` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `duty_date` datetime(6) DEFAULT NULL,
  `duty_situation` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) DEFAULT NULL,
  `created_by_id` bigint(20) NOT NULL,
  `updated_by_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_duty_records_created_by_id_31d37535_fk_users_id` (`created_by_id`),
  KEY `tdyw_duty_records_updated_by_id_5a23f6c5_fk_users_id` (`updated_by_id`),
  CONSTRAINT `tdyw_duty_records_created_by_id_31d37535_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_duty_records_updated_by_id_5a23f6c5_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_duty_records`
--

LOCK TABLES `tdyw_duty_records` WRITE;
/*!40000 ALTER TABLE `tdyw_duty_records` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_duty_records` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_evidence_attachments`
--

DROP TABLE IF EXISTS `tdyw_evidence_attachments`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_evidence_attachments` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `module` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `object_type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `object_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `file_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `file_path` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `file_size` bigint(20) NOT NULL,
  `file_ext` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `file_hash_sha256` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `file_hash_md5` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `uploaded_by_id` int(11) DEFAULT NULL,
  `uploaded_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_deleted` tinyint(1) NOT NULL,
  `deleted_by_id` int(11) DEFAULT NULL,
  `deleted_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `deleted_at` datetime(6) DEFAULT NULL,
  `delete_reason` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `uploaded_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ev_att_obj_idx` (`tenant_id`,`module`,`object_type`,`object_id`),
  KEY `ev_att_sha256_idx` (`file_hash_sha256`),
  KEY `ev_att_del_idx` (`tenant_id`,`is_deleted`),
  KEY `tdyw_evidence_attachments_file_hash_sha256_ae06487f` (`file_hash_sha256`),
  KEY `ev_att_obj_del_time_idx` (`tenant_id`,`module`,`object_type`,`object_id`,`is_deleted`,`uploaded_at`,`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_evidence_attachments`
--

LOCK TABLES `tdyw_evidence_attachments` WRITE;
/*!40000 ALTER TABLE `tdyw_evidence_attachments` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_evidence_attachments` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_evidence_events`
--

DROP TABLE IF EXISTS `tdyw_evidence_events`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_evidence_events` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `module` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `object_type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `object_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `event_type` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `event_title` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `actor_user_id` int(11) DEFAULT NULL,
  `actor_username` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `actor_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `actor_department` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `actor_ip` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `actor_device` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `object_snapshot` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `before_snapshot` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `after_snapshot` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `attachment_hashes` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `remark` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `prev_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `event_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `audit_log_id` int(11) DEFAULT NULL,
  `external_ts_provider` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `external_ts_token` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ev_obj_chain_idx` (`tenant_id`,`module`,`object_type`,`object_id`,`id` DESC),
  KEY `ev_obj_actor_idx` (`tenant_id`,`actor_user_id`),
  KEY `ev_obj_type_idx` (`tenant_id`,`event_type`),
  KEY `ev_event_hash_idx` (`event_hash`),
  KEY `tdyw_evidence_events_event_hash_8e32b2d0` (`event_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_evidence_events`
--

LOCK TABLES `tdyw_evidence_events` WRITE;
/*!40000 ALTER TABLE `tdyw_evidence_events` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_evidence_events` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_fault_parts`
--

DROP TABLE IF EXISTS `tdyw_fault_parts`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_fault_parts` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `system_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `date` datetime(6) DEFAULT NULL,
  `fault_date` datetime(6) DEFAULT NULL,
  `status` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `fault_sent_date` datetime(6) DEFAULT NULL,
  `test_return_date` datetime(6) DEFAULT NULL,
  `archive_date` datetime(6) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) DEFAULT NULL,
  `created_by_id` bigint(20) NOT NULL,
  `updated_by_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_fault_parts_created_by_id_c1ce4711_fk_users_id` (`created_by_id`),
  KEY `tdyw_fault_parts_updated_by_id_af731088_fk_users_id` (`updated_by_id`),
  CONSTRAINT `tdyw_fault_parts_created_by_id_c1ce4711_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_fault_parts_updated_by_id_af731088_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_fault_parts`
--

LOCK TABLES `tdyw_fault_parts` WRITE;
/*!40000 ALTER TABLE `tdyw_fault_parts` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_fault_parts` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_fault_records`
--

DROP TABLE IF EXISTS `tdyw_fault_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_fault_records` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `system_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `device_code` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `fault_date` datetime(6) DEFAULT NULL,
  `handler` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `recorder` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `fault_level` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `fault_phenomenon` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `handling_process` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) DEFAULT NULL,
  `created_by_id` bigint(20) NOT NULL,
  `updated_by_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_fault_records_created_by_id_6fa37dd7_fk_users_id` (`created_by_id`),
  KEY `tdyw_fault_records_updated_by_id_ac86ecbc_fk_users_id` (`updated_by_id`),
  CONSTRAINT `tdyw_fault_records_created_by_id_6fa37dd7_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_fault_records_updated_by_id_ac86ecbc_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_fault_records`
--

LOCK TABLES `tdyw_fault_records` WRITE;
/*!40000 ALTER TABLE `tdyw_fault_records` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_fault_records` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_interferences`
--

DROP TABLE IF EXISTS `tdyw_interferences`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_interferences` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `serial_number` int(11) NOT NULL,
  `frequency` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `report_dept` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `datetime` datetime(6) DEFAULT NULL,
  `coordinates` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `interference_type` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `phenomenon` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `flight_number` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `aircraft_type` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_reported` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) DEFAULT NULL,
  `created_by_id` bigint(20) NOT NULL,
  `updated_by_id` bigint(20) DEFAULT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `submitted_by_id` int(11) DEFAULT NULL,
  `submitted_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `submitted_at` datetime(6) DEFAULT NULL,
  `reviewed_by_id` int(11) DEFAULT NULL,
  `reviewed_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `reviewed_at` datetime(6) DEFAULT NULL,
  `review_comment` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `reported_at` datetime(6) DEFAULT NULL,
  `reported_by_id` int(11) DEFAULT NULL,
  `reported_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `report_channel` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `report_no` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `handled_by_id` int(11) DEFAULT NULL,
  `handled_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `handled_at` datetime(6) DEFAULT NULL,
  `closed_by_id` int(11) DEFAULT NULL,
  `closed_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `closed_at` datetime(6) DEFAULT NULL,
  `close_summary` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `voided_by_id` int(11) DEFAULT NULL,
  `voided_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `voided_at` datetime(6) DEFAULT NULL,
  `void_reason` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `snapshot_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_interferences_created_by_id_395767df_fk_users_id` (`created_by_id`),
  KEY `tdyw_interferences_updated_by_id_c34acb4f_fk_users_id` (`updated_by_id`),
  KEY `inter_status_idx` (`tenant_id`,`status`),
  KEY `inter_time_idx` (`tenant_id`,`datetime` DESC,`id` DESC),
  CONSTRAINT `tdyw_interferences_created_by_id_395767df_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_interferences_updated_by_id_c34acb4f_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_interferences`
--

LOCK TABLES `tdyw_interferences` WRITE;
/*!40000 ALTER TABLE `tdyw_interferences` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_interferences` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_radio_license`
--

DROP TABLE IF EXISTS `tdyw_radio_license`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_radio_license` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `station_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `purpose` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `valid_from` date NOT NULL,
  `valid_to` date NOT NULL,
  `responsible_user_id` int(11) DEFAULT NULL,
  `responsible_user_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `last_remind_at` datetime(6) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) DEFAULT NULL,
  `created_by_id` bigint(20) NOT NULL,
  `updated_by_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_radio__tenant__f59744_idx` (`tenant_id`,`created_at` DESC,`id` DESC),
  KEY `tdyw_radio__tenant__fe3ab2_idx` (`tenant_id`,`valid_to`),
  KEY `tdyw_radio_license_created_by_id_9c1683e2_fk_users_id` (`created_by_id`),
  KEY `tdyw_radio_license_updated_by_id_5c284e46_fk_users_id` (`updated_by_id`),
  CONSTRAINT `tdyw_radio_license_created_by_id_9c1683e2_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_radio_license_updated_by_id_5c284e46_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_radio_license`
--

LOCK TABLES `tdyw_radio_license` WRITE;
/*!40000 ALTER TABLE `tdyw_radio_license` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_radio_license` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_radio_license_frequency`
--

DROP TABLE IF EXISTS `tdyw_radio_license_frequency`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_radio_license_frequency` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `frequency_value` decimal(12,4) NOT NULL,
  `frequency_unit` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `frequency_text` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `remark` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `sort_order` int(11) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `created_by_id` bigint(20) NOT NULL,
  `license_id` bigint(20) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_radio__tenant__b1deda_idx` (`tenant_id`,`license_id`),
  KEY `tdyw_radio_license_frequency_created_by_id_975f95ee_fk_users_id` (`created_by_id`),
  KEY `tdyw_radio_license_frequency_license_id_46b405e3_fk` (`license_id`),
  CONSTRAINT `tdyw_radio_license_frequency_created_by_id_975f95ee_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_radio_license_frequency_license_id_46b405e3_fk` FOREIGN KEY (`license_id`) REFERENCES `tdyw_radio_license` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_radio_license_frequency`
--

LOCK TABLES `tdyw_radio_license_frequency` WRITE;
/*!40000 ALTER TABLE `tdyw_radio_license_frequency` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_radio_license_frequency` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_radio_license_reminder_ack`
--

DROP TABLE IF EXISTS `tdyw_radio_license_reminder_ack`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_radio_license_reminder_ack` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_id` int(11) NOT NULL,
  `user_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `ack_valid_to` date NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `license_id` bigint(20) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_license_user_valid_to` (`tenant_id`,`license_id`,`user_id`,`ack_valid_to`),
  KEY `tdyw_rlra_user_idx` (`tenant_id`,`user_id`,`license_id`),
  KEY `tdyw_radio_license_reminder_ack_license_id_3d8b0fd9_fk` (`license_id`),
  CONSTRAINT `tdyw_radio_license_reminder_ack_license_id_3d8b0fd9_fk` FOREIGN KEY (`license_id`) REFERENCES `tdyw_radio_license` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_radio_license_reminder_ack`
--

LOCK TABLES `tdyw_radio_license_reminder_ack` WRITE;
/*!40000 ALTER TABLE `tdyw_radio_license_reminder_ack` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_radio_license_reminder_ack` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_radio_license_version`
--

DROP TABLE IF EXISTS `tdyw_radio_license_version`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_radio_license_version` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `version_no` int(11) NOT NULL,
  `snapshot_json` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `changed_fields` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `change_reason` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `changed_by_id` int(11) DEFAULT NULL,
  `changed_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `changed_at` datetime(6) DEFAULT NULL,
  `snapshot_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `license_id` bigint(20) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `rl_ver_license_idx` (`tenant_id`,`license_id`),
  KEY `tdyw_radio_license_version_license_id_64a2a20f_fk` (`license_id`),
  CONSTRAINT `tdyw_radio_license_version_license_id_64a2a20f_fk` FOREIGN KEY (`license_id`) REFERENCES `tdyw_radio_license` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_radio_license_version`
--

LOCK TABLES `tdyw_radio_license_version` WRITE;
/*!40000 ALTER TABLE `tdyw_radio_license_version` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_radio_license_version` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_regulation`
--

DROP TABLE IF EXISTS `tdyw_regulation`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_regulation` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `title` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `rule_no` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `issuing_authority` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `biz_type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `publish_date` date DEFAULT NULL,
  `effective_date` date DEFAULT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `updated_at` datetime(6) DEFAULT NULL,
  `category_id` bigint(20) DEFAULT NULL,
  `updated_by_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_regulation_updated_by_id_f7798d99_fk_users_id` (`updated_by_id`),
  KEY `reg_rule_no_idx` (`rule_no`),
  KEY `reg_issue_auth_idx` (`issuing_authority`),
  KEY `reg_biz_type_idx` (`biz_type`),
  KEY `reg_status_idx` (`status`),
  KEY `tdyw_regulation_rule_no_b2b666ad` (`rule_no`),
  KEY `tdyw_regulation_issuing_authority_69284b72` (`issuing_authority`),
  KEY `tdyw_regulation_biz_type_323a86a5` (`biz_type`),
  KEY `tdyw_regulation_effective_date_5512486f` (`effective_date`),
  KEY `tdyw_regulation_status_cca33950` (`status`),
  KEY `tdyw_regulation_category_id_4b63fcea_fk` (`category_id`),
  CONSTRAINT `tdyw_regulation_category_id_4b63fcea_fk` FOREIGN KEY (`category_id`) REFERENCES `tdyw_regulation_category` (`id`),
  CONSTRAINT `tdyw_regulation_updated_by_id_f7798d99_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_regulation`
--

LOCK TABLES `tdyw_regulation` WRITE;
/*!40000 ALTER TABLE `tdyw_regulation` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_regulation` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_regulation_attachment`
--

DROP TABLE IF EXISTS `tdyw_regulation_attachment`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_regulation_attachment` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `original_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `stored_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `file_path` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `file_size` bigint(20) NOT NULL,
  `file_type` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `file_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `sort_order` int(11) NOT NULL,
  `uploaded_at` datetime(6) NOT NULL,
  `is_deleted` tinyint(1) NOT NULL,
  `deleted_at` datetime(6) DEFAULT NULL,
  `deleted_by_id` bigint(20) DEFAULT NULL,
  `regulation_id` bigint(20) NOT NULL,
  `uploaded_by_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `reg_att_list_idx` (`regulation_id`,`is_deleted`,`sort_order`),
  KEY `tdyw_regulation_attachment_deleted_by_id_1b3049ec_fk_users_id` (`deleted_by_id`),
  KEY `tdyw_regulation_attachment_uploaded_by_id_f599fe28_fk_users_id` (`uploaded_by_id`),
  KEY `tdyw_regulation_attachment_file_hash_4a181300` (`file_hash`),
  KEY `tdyw_regulation_attachment_is_deleted_d4907495` (`is_deleted`),
  CONSTRAINT `tdyw_regulation_attachment_deleted_by_id_1b3049ec_fk_users_id` FOREIGN KEY (`deleted_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_regulation_attachment_regulation_id_fab5d817_fk` FOREIGN KEY (`regulation_id`) REFERENCES `tdyw_regulation` (`id`),
  CONSTRAINT `tdyw_regulation_attachment_uploaded_by_id_f599fe28_fk_users_id` FOREIGN KEY (`uploaded_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_regulation_attachment`
--

LOCK TABLES `tdyw_regulation_attachment` WRITE;
/*!40000 ALTER TABLE `tdyw_regulation_attachment` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_regulation_attachment` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_regulation_category`
--

DROP TABLE IF EXISTS `tdyw_regulation_category`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_regulation_category` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `sort_order` int(11) NOT NULL,
  `code` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_leaf` tinyint(1) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `created_by_id` bigint(20) DEFAULT NULL,
  `parent_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `reg_cat_parent_sort_idx` (`parent_id`,`sort_order`),
  KEY `tdyw_regulation_category_created_by_id_f5d54f47_fk_users_id` (`created_by_id`),
  CONSTRAINT `tdyw_regulation_category_created_by_id_f5d54f47_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_regulation_category_parent_id_dee77160_fk` FOREIGN KEY (`parent_id`) REFERENCES `tdyw_regulation_category` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_regulation_category`
--

LOCK TABLES `tdyw_regulation_category` WRITE;
/*!40000 ALTER TABLE `tdyw_regulation_category` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_regulation_category` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_run_log_event_types`
--

DROP TABLE IF EXISTS `tdyw_run_log_event_types`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_run_log_event_types` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `created_by_id` bigint(20) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`),
  KEY `tdyw_run_log_event_types_created_by_id_d4fc324a_fk_users_id` (`created_by_id`),
  KEY `tdyw_run_lo_is_acti_02d1c0_idx` (`is_active`),
  CONSTRAINT `tdyw_run_log_event_types_created_by_id_d4fc324a_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_run_log_event_types`
--

LOCK TABLES `tdyw_run_log_event_types` WRITE;
/*!40000 ALTER TABLE `tdyw_run_log_event_types` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_run_log_event_types` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_run_log_updates`
--

DROP TABLE IF EXISTS `tdyw_run_log_updates`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_run_log_updates` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `runlog_id` int(11) NOT NULL,
  `event_title` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `update_date` date NOT NULL,
  `sequence` int(11) NOT NULL,
  `recorder` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `detail_content` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `attachments` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `editable_until` datetime(6) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `created_by_id` bigint(20) NOT NULL,
  `duty_person` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `update_type` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `corrected_update_id` int(11) DEFAULT NULL,
  `is_voided` tinyint(1) NOT NULL,
  `void_reason` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_run_lo_runlog__f96268_idx` (`runlog_id`),
  KEY `tdyw_run_lo_tenant__ef3bce_idx` (`tenant_id`,`runlog_id`),
  KEY `tdyw_run_lo_update__bbd520_idx` (`update_date`),
  KEY `tdyw_run_log_updates_created_by_id_94de19d6_fk_users_id` (`created_by_id`),
  CONSTRAINT `tdyw_run_log_updates_created_by_id_94de19d6_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_run_log_updates`
--

LOCK TABLES `tdyw_run_log_updates` WRITE;
/*!40000 ALTER TABLE `tdyw_run_log_updates` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_run_log_updates` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_run_logs`
--

DROP TABLE IF EXISTS `tdyw_run_logs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_run_logs` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `event_title` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `event_type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `system_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `severity` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `responsible_user_id` int(11) DEFAULT NULL,
  `responsible_user_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `resolution` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `verifier_id` int(11) DEFAULT NULL,
  `verifier_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `verified_at` datetime(6) DEFAULT NULL,
  `closed_at` datetime(6) DEFAULT NULL,
  `update_count` int(11) NOT NULL,
  `first_update_date` date DEFAULT NULL,
  `last_update_date` date DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) DEFAULT NULL,
  `created_by_id` bigint(20) NOT NULL,
  `updated_by_id` bigint(20) DEFAULT NULL,
  `snapshot_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `verified_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_run_lo_tenant__8c613c_idx` (`tenant_id`,`status`),
  KEY `tdyw_run_lo_tenant__c21b90_idx` (`tenant_id`,`severity`),
  KEY `tdyw_run_logs_created_by_id_4d650d4b_fk_users_id` (`created_by_id`),
  KEY `tdyw_run_logs_updated_by_id_4408a70b_fk_users_id` (`updated_by_id`),
  CONSTRAINT `tdyw_run_logs_created_by_id_4d650d4b_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_run_logs_updated_by_id_4408a70b_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_run_logs`
--

LOCK TABLES `tdyw_run_logs` WRITE;
/*!40000 ALTER TABLE `tdyw_run_logs` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_run_logs` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_signature_usages`
--

DROP TABLE IF EXISTS `tdyw_signature_usages`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_signature_usages` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `module` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `object_type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `object_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `scene_code` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `signer_user_id` bigint(20) NOT NULL,
  `signer_username` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `signer_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `signature_attachment_id` bigint(20) NOT NULL,
  `signature_version` int(10) unsigned NOT NULL CHECK (`signature_version` >= 0),
  `signature_sha256` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `business_snapshot` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `business_snapshot_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `signed_at` datetime(6) NOT NULL,
  `signer_ip` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `request_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `request_fingerprint` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `evidence_event_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `sig_usage_tenant_request_uniq` (`tenant_id`,`request_id`),
  KEY `sig_usage_obj_idx` (`tenant_id`,`module`,`object_type`,`object_id`),
  KEY `sig_usage_signer_idx` (`tenant_id`,`signer_user_id`,`signed_at`),
  KEY `sig_usage_att_idx` (`signature_attachment_id`),
  KEY `tdyw_signature_usages_tenant_id_41260296` (`tenant_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_signature_usages`
--

LOCK TABLES `tdyw_signature_usages` WRITE;
/*!40000 ALTER TABLE `tdyw_signature_usages` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_signature_usages` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_station_frequency_approval`
--

DROP TABLE IF EXISTS `tdyw_station_frequency_approval`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_station_frequency_approval` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `doc_no` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `frequency_text` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `valid_from` date NOT NULL,
  `valid_to` date NOT NULL,
  `responsible_user_id` int(11) NOT NULL,
  `responsible_user_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `remark` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) DEFAULT NULL,
  `created_by_id` bigint(20) NOT NULL,
  `updated_by_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_sfa_tenant_doc_no` (`tenant_id`,`doc_no`),
  KEY `sfa_tenant_created_idx` (`tenant_id`,`created_at` DESC,`id` DESC),
  KEY `sfa_owner_expiry_idx` (`tenant_id`,`responsible_user_id`,`valid_to`),
  KEY `sfa_tenant_expiry_idx` (`tenant_id`,`valid_to`),
  KEY `tdyw_station_frequenc_created_by_id_00de1f76_fk_users_id` (`created_by_id`),
  KEY `tdyw_station_frequenc_updated_by_id_d9637c39_fk_users_id` (`updated_by_id`),
  CONSTRAINT `tdyw_station_frequenc_created_by_id_00de1f76_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_station_frequenc_updated_by_id_d9637c39_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_station_frequency_approval`
--

LOCK TABLES `tdyw_station_frequency_approval` WRITE;
/*!40000 ALTER TABLE `tdyw_station_frequency_approval` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_station_frequency_approval` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_station_frequency_approval_reminder_ack`
--

DROP TABLE IF EXISTS `tdyw_station_frequency_approval_reminder_ack`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_station_frequency_approval_reminder_ack` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_id` int(11) NOT NULL,
  `user_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `ack_valid_to` date NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `approval_id` bigint(20) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_sfa_ack_cycle` (`tenant_id`,`approval_id`,`user_id`,`ack_valid_to`),
  KEY `sfa_ack_user_approval_idx` (`tenant_id`,`user_id`,`approval_id`),
  KEY `tdyw_station_frequency_ap_approval_id_2271bc65_fk` (`approval_id`),
  CONSTRAINT `tdyw_station_frequency_ap_approval_id_2271bc65_fk` FOREIGN KEY (`approval_id`) REFERENCES `tdyw_station_frequency_approval` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_station_frequency_approval_reminder_ack`
--

LOCK TABLES `tdyw_station_frequency_approval_reminder_ack` WRITE;
/*!40000 ALTER TABLE `tdyw_station_frequency_approval_reminder_ack` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_station_frequency_approval_reminder_ack` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_upgrade_plan_steps`
--

DROP TABLE IF EXISTS `tdyw_upgrade_plan_steps`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_upgrade_plan_steps` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `template_id` int(11) NOT NULL,
  `title` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `sequence` int(11) NOT NULL,
  `is_required` tinyint(1) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `phase` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_upgrad_templat_3f7a1a_idx` (`template_id`),
  KEY `tdyw_upgrad_tenant__4a96ad_idx` (`tenant_id`,`template_id`),
  KEY `tdyw_upgrade_plan_steps_tenant_id_1a982a7d` (`tenant_id`),
  KEY `upg_plan_tenant_seq_idx` (`tenant_id`,`template_id`,`sequence`,`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_upgrade_plan_steps`
--

LOCK TABLES `tdyw_upgrade_plan_steps` WRITE;
/*!40000 ALTER TABLE `tdyw_upgrade_plan_steps` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_upgrade_plan_steps` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_upgrade_record_steps`
--

DROP TABLE IF EXISTS `tdyw_upgrade_record_steps`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_upgrade_record_steps` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `upgrade_id` int(11) NOT NULL,
  `checklist_id` int(11) NOT NULL,
  `title` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `sequence` int(11) NOT NULL,
  `is_required` tinyint(1) NOT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `completed_by` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `completed_at` datetime(6) DEFAULT NULL,
  `remark` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `phase` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_upgrad_upgrade_e5a7f6_idx` (`upgrade_id`),
  KEY `tdyw_upgrad_tenant__4a6b6b_idx` (`tenant_id`,`upgrade_id`),
  KEY `tdyw_upgrade_record_steps_tenant_id_1027e88e` (`tenant_id`),
  KEY `upg_step_tenant_seq_idx` (`tenant_id`,`upgrade_id`,`sequence`,`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_upgrade_record_steps`
--

LOCK TABLES `tdyw_upgrade_record_steps` WRITE;
/*!40000 ALTER TABLE `tdyw_upgrade_record_steps` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_upgrade_record_steps` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_upgrade_records`
--

DROP TABLE IF EXISTS `tdyw_upgrade_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_upgrade_records` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `upgrade_no` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `system` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `upgrade_type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `version` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `upgrade_time` datetime(6) DEFAULT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `owner` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) DEFAULT NULL,
  `created_by_id` bigint(20) NOT NULL,
  `updated_by_id` bigint(20) DEFAULT NULL,
  `title` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `upgrade_content` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `impact_scope` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `risk_desc` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `rollback_plan` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `tdyw_upgrade_records_tenant_id_upgrade_no_ac4e6b44_uniq` (`tenant_id`,`upgrade_no`),
  KEY `tdyw_upgrade_records_created_by_id_4def2632_fk_users_id` (`created_by_id`),
  KEY `tdyw_upgrade_records_updated_by_id_7795fa23_fk_users_id` (`updated_by_id`),
  KEY `tdyw_upgrad_tenant__f711da_idx` (`tenant_id`,`status`),
  KEY `upg_rec_time_idx` (`tenant_id`,`upgrade_time`,`id`),
  KEY `upg_rec_status_time_idx` (`tenant_id`,`status`,`upgrade_time`,`id`),
  KEY `upg_rec_type_time_idx` (`tenant_id`,`upgrade_type`,`upgrade_time`,`id`),
  CONSTRAINT `tdyw_upgrade_records_created_by_id_4def2632_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_upgrade_records_updated_by_id_7795fa23_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_upgrade_records`
--

LOCK TABLES `tdyw_upgrade_records` WRITE;
/*!40000 ALTER TABLE `tdyw_upgrade_records` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_upgrade_records` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_upgrade_status_logs`
--

DROP TABLE IF EXISTS `tdyw_upgrade_status_logs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_upgrade_status_logs` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `upgrade_id` int(11) NOT NULL,
  `action` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `from_status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `to_status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `operator_id` int(11) NOT NULL,
  `operator_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `remark` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `target_action` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `event_seq` int(11) NOT NULL,
  `is_override` tinyint(1) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_upgrad_upgrade_fab64e_idx` (`upgrade_id`),
  KEY `tdyw_upgrad_tenant__b4cd1a_idx` (`tenant_id`,`upgrade_id`),
  KEY `tdyw_upgrade_status_logs_tenant_id_ece0ae3d` (`tenant_id`),
  KEY `tdyw_upgrad_upgrade_seq_idx` (`upgrade_id`,`event_seq`),
  KEY `upg_log_tenant_seq_idx` (`tenant_id`,`upgrade_id`,`event_seq`,`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_upgrade_status_logs`
--

LOCK TABLES `tdyw_upgrade_status_logs` WRITE;
/*!40000 ALTER TABLE `tdyw_upgrade_status_logs` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_upgrade_status_logs` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_upgrade_systems`
--

DROP TABLE IF EXISTS `tdyw_upgrade_systems`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_upgrade_systems` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  `sort_order` int(11) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) DEFAULT NULL,
  `created_by_id` bigint(20) DEFAULT NULL,
  `updated_by_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `tdyw_upgrade_systems_tenant_id_name_fddb4b92_uniq` (`tenant_id`,`name`),
  KEY `tdyw_upgrade_systems_created_by_id_01ea7558_fk_users_id` (`created_by_id`),
  KEY `tdyw_upgrade_systems_updated_by_id_6e6f43f7_fk_users_id` (`updated_by_id`),
  KEY `upg_sys_active_idx` (`tenant_id`,`is_active`,`sort_order`,`name`),
  CONSTRAINT `tdyw_upgrade_systems_created_by_id_01ea7558_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_upgrade_systems_updated_by_id_6e6f43f7_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=11 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_upgrade_systems`
--

LOCK TABLES `tdyw_upgrade_systems` WRITE;
/*!40000 ALTER TABLE `tdyw_upgrade_systems` DISABLE KEYS */;
INSERT INTO `tdyw_upgrade_systems` VALUES
(1,'','运维管理平台',1,1,'2026-07-24 10:29:17.000000',NULL,NULL,NULL),
(2,'','数据库系统',1,2,'2026-07-24 10:29:17.000000',NULL,NULL,NULL),
(3,'','网络设备',1,3,'2026-07-24 10:29:17.000000',NULL,NULL,NULL),
(4,'','安全设备',1,4,'2026-07-24 10:29:17.000000',NULL,NULL,NULL),
(5,'','中间件',1,5,'2026-07-24 10:29:17.000000',NULL,NULL,NULL),
(6,'','监控系统',1,6,'2026-07-24 10:29:17.000000',NULL,NULL,NULL),
(7,'','备份系统',1,7,'2026-07-24 10:29:17.000000',NULL,NULL,NULL),
(8,'','邮件系统',1,8,'2026-07-24 10:29:17.000000',NULL,NULL,NULL),
(9,'','OA系统',1,9,'2026-07-24 10:29:17.000000',NULL,NULL,NULL),
(10,'','其他',1,10,'2026-07-24 10:29:17.000000',NULL,NULL,NULL);
/*!40000 ALTER TABLE `tdyw_upgrade_systems` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tdyw_upgrade_templates`
--

DROP TABLE IF EXISTS `tdyw_upgrade_templates`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tdyw_upgrade_templates` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `system` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `upgrade_type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `version` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `owner` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `detail_content` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_default` tinyint(1) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) DEFAULT NULL,
  `created_by_id` bigint(20) NOT NULL,
  `description` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_upgrad_tenant__ceb441_idx` (`tenant_id`),
  KEY `tdyw_upgrade_templates_created_by_id_aa2ea5c0_fk_users_id` (`created_by_id`),
  KEY `tdyw_upgrade_templates_tenant_id_79931e61` (`tenant_id`),
  KEY `upg_tpl_default_idx` (`tenant_id`,`is_default`,`name`,`id`),
  CONSTRAINT `tdyw_upgrade_templates_created_by_id_aa2ea5c0_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_upgrade_templates`
--

LOCK TABLES `tdyw_upgrade_templates` WRITE;
/*!40000 ALTER TABLE `tdyw_upgrade_templates` DISABLE KEYS */;
/*!40000 ALTER TABLE `tdyw_upgrade_templates` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tenants`
--

DROP TABLE IF EXISTS `tenants`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tenants` (
  `id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `created_by_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `tenants_created_by_id_ac6da4d6_fk` (`created_by_id`),
  CONSTRAINT `tenants_created_by_id_ac6da4d6_fk` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tenants`
--

LOCK TABLES `tenants` WRITE;
/*!40000 ALTER TABLE `tenants` DISABLE KEYS */;
/*!40000 ALTER TABLE `tenants` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `user_role_rel`
--

DROP TABLE IF EXISTS `user_role_rel`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `user_role_rel` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `user_id` bigint(20) NOT NULL,
  `role_id` bigint(20) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `user_role_rel_user_id_role_id_62a7d1cf_uniq` (`user_id`,`role_id`),
  KEY `user_role_rel_role_id_57d24f6b_fk` (`role_id`),
  CONSTRAINT `user_role_rel_role_id_57d24f6b_fk` FOREIGN KEY (`role_id`) REFERENCES `roles` (`id`),
  CONSTRAINT `user_role_rel_user_id_b88b83f1_fk` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `user_role_rel`
--

LOCK TABLES `user_role_rel` WRITE;
/*!40000 ALTER TABLE `user_role_rel` DISABLE KEYS */;
/*!40000 ALTER TABLE `user_role_rel` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `user_settings`
--

DROP TABLE IF EXISTS `user_settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `user_settings` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `key` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_id` bigint(20) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `user_settings_user_id_key_44bb6951_uniq` (`user_id`,`key`),
  CONSTRAINT `user_settings_user_id_46a3df84_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `user_settings`
--

LOCK TABLES `user_settings` WRITE;
/*!40000 ALTER TABLE `user_settings` DISABLE KEYS */;
/*!40000 ALTER TABLE `user_settings` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `users` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `username` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `nickname` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `password_hash` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `type` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_supper` tinyint(1) NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  `access_token` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `token_expired` int(11) DEFAULT NULL,
  `last_login` datetime(6) DEFAULT NULL,
  `last_ip` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `wx_token` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `tenant_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `deleted_at` datetime(6) DEFAULT NULL,
  `created_by_id` bigint(20) DEFAULT NULL,
  `deleted_by_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `users_tenant_id_07f315ee` (`tenant_id`),
  KEY `users_created_by_id_19a92469_fk` (`created_by_id`),
  KEY `users_deleted_by_id_d342c553_fk` (`deleted_by_id`),
  CONSTRAINT `users_created_by_id_19a92469_fk` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `users_deleted_by_id_d342c553_fk` FOREIGN KEY (`deleted_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `users`
--

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` VALUES
(1,'admin','管理员','pbkdf2_sha256$600000$QhIqQ7NIzxAXBdIShhF31m$vd6ohShI/KNeysj3wjgSwV8m2qiimhUZGzm2d4sdQPI=','default',1,1,'',NULL,NULL,'',NULL,'admin','2026-07-24 10:29:20.208493',NULL,NULL,NULL);
/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping events for database 'tdyw'
--

--
-- Dumping routines for database 'tdyw'
--
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-07-24 10:30:51
