-- MariaDB dump 10.19  Distrib 10.8.2-MariaDB, for debian-linux-gnu (x86_64)
--
-- Host: localhost    Database: spug
-- ------------------------------------------------------
-- Server version	10.8.2-MariaDB-1:10.8.2+maria~focal

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
-- Table structure for table `apps`
--

DROP TABLE IF EXISTS `apps`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `apps` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `key` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `desc` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `rel_apps` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `rel_services` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `sort_id` int(11) NOT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `key` (`key`),
  KEY `apps_created_by_id_35f182fb_fk_users_id` (`created_by_id`),
  KEY `apps_sort_id_d43e88b4` (`sort_id`),
  CONSTRAINT `apps_created_by_id_35f182fb_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `apps`
--

LOCK TABLES `apps` WRITE;
/*!40000 ALTER TABLE `apps` DISABLE KEYS */;
INSERT INTO `apps` VALUES
(1,'洪心艺','ss',NULL,NULL,NULL,1,'2026-01-21 13:59:42',5),
(2,'仨','111',NULL,NULL,NULL,2,'2026-01-24 16:33:19',5),
(3,'111','1111',NULL,NULL,NULL,3,'2026-01-24 21:44:20',5),
(4,'123','231',NULL,NULL,NULL,4,'2026-01-25 10:35:28',5),
(5,'林杰','56',NULL,NULL,NULL,5,'2026-01-25 10:53:19',5);
/*!40000 ALTER TABLE `apps` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `config_histories`
--

DROP TABLE IF EXISTS `config_histories`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `config_histories` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `type` varchar(5) COLLATE utf8mb4_unicode_ci NOT NULL,
  `o_id` int(11) NOT NULL,
  `key` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `env_id` int(11) NOT NULL,
  `value` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `desc` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_public` tinyint(1) NOT NULL,
  `old_value` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `action` varchar(2) COLLATE utf8mb4_unicode_ci NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `updated_by_id` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `config_histories_updated_by_id_2e187933_fk_users_id` (`updated_by_id`),
  CONSTRAINT `config_histories_updated_by_id_2e187933_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `config_histories`
--

LOCK TABLES `config_histories` WRITE;
/*!40000 ALTER TABLE `config_histories` DISABLE KEYS */;
/*!40000 ALTER TABLE `config_histories` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `configs`
--

DROP TABLE IF EXISTS `configs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `configs` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `type` varchar(5) COLLATE utf8mb4_unicode_ci NOT NULL,
  `o_id` int(11) NOT NULL,
  `key` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `env_id` int(11) NOT NULL,
  `value` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `desc` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_public` tinyint(1) NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `updated_by_id` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `configs_env_id_2f0649d0_fk_environments_id` (`env_id`),
  KEY `configs_updated_by_id_63b5c809_fk_users_id` (`updated_by_id`),
  CONSTRAINT `configs_env_id_2f0649d0_fk_environments_id` FOREIGN KEY (`env_id`) REFERENCES `environments` (`id`),
  CONSTRAINT `configs_updated_by_id_63b5c809_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `configs`
--

LOCK TABLES `configs` WRITE;
/*!40000 ALTER TABLE `configs` DISABLE KEYS */;
/*!40000 ALTER TABLE `configs` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `deploy_extend1`
--

DROP TABLE IF EXISTS `deploy_extend1`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `deploy_extend1` (
  `deploy_id` int(11) NOT NULL,
  `git_repo` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `dst_dir` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `dst_repo` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `versions` int(11) NOT NULL,
  `filter_rule` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `hook_pre_server` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `hook_post_server` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `hook_pre_host` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `hook_post_host` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`deploy_id`),
  CONSTRAINT `deploy_extend1_deploy_id_19394d5b_fk_deploys_id` FOREIGN KEY (`deploy_id`) REFERENCES `deploys` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `deploy_extend1`
--

LOCK TABLES `deploy_extend1` WRITE;
/*!40000 ALTER TABLE `deploy_extend1` DISABLE KEYS */;
/*!40000 ALTER TABLE `deploy_extend1` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `deploy_extend2`
--

DROP TABLE IF EXISTS `deploy_extend2`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `deploy_extend2` (
  `deploy_id` int(11) NOT NULL,
  `server_actions` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `host_actions` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `require_upload` tinyint(1) NOT NULL,
  PRIMARY KEY (`deploy_id`),
  CONSTRAINT `deploy_extend2_deploy_id_f17e22fa_fk_deploys_id` FOREIGN KEY (`deploy_id`) REFERENCES `deploys` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `deploy_extend2`
--

LOCK TABLES `deploy_extend2` WRITE;
/*!40000 ALTER TABLE `deploy_extend2` DISABLE KEYS */;
/*!40000 ALTER TABLE `deploy_extend2` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `deploy_requests`
--

DROP TABLE IF EXISTS `deploy_requests`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `deploy_requests` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `deploy_id` int(11) NOT NULL,
  `repository_id` int(11) DEFAULT NULL,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `type` varchar(2) COLLATE utf8mb4_unicode_ci NOT NULL,
  `extra` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `host_ids` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `desc` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` varchar(2) COLLATE utf8mb4_unicode_ci NOT NULL,
  `reason` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `version` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `spug_version` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `plan` datetime(6) DEFAULT NULL,
  `fail_host_ids` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  `approve_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `approve_by_id` int(11) DEFAULT NULL,
  `do_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `do_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `deploy_requests_deploy_id_a0ea9eff_fk_deploys_id` (`deploy_id`),
  KEY `deploy_requests_repository_id_d79d0dc5_fk_repositories_id` (`repository_id`),
  KEY `deploy_requests_created_by_id_aa58eae6_fk_users_id` (`created_by_id`),
  KEY `deploy_requests_approve_by_id_8057f43a_fk_users_id` (`approve_by_id`),
  KEY `deploy_requests_do_by_id_43c9b599_fk_users_id` (`do_by_id`),
  CONSTRAINT `deploy_requests_approve_by_id_8057f43a_fk_users_id` FOREIGN KEY (`approve_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `deploy_requests_created_by_id_aa58eae6_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `deploy_requests_deploy_id_a0ea9eff_fk_deploys_id` FOREIGN KEY (`deploy_id`) REFERENCES `deploys` (`id`),
  CONSTRAINT `deploy_requests_do_by_id_43c9b599_fk_users_id` FOREIGN KEY (`do_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `deploy_requests_repository_id_d79d0dc5_fk_repositories_id` FOREIGN KEY (`repository_id`) REFERENCES `repositories` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `deploy_requests`
--

LOCK TABLES `deploy_requests` WRITE;
/*!40000 ALTER TABLE `deploy_requests` DISABLE KEYS */;
/*!40000 ALTER TABLE `deploy_requests` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `deploys`
--

DROP TABLE IF EXISTS `deploys`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `deploys` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `app_id` int(11) NOT NULL,
  `env_id` int(11) NOT NULL,
  `host_ids` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `extend` varchar(2) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_audit` tinyint(1) NOT NULL,
  `is_parallel` tinyint(1) NOT NULL,
  `rst_notify` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `updated_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `deploys_app_id_f7f57778_fk_apps_id` (`app_id`),
  KEY `deploys_env_id_4b8de219_fk_environments_id` (`env_id`),
  KEY `deploys_created_by_id_5d5eab7f_fk_users_id` (`created_by_id`),
  KEY `deploys_updated_by_id_e184af7e_fk_users_id` (`updated_by_id`),
  CONSTRAINT `deploys_app_id_f7f57778_fk_apps_id` FOREIGN KEY (`app_id`) REFERENCES `apps` (`id`),
  CONSTRAINT `deploys_created_by_id_5d5eab7f_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `deploys_env_id_4b8de219_fk_environments_id` FOREIGN KEY (`env_id`) REFERENCES `environments` (`id`),
  CONSTRAINT `deploys_updated_by_id_e184af7e_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `deploys`
--

LOCK TABLES `deploys` WRITE;
/*!40000 ALTER TABLE `deploys` DISABLE KEYS */;
/*!40000 ALTER TABLE `deploys` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `detections`
--

DROP TABLE IF EXISTS `detections`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `detections` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `type` varchar(2) COLLATE utf8mb4_unicode_ci NOT NULL,
  `group` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `targets` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `extra` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `desc` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_active` tinyint(1) NOT NULL,
  `rate` int(11) NOT NULL,
  `threshold` int(11) NOT NULL,
  `quiet` int(11) NOT NULL,
  `fault_times` smallint(6) NOT NULL,
  `notify_mode` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `notify_grp` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `latest_run_time` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `updated_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `detections_created_by_id_9c30d47b_fk_users_id` (`created_by_id`),
  KEY `detections_updated_by_id_d1302145_fk_users_id` (`updated_by_id`),
  CONSTRAINT `detections_created_by_id_9c30d47b_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `detections_updated_by_id_d1302145_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `detections`
--

LOCK TABLES `detections` WRITE;
/*!40000 ALTER TABLE `detections` DISABLE KEYS */;
/*!40000 ALTER TABLE `detections` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `django_migrations`
--

DROP TABLE IF EXISTS `django_migrations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `django_migrations` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `app` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `applied` datetime(6) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `django_migrations`
--

LOCK TABLES `django_migrations` WRITE;
/*!40000 ALTER TABLE `django_migrations` DISABLE KEYS */;
/*!40000 ALTER TABLE `django_migrations` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `environments`
--

DROP TABLE IF EXISTS `environments`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `environments` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `key` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `desc` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `sort_id` int(11) NOT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `environments_created_by_id_ec487847_fk_users_id` (`created_by_id`),
  KEY `environments_sort_id_0d1b2482` (`sort_id`),
  CONSTRAINT `environments_created_by_id_ec487847_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `environments`
--

LOCK TABLES `environments` WRITE;
/*!40000 ALTER TABLE `environments` DISABLE KEYS */;
/*!40000 ALTER TABLE `environments` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `exec_duty_records`
--

DROP TABLE IF EXISTS `exec_duty_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exec_duty_records` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `user_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `duty_date` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `log_content` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `events` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `attachments` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `updated_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `user_name` (`user_name`),
  KEY `duty_date` (`duty_date`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exec_duty_records`
--

LOCK TABLES `exec_duty_records` WRITE;
/*!40000 ALTER TABLE `exec_duty_records` DISABLE KEYS */;
INSERT INTO `exec_duty_records` VALUES
(1,12,'12','2026-01-10 22:32:12',NULL,'[]','[]','2026-01-22 22:32:11',5,NULL,NULL),
(2,12,'曹春城','2026-01-25 00:00:07',NULL,'[]','[]','2026-01-25 20:08:46',5,NULL,NULL),
(3,22,'曹春城','2026-01-27 00:00:06',NULL,'[]','[]','2026-01-27 23:48:11',5,NULL,NULL);
/*!40000 ALTER TABLE `exec_duty_records` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `exec_fault_parts`
--

DROP TABLE IF EXISTS `exec_fault_parts`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exec_fault_parts` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(100) NOT NULL COMMENT 'æ•…éšœä»¶åç§°',
  `system_name` varchar(100) NOT NULL COMMENT 'æ‰€å±žç³»ç»Ÿ',
  `date` varchar(20) NOT NULL COMMENT 'æ—¥æœŸ',
  `fault_date` varchar(20) NOT NULL COMMENT 'æ•…éšœæ—¥æœŸ',
  `status` varchar(20) NOT NULL COMMENT 'çŠ¶æ€',
  `fault_sent_date` varchar(20) DEFAULT NULL COMMENT 'é€ä¿®æ—¥æœŸ',
  `test_return_date` varchar(20) DEFAULT NULL COMMENT 'è¿å›žæµ‹è¯•æ—¥æœŸ',
  `archive_date` varchar(20) DEFAULT NULL COMMENT 'å½’æ¡£æ—¥æœŸ',
  `created_at` varchar(20) NOT NULL COMMENT 'åˆ›å»ºæ—¶é—´',
  `created_by_id` int(11) NOT NULL COMMENT 'åˆ›å»ºäºº',
  `updated_at` varchar(20) DEFAULT NULL COMMENT 'æ›´æ–°æ—¶é—´',
  `updated_by_id` int(11) DEFAULT NULL COMMENT 'æ›´æ–°äºº',
  PRIMARY KEY (`id`),
  KEY `status_idx` (`status`),
  KEY `system_name_idx` (`system_name`),
  KEY `date_idx` (`date`)
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COMMENT='æ•…éšœä»¶ç®¡ç†è¡¨';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exec_fault_parts`
--

LOCK TABLES `exec_fault_parts` WRITE;
/*!40000 ALTER TABLE `exec_fault_parts` DISABLE KEYS */;
INSERT INTO `exec_fault_parts` VALUES
(2,'洪心艺','11','2026-01-21','2026-01-21','正常归档','2026-01-21','2026-01-21','2026-01-21 22:42:51','2026-01-21 13:35:26',5,'2026-01-21 22:42:51',5),
(3,'洪心艺','11','2026-01-21','2026-01-21','送修','2026-01-21 13:35:46',NULL,NULL,'2026-01-21 13:35:46',5,NULL,NULL),
(4,'洪心艺','11','2026-01-21','2026-01-22','故障','2026-01-21','2026-01-21','2026-01-20','2026-01-21 13:35:59',5,'2026-01-21 13:45:49',5),
(5,'洪心艺','11','2026-01-19','2026-01-15','正常归档','2026-01-21','2026-01-21','2026-01-21 13:50:36','2026-01-21 13:50:19',5,'2026-01-21 13:50:36',5),
(6,'洪心艺','11','2026-01-23','2026-01-16','故障',NULL,NULL,NULL,'2026-01-21 14:11:01',5,NULL,NULL),
(7,'sa','11','2026-01-20','2026-01-13','正常归档','2026-01-21','2026-01-21','2026-01-21 14:29:31','2026-01-21 14:29:04',5,'2026-01-21 14:29:31',5);
/*!40000 ALTER TABLE `exec_fault_parts` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `exec_fault_records`
--

DROP TABLE IF EXISTS `exec_fault_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exec_fault_records` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `system_name` varchar(100) NOT NULL COMMENT 'ç³»ç»Ÿåç§°',
  `device_code` varchar(100) NOT NULL COMMENT 'è®¾å¤‡ç¼–å·',
  `fault_date` varchar(20) NOT NULL COMMENT 'æ—¥æœŸ',
  `handler` varchar(100) NOT NULL COMMENT 'å¤„ç½®äººå‘˜',
  `recorder` varchar(100) NOT NULL COMMENT 'è®°å½•äººå‘˜',
  `fault_level` varchar(10) NOT NULL COMMENT 'æ•…éšœè¯„çº§',
  `fault_phenomenon` text NOT NULL COMMENT 'æ•…éšœçŽ°è±¡',
  `handling_process` text NOT NULL COMMENT 'å¤„ç½®è¿‡ç¨‹',
  `created_at` varchar(20) NOT NULL COMMENT 'åˆ›å»ºæ—¶é—´',
  `created_by_id` int(11) NOT NULL COMMENT 'åˆ›å»ºäºº',
  `updated_at` varchar(20) DEFAULT NULL COMMENT 'æ›´æ–°æ—¶é—´',
  `updated_by_id` int(11) DEFAULT NULL COMMENT 'æ›´æ–°äºº',
  PRIMARY KEY (`id`),
  KEY `fault_date_idx` (`fault_date`),
  KEY `system_name_idx` (`system_name`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COMMENT='æ•…éšœå¤„ç½®è®°å½•è¡¨';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exec_fault_records`
--

LOCK TABLES `exec_fault_records` WRITE;
/*!40000 ALTER TABLE `exec_fault_records` DISABLE KEYS */;
INSERT INTO `exec_fault_records` VALUES
(1,'晋江系统','123','2026-01-22','崔林杰','崔林杰','B','11','11','2026-01-21 12:59:04',5,NULL,NULL),
(2,'晋江系统','123','2026-01-15','崔林杰','崔林杰','B','q','去去去','2026-01-21 12:59:43',5,NULL,NULL),
(3,'晋江系统','123','2026-01-15','崔林杰','崔林杰','B','PS E:\\TDYW\\spug-3.0> # 复制脚本到容器\nPS E:\\TDYW\\spug-3.0> docker cp e:/TDYW/spug-3.0/create_table.py spug:/tmp/\nSuccessfully copied 3.58kB to spug:/tmp/\nPS E:\\TDYW\\spug-3.0>\nPS E:\\TDYW\\spug-3.0> # 执行脚本\nPS E:\\TDYW\\spug-3.0> docker exec spug /usr/bin/python3 /tmp/create_table.py\nTraceback (most recent call last):\n  File \"/tmp/create_table.py\", line 9, in <module>\n    django.setup()\n  File \"/usr/local/lib/python3.10/dist-packages/django/__init__.py\", line 19, in setup\n    configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 79, in __getattr__\n    self._setup(name)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 66, in _setup\n    self._wrapped = Settings(settings_module)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 157, in __init__\n    mod = importlib.import_module(self.SETTINGS_MODULE)\n  File \"/usr/lib/python3.10/importlib/__init__.py\", line 126, in import_module\n    return _bootstrap._gcd_import(name[level:], package, level)\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 992, in _find_and_load_unlocked\n  File \"<frozen importlib._bootstrap>\", line 241, in _call_with_frames_removed\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 1004, in _find_and_load_unlocked\nModuleNotFoundError: No module named \'spug_api\'\nPS E:\\TDYW\\spug-3.0> docker cp e:/TDYW/spug-3.0/create_table.py spug:/tmp/\nSuccessfully copied 3.58kB to spug:/tmp/\nPS E:\\TDYW\\spug-3.0> docker exec spug /usr/bin/python3 /tmp/create_table.py\nTraceback (most recent call last):\n  File \"/tmp/create_table.py\", line 9, in <module>\n    django.setup()\n  File \"/usr/local/lib/python3.10/dist-packages/django/__init__.py\", line 19, in setup\n    configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 79, in __getattr__\n    self._setup(name)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 66, in _setup\n    self._wrapped = Settings(settings_module)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 157, in __init__\n    mod = importlib.import_module(self.SETTINGS_MODULE)\n  File \"/usr/lib/python3.10/importlib/__init__.py\", line 126, in import_module\n    return _bootstrap._gcd_import(name[level:], package, level)\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 992, in _find_and_load_unlocked\n  File \"<frozen importlib._bootstrap>\", line 241, in _call_with_frames_removed\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 1004, in _find_and_load_unlocked\nModuleNotFoundError: No module named \'spug_api\'PS E:\\TDYW\\spug-3.0> # 复制脚本到容器\nPS E:\\TDYW\\spug-3.0> docker cp e:/TDYW/spug-3.0/create_table.py spug:/tmp/\nSuccessfully copied 3.58kB to spug:/tmp/\nPS E:\\TDYW\\spug-3.0>\nPS E:\\TDYW\\spug-3.0> # 执行脚本\nPS E:\\TDYW\\spug-3.0> docker exec spug /usr/bin/python3 /tmp/create_table.py\nTraceback (most recent call last):\n  File \"/tmp/create_table.py\", line 9, in <module>\n    django.setup()\n  File \"/usr/local/lib/python3.10/dist-packages/django/__init__.py\", line 19, in setup\n    configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 79, in __getattr__\n    self._setup(name)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 66, in _setup\n    self._wrapped = Settings(settings_module)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 157, in __init__\n    mod = importlib.import_module(self.SETTINGS_MODULE)\n  File \"/usr/lib/python3.10/importlib/__init__.py\", line 126, in import_module\n    return _bootstrap._gcd_import(name[level:], package, level)\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 992, in _find_and_load_unlocked\n  File \"<frozen importlib._bootstrap>\", line 241, in _call_with_frames_removed\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 1004, in _find_and_load_unlocked\nModuleNotFoundError: No module named \'spug_api\'\nPS E:\\TDYW\\spug-3.0> docker cp e:/TDYW/spug-3.0/create_table.py spug:/tmp/\nSuccessfully copied 3.58kB to spug:/tmp/\nPS E:\\TDYW\\spug-3.0> docker exec spug /usr/bin/python3 /tmp/create_table.py\nTraceback (most recent call last):\n  File \"/tmp/create_table.py\", line 9, in <module>\n    django.setup()\n  File \"/usr/local/lib/python3.10/dist-packages/django/__init__.py\", line 19, in setup\n    configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 79, in __getattr__\n    self._setup(name)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 66, in _setup\n    self._wrapped = Settings(settings_module)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 157, in __init__\n    mod = importlib.import_module(self.SETTINGS_MODULE)\n  File \"/usr/lib/python3.10/importlib/__init__.py\", line 126, in import_module\n    return _bootstrap._gcd_import(name[level:], package, level)\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 992, in _find_and_load_unlocked\n  File \"<frozen importlib._bootstrap>\", line 241, in _call_with_frames_removed\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 1004, in _find_and_load_unlocked\nModuleNotFoundError: No module named \'spug_api\'PS E:\\TDYW\\spug-3.0> # 复制脚本到容器\nPS E:\\TDYW\\spug-3.0> docker cp e:/TDYW/spug-3.0/create_table.py spug:/tmp/\nSuccessfully copied 3.58kB to spug:/tmp/\nPS E:\\TDYW\\spug-3.0>\nPS E:\\TDYW\\spug-3.0> # 执行脚本\nPS E:\\TDYW\\spug-3.0> docker exec spug /usr/bin/python3 /tmp/create_table.py\nTraceback (most recent call last):\n  File \"/tmp/create_table.py\", line 9, in <module>\n    django.setup()\n  File \"/usr/local/lib/python3.10/dist-packages/django/__init__.py\", line 19, in setup\n    configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 79, in __getattr__\n    self._setup(name)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 66, in _setup\n    self._wrapped = Settings(settings_module)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 157, in __init__\n    mod = importlib.import_module(self.SETTINGS_MODULE)\n  File \"/usr/lib/python3.10/importlib/__init__.py\", line 126, in import_module\n    return _bootstrap._gcd_import(name[level:], package, level)\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 992, in _find_and_load_unlocked\n  File \"<frozen importlib._bootstrap>\", line 241, in _call_with_frames_removed\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 1004, in _find_and_load_unlocked\nModuleNotFoundError: No module named \'spug_api\'\nPS E:\\TDYW\\spug-3.0> docker cp e:/TDYW/spug-3.0/create_table.py spug:/tmp/\nSuccessfully copied 3.58kB to spug:/tmp/\nPS E:\\TDYW\\spug-3.0> docker exec spug /usr/bin/python3 /tmp/create_table.py\nTraceback (most recent call last):\n  File \"/tmp/create_table.py\", line 9, in <module>\n    django.setup()\n  File \"/usr/local/lib/python3.10/dist-packages/django/__init__.py\", line 19, in setup\n    configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 79, in __getattr__\n    self._setup(name)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 66, in _setup\n    self._wrapped = Settings(settings_module)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 157, in __init__\n    mod = importlib.import_module(self.SETTINGS_MODULE)\n  File \"/usr/lib/python3.10/importlib/__init__.py\", line 126, in import_module\n    return _bootstrap._gcd_import(name[level:], package, level)\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 992, in _find_and_load_unlocked\n  File \"<frozen importlib._bootstrap>\", line 241, in _call_with_frames_removed\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 1004, in _find_and_load_unlocked\nModuleNotFoundError: No module named \'spug_api\'','PS E:\\TDYW\\spug-3.0> # 复制脚本到容器\nPS E:\\TDYW\\spug-3.0> docker cp e:/TDYW/spug-3.0/create_table.py spug:/tmp/\nSuccessfully copied 3.58kB to spug:/tmp/\nPS E:\\TDYW\\spug-3.0>\nPS E:\\TDYW\\spug-3.0> # 执行脚本\nPS E:\\TDYW\\spug-3.0> docker exec spug /usr/bin/python3 /tmp/create_table.py\nTraceback (most recent call last):\n  File \"/tmp/create_table.py\", line 9, in <module>\n    django.setup()\n  File \"/usr/local/lib/python3.10/dist-packages/django/__init__.py\", line 19, in setup\n    configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 79, in __getattr__\n    self._setup(name)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 66, in _setup\n    self._wrapped = Settings(settings_module)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 157, in __init__\n    mod = importlib.import_module(self.SETTINGS_MODULE)\n  File \"/usr/lib/python3.10/importlib/__init__.py\", line 126, in import_module\n    return _bootstrap._gcd_import(name[level:], package, level)\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 992, in _find_and_load_unlocked\n  File \"<frozen importlib._bootstrap>\", line 241, in _call_with_frames_removed\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 1004, in _find_and_load_unlocked\nModuleNotFoundError: No module named \'spug_api\'\nPS E:\\TDYW\\spug-3.0> docker cp e:/TDYW/spug-3.0/create_table.py spug:/tmp/\nSuccessfully copied 3.58kB to spug:/tmp/\nPS E:\\TDYW\\spug-3.0> docker exec spug /usr/bin/python3 /tmp/create_table.py\nTraceback (most recent call last):\n  File \"/tmp/create_table.py\", line 9, in <module>\n    django.setup()\n  File \"/usr/local/lib/python3.10/dist-packages/django/__init__.py\", line 19, in setup\n    configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 79, in __getattr__\n    self._setup(name)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 66, in _setup\n    self._wrapped = Settings(settings_module)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 157, in __init__\n    mod = importlib.import_module(self.SETTINGS_MODULE)\n  File \"/usr/lib/python3.10/importlib/__init__.py\", line 126, in import_module\n    return _bootstrap._gcd_import(name[level:], package, level)\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 992, in _find_and_load_unlocked\n  File \"<frozen importlib._bootstrap>\", line 241, in _call_with_frames_removed\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 1004, in _find_and_load_unlocked\nModuleNotFoundError: No module named \'spug_api\'PS E:\\TDYW\\spug-3.0> # 复制脚本到容器\nPS E:\\TDYW\\spug-3.0> docker cp e:/TDYW/spug-3.0/create_table.py spug:/tmp/\nSuccessfully copied 3.58kB to spug:/tmp/\nPS E:\\TDYW\\spug-3.0>\nPS E:\\TDYW\\spug-3.0> # 执行脚本\nPS E:\\TDYW\\spug-3.0> docker exec spug /usr/bin/python3 /tmp/create_table.py\nTraceback (most recent call last):\n  File \"/tmp/create_table.py\", line 9, in <module>\n    django.setup()\n  File \"/usr/local/lib/python3.10/dist-packages/django/__init__.py\", line 19, in setup\n    configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 79, in __getattr__\n    self._setup(name)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 66, in _setup\n    self._wrapped = Settings(settings_module)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 157, in __init__\n    mod = importlib.import_module(self.SETTINGS_MODULE)\n  File \"/usr/lib/python3.10/importlib/__init__.py\", line 126, in import_module\n    return _bootstrap._gcd_import(name[level:], package, level)\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 992, in _find_and_load_unlocked\n  File \"<frozen importlib._bootstrap>\", line 241, in _call_with_frames_removed\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 1004, in _find_and_load_unlocked\nModuleNotFoundError: No module named \'spug_api\'\nPS E:\\TDYW\\spug-3.0> docker cp e:/TDYW/spug-3.0/create_table.py spug:/tmp/\nSuccessfully copied 3.58kB to spug:/tmp/\nPS E:\\TDYW\\spug-3.0> docker exec spug /usr/bin/python3 /tmp/create_table.py\nTraceback (most recent call last):\n  File \"/tmp/create_table.py\", line 9, in <module>\n    django.setup()\n  File \"/usr/local/lib/python3.10/dist-packages/django/__init__.py\", line 19, in setup\n    configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 79, in __getattr__\n    self._setup(name)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 66, in _setup\n    self._wrapped = Settings(settings_module)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 157, in __init__\n    mod = importlib.import_module(self.SETTINGS_MODULE)\n  File \"/usr/lib/python3.10/importlib/__init__.py\", line 126, in import_module\n    return _bootstrap._gcd_import(name[level:], package, level)\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 992, in _find_and_load_unlocked\n  File \"<frozen importlib._bootstrap>\", line 241, in _call_with_frames_removed\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 1004, in _find_and_load_unlocked\nModuleNotFoundError: No module named \'spug_api\'PS E:\\TDYW\\spug-3.0> # 复制脚本到容器\nPS E:\\TDYW\\spug-3.0> docker cp e:/TDYW/spug-3.0/create_table.py spug:/tmp/\nSuccessfully copied 3.58kB to spug:/tmp/\nPS E:\\TDYW\\spug-3.0>\nPS E:\\TDYW\\spug-3.0> # 执行脚本\nPS E:\\TDYW\\spug-3.0> docker exec spug /usr/bin/python3 /tmp/create_table.py\nTraceback (most recent call last):\n  File \"/tmp/create_table.py\", line 9, in <module>\n    django.setup()\n  File \"/usr/local/lib/python3.10/dist-packages/django/__init__.py\", line 19, in setup\n    configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 79, in __getattr__\n    self._setup(name)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 66, in _setup\n    self._wrapped = Settings(settings_module)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 157, in __init__\n    mod = importlib.import_module(self.SETTINGS_MODULE)\n  File \"/usr/lib/python3.10/importlib/__init__.py\", line 126, in import_module\n    return _bootstrap._gcd_import(name[level:], package, level)\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 992, in _find_and_load_unlocked\n  File \"<frozen importlib._bootstrap>\", line 241, in _call_with_frames_removed\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 1004, in _find_and_load_unlocked\nModuleNotFoundError: No module named \'spug_api\'\nPS E:\\TDYW\\spug-3.0> docker cp e:/TDYW/spug-3.0/create_table.py spug:/tmp/\nSuccessfully copied 3.58kB to spug:/tmp/\nPS E:\\TDYW\\spug-3.0> docker exec spug /usr/bin/python3 /tmp/create_table.py\nTraceback (most recent call last):\n  File \"/tmp/create_table.py\", line 9, in <module>\n    django.setup()\n  File \"/usr/local/lib/python3.10/dist-packages/django/__init__.py\", line 19, in setup\n    configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 79, in __getattr__\n    self._setup(name)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 66, in _setup\n    self._wrapped = Settings(settings_module)\n  File \"/usr/local/lib/python3.10/dist-packages/django/conf/__init__.py\", line 157, in __init__\n    mod = importlib.import_module(self.SETTINGS_MODULE)\n  File \"/usr/lib/python3.10/importlib/__init__.py\", line 126, in import_module\n    return _bootstrap._gcd_import(name[level:], package, level)\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 992, in _find_and_load_unlocked\n  File \"<frozen importlib._bootstrap>\", line 241, in _call_with_frames_removed\n  File \"<frozen importlib._bootstrap>\", line 1050, in _gcd_import\n  File \"<frozen importlib._bootstrap>\", line 1027, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 1004, in _find_and_load_unlocked\nModuleNotFoundError: No module named \'spug_api\'','2026-01-21 13:00:10',5,NULL,NULL),
(4,'晋江系统','萨达','2026-01-15','崔林杰','崔林杰','B','阿萨','阿萨','2026-01-21 22:42:31',5,NULL,NULL);
/*!40000 ALTER TABLE `exec_fault_records` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `exec_handover_records`
--

DROP TABLE IF EXISTS `exec_handover_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exec_handover_records` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `from_user_id` int(11) NOT NULL,
  `from_user_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `to_user_id` int(11) NOT NULL,
  `to_user_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `handover_time` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `items` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `notes` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `confirmed` tinyint(1) DEFAULT 0,
  `confirmed_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `updated_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `handover_time` (`handover_time`),
  KEY `confirmed` (`confirmed`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exec_handover_records`
--

LOCK TABLES `exec_handover_records` WRITE;
/*!40000 ALTER TABLE `exec_handover_records` DISABLE KEYS */;
/*!40000 ALTER TABLE `exec_handover_records` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `exec_histories`
--

DROP TABLE IF EXISTS `exec_histories`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exec_histories` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `template_id` int(11) DEFAULT NULL,
  `digest` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `interpreter` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `command` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `params` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `host_ids` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `exec_histories_user_id_5ccf5466_fk_users_id` (`user_id`),
  KEY `exec_histories_template_id_1a2c6b6c_fk_exec_templates_id` (`template_id`),
  KEY `exec_histories_digest_a8699fb0` (`digest`),
  CONSTRAINT `exec_histories_template_id_1a2c6b6c_fk_exec_templates_id` FOREIGN KEY (`template_id`) REFERENCES `exec_templates` (`id`),
  CONSTRAINT `exec_histories_user_id_5ccf5466_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exec_histories`
--

LOCK TABLES `exec_histories` WRITE;
/*!40000 ALTER TABLE `exec_histories` DISABLE KEYS */;
/*!40000 ALTER TABLE `exec_histories` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `exec_interferences`
--

DROP TABLE IF EXISTS `exec_interferences`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exec_interferences` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `serial_number` int(11) DEFAULT 0,
  `frequency` varchar(100) NOT NULL COMMENT 'é¢‘çŽ‡',
  `report_dept` varchar(100) NOT NULL COMMENT 'æ±‡æŠ¥ç§‘å®¤',
  `datetime` varchar(20) NOT NULL COMMENT 'æ—¥æœŸæ—¶é—´',
  `coordinates` varchar(200) NOT NULL COMMENT 'åæ ‡',
  `interference_type` varchar(100) NOT NULL COMMENT 'å¹²æ‰°ç±»åž‹',
  `phenomenon` text NOT NULL COMMENT 'çŽ°è±¡',
  `flight_number` varchar(100) DEFAULT NULL COMMENT 'èˆªç­å·',
  `aircraft_type` varchar(100) DEFAULT NULL COMMENT 'æœºåž‹',
  `is_reported` varchar(10) DEFAULT 'å¦' COMMENT 'æ˜¯å¦ä¸ŠæŠ¥',
  `created_at` varchar(20) NOT NULL COMMENT 'åˆ›å»ºæ—¶é—´',
  `created_by_id` int(11) NOT NULL COMMENT 'åˆ›å»ºäººID',
  `updated_at` varchar(20) DEFAULT NULL COMMENT 'æ›´æ–°æ—¶é—´',
  `updated_by_id` int(11) DEFAULT NULL COMMENT 'æ›´æ–°äººID',
  PRIMARY KEY (`id`),
  KEY `idx_datetime` (`datetime`),
  KEY `idx_report_dept` (`report_dept`),
  KEY `idx_interference_type` (`interference_type`)
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COMMENT='å¹²æ‰°ç®¡ç†è¡¨';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exec_interferences`
--

LOCK TABLES `exec_interferences` WRITE;
/*!40000 ALTER TABLE `exec_interferences` DISABLE KEYS */;
INSERT INTO `exec_interferences` VALUES
(3,3,'118.45','仨','2026-01-08 23:17:55','阿萨','阿萨','仨',NULL,NULL,'是','2026-01-21 23:18:01',5,NULL,NULL),
(4,4,'118.45','仨','2026-01-07 23:46:00','阿萨','阿萨','亲戚',NULL,NULL,'是','2026-01-21 23:46:05',5,NULL,NULL),
(5,5,'118.45','仨','2026-01-15 09:40:55','1345‘23323’','阿萨','啊多少',NULL,NULL,'否','2026-01-27 09:41:02',5,NULL,NULL),
(6,6,'118.45','仨','2026-01-27 00:00:07','1345‘23323’','阿萨','212',NULL,NULL,'否','2026-01-27 23:48:45',5,NULL,NULL),
(7,7,'120.85','123','2026-01-27 00:00:05','阿萨','阿萨','安安书',NULL,NULL,'否','2026-01-27 23:49:11',5,NULL,NULL);
/*!40000 ALTER TABLE `exec_interferences` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `exec_run_logs`
--

DROP TABLE IF EXISTS `exec_run_logs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exec_run_logs` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `system_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `log_date` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `detail_record` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `handler` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `recorder` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `updated_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `exec_run_logs_created_by_id_a3d676bd_fk_users_id` (`created_by_id`),
  KEY `exec_run_logs_updated_by_id_e45ce392_fk_users_id` (`updated_by_id`),
  CONSTRAINT `exec_run_logs_created_by_id_a3d676bd_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `exec_run_logs_updated_by_id_e45ce392_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=9 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exec_run_logs`
--

LOCK TABLES `exec_run_logs` WRITE;
/*!40000 ALTER TABLE `exec_run_logs` DISABLE KEYS */;
INSERT INTO `exec_run_logs` VALUES
(1,'自动转报系统','2026-01-08','21','崔林杰、林杰','崔林杰','2026-01-21 10:12:26',5,NULL,NULL),
(3,'自动转报系统','2026-01-02','cd E:\\TDYW\\spug-3.0\\spug_web\n.\\build.bat\ndocker exec spug rm -rf /data/spug/spug_web/build\ndocker cp E:\\TDYW\\spug-3.0\\spug_web\\build spug:/data/spug/spug_web/build\ndocker exec spug supervisorctl restart nginx\ndocker restart spugcd E:\\TDYW\\spug-3.0\\spug_web\n.\\build.bat\ndocker exec spug rm -rf /data/spug/spug_web/build\ndocker cp E:\\TDYW\\spug-3.0\\spug_web\\build spug:/data/spug/spug_web/build\ndocker exec spug supervisorctl restart nginx\ndocker restart spugcd E:\\TDYW\\spug-3.0\\spug_web\n.\\build.bat\ndocker exec spug rm -rf /data/spug/spug_web/build\ndocker cp E:\\TDYW\\spug-3.0\\spug_web\\build spug:/data/spug/spug_web/build\ndocker exec spug supervisorctl restart nginx\ndocker restart spugcd E:\\TDYW\\spug-3.0\\spug_web\n.\\build.bat\ndocker exec spug rm -rf /data/spug/spug_web/build\ndocker cp E:\\TDYW\\spug-3.0\\spug_web\\build spug:/data/spug/spug_web/build\ndocker exec spug supervisorctl restart nginx\ndocker restart spugcd E:\\TDYW\\spug-3.0\\spug_web\n.\\build.bat\ndocker exec spug rm -rf /data/spug/spug_web/build\ndocker cp E:\\TDYW\\spug-3.0\\spug_web\\build spug:/data/spug/spug_web/build\ndocker exec spug supervisorctl restart nginx\ndocker restart spugcd E:\\TDYW\\spug-3.0\\spug_web\n.\\build.bat\ndocker exec spug rm -rf /data/spug/spug_web/build\ndocker cp E:\\TDYW\\spug-3.0\\spug_web\\build spug:/data/spug/spug_web/build\ndocker exec spug supervisorctl restart nginx\ndocker restart spugcd E:\\TDYW\\spug-3.0\\spug_web\n.\\build.bat\ndocker exec spug rm -rf /data/spug/spug_web/build\ndocker cp E:\\TDYW\\spug-3.0\\spug_web\\build spug:/data/spug/spug_web/build\ndocker exec spug supervisorctl restart nginx\ndocker restart spug','崔林杰、林杰','崔林杰','2026-01-21 10:13:16',5,NULL,NULL),
(4,'晋江系统','2026-01-08','啊','崔林杰、林杰','崔林杰','2026-01-21 11:50:45',5,NULL,NULL),
(5,'自动转报系统','2026-01-08','545654','崔林杰、林杰','崔林杰','2026-01-21 12:08:45',5,NULL,NULL),
(6,'晋江系统','2026-01-01','111',NULL,NULL,'2026-01-21 12:13:06',5,NULL,NULL),
(7,'自动转报系统','2026-01-15','阿萨','飒飒','阿萨斯','2026-01-21 22:42:11',5,NULL,NULL),
(8,'自动转报系统','2026-01-23','娃娃','崔林杰、林杰','崔林杰','2026-01-24 23:49:59',5,NULL,NULL);
/*!40000 ALTER TABLE `exec_run_logs` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `exec_schedule`
--

DROP TABLE IF EXISTS `exec_schedule`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exec_schedule` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `staff_id` int(11) NOT NULL,
  `staff_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `schedule_date` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `shift_id` int(11) NOT NULL,
  `shift_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `shift_time_id` int(11) DEFAULT NULL,
  `notes` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `updated_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_schedule` (`staff_id`,`schedule_date`),
  KEY `schedule_date` (`schedule_date`),
  KEY `shift_id` (`shift_id`),
  KEY `staff_id` (`staff_id`)
) ENGINE=InnoDB AUTO_INCREMENT=262 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exec_schedule`
--

LOCK TABLES `exec_schedule` WRITE;
/*!40000 ALTER TABLE `exec_schedule` DISABLE KEYS */;
INSERT INTO `exec_schedule` VALUES
(162,19,'员工5','2026-01-02',12,'上一休二',NULL,'','2026-01-26 10:00:55',5,'2026-01-28 18:30:39',9),
(163,15,'员工1','2026-01-05',14,'主副休休',NULL,'','2026-01-26 10:00:55',5,NULL,NULL),
(164,15,'员工1','2026-01-09',14,'主副休休',NULL,'','2026-01-26 10:00:55',5,NULL,NULL),
(165,15,'员工1','2026-01-13',14,'主副休休',NULL,'','2026-01-26 10:00:55',5,NULL,NULL),
(166,15,'员工1','2026-01-17',14,'主副休休',NULL,'','2026-01-26 10:00:55',5,NULL,NULL),
(167,15,'员工1','2026-01-21',14,'主副休休',NULL,'','2026-01-26 10:00:55',5,NULL,NULL),
(168,15,'员工1','2026-01-25',14,'主副休休',NULL,'','2026-01-26 10:00:55',5,NULL,NULL),
(169,15,'员工1','2026-01-29',14,'主副休休',NULL,'','2026-01-26 10:00:55',5,NULL,NULL),
(179,16,'员工2','2026-01-06',14,'主副休休',NULL,'','2026-01-26 10:01:43',5,NULL,NULL),
(180,16,'员工2','2026-01-10',14,'主副休休',NULL,'','2026-01-26 10:01:43',5,NULL,NULL),
(181,16,'员工2','2026-01-14',14,'主副休休',NULL,'','2026-01-26 10:01:43',5,NULL,NULL),
(182,16,'员工2','2026-01-18',14,'主副休休',NULL,'','2026-01-26 10:01:43',5,NULL,NULL),
(183,16,'员工2','2026-01-22',14,'主副休休',NULL,'','2026-01-26 10:01:43',5,NULL,NULL),
(184,16,'员工2','2026-01-26',14,'主副休休',NULL,'','2026-01-26 10:01:43',5,NULL,NULL),
(185,16,'员工2','2026-01-30',14,'主副休休',NULL,'','2026-01-26 10:01:43',5,NULL,NULL),
(186,17,'员工3','2026-01-03',14,'主副休休',NULL,'','2026-01-26 10:01:54',5,NULL,NULL),
(187,17,'员工3','2026-01-07',14,'主副休休',NULL,'','2026-01-26 10:01:54',5,NULL,NULL),
(188,17,'员工3','2026-01-11',14,'主副休休',NULL,'','2026-01-26 10:01:54',5,NULL,NULL),
(189,17,'员工3','2026-01-15',14,'主副休休',NULL,'','2026-01-26 10:01:54',5,NULL,NULL),
(190,17,'员工3','2026-01-19',14,'主副休休',NULL,'','2026-01-26 10:01:54',5,NULL,NULL),
(191,17,'员工3','2026-01-23',14,'主副休休',NULL,'','2026-01-26 10:01:54',5,NULL,NULL),
(192,17,'员工3','2026-01-27',14,'主副休休',NULL,'','2026-01-26 10:01:54',5,NULL,NULL),
(193,17,'员工3','2026-01-31',14,'主副休休',NULL,'','2026-01-26 10:01:54',5,NULL,NULL),
(194,18,'员工4','2026-01-04',14,'主副休休',NULL,'','2026-01-26 10:02:13',5,NULL,NULL),
(195,18,'员工4','2026-01-08',14,'主副休休',NULL,'','2026-01-26 10:02:13',5,NULL,NULL),
(196,18,'员工4','2026-01-12',14,'主副休休',NULL,'','2026-01-26 10:02:13',5,NULL,NULL),
(197,18,'员工4','2026-01-16',14,'主副休休',NULL,'','2026-01-26 10:02:13',5,NULL,NULL),
(198,18,'员工4','2026-01-20',14,'主副休休',NULL,'','2026-01-26 10:02:13',5,NULL,NULL),
(199,18,'员工4','2026-01-24',14,'主副休休',NULL,'','2026-01-26 10:02:13',5,NULL,NULL),
(200,18,'员工4','2026-01-28',14,'主副休休',NULL,'','2026-01-26 10:02:13',5,NULL,NULL),
(201,16,'员工2','2026-01-01',14,'主副休休',NULL,'','2026-01-26 10:02:46',5,'2026-01-28 18:30:39',9),
(202,19,'员工5','2026-01-04',12,'上一休二',NULL,'','2026-01-26 10:02:46',5,NULL,NULL),
(203,19,'员工5','2026-01-07',12,'上一休二',NULL,'','2026-01-26 10:02:46',5,NULL,NULL),
(204,19,'员工5','2026-01-10',12,'上一休二',NULL,'','2026-01-26 10:02:46',5,NULL,NULL),
(205,19,'员工5','2026-01-13',12,'上一休二',NULL,'','2026-01-26 10:02:46',5,NULL,NULL),
(206,19,'员工5','2026-01-16',12,'上一休二',NULL,'','2026-01-26 10:02:46',5,NULL,NULL),
(207,19,'员工5','2026-01-19',12,'上一休二',NULL,'','2026-01-26 10:02:46',5,NULL,NULL),
(208,19,'员工5','2026-01-22',12,'上一休二',NULL,'','2026-01-26 10:02:46',5,NULL,NULL),
(209,19,'员工5','2026-01-25',12,'上一休二',NULL,'','2026-01-26 10:02:46',5,NULL,NULL),
(210,19,'员工5','2026-01-28',12,'上一休二',NULL,'','2026-01-26 10:02:46',5,NULL,NULL),
(211,19,'员工5','2026-01-31',12,'上一休二',NULL,'','2026-01-26 10:02:46',5,NULL,NULL),
(212,20,'员工6','2026-01-02',16,'上二休四',NULL,'','2026-01-26 10:02:58',5,NULL,NULL),
(213,20,'员工6','2026-01-03',16,'上二休四',NULL,'','2026-01-26 10:02:58',5,NULL,NULL),
(214,20,'员工6','2026-01-08',16,'上二休四',NULL,'','2026-01-26 10:02:58',5,NULL,NULL),
(215,20,'员工6','2026-01-09',16,'上二休四',NULL,'','2026-01-26 10:02:58',5,NULL,NULL),
(216,20,'员工6','2026-01-14',16,'上二休四',NULL,'','2026-01-26 10:02:58',5,NULL,NULL),
(217,20,'员工6','2026-01-15',16,'上二休四',NULL,'','2026-01-26 10:02:58',5,NULL,NULL),
(218,20,'员工6','2026-01-20',16,'上二休四',NULL,'','2026-01-26 10:02:58',5,NULL,NULL),
(219,20,'员工6','2026-01-21',16,'上二休四',NULL,'','2026-01-26 10:02:58',5,NULL,NULL),
(220,20,'员工6','2026-01-26',16,'上二休四',NULL,'','2026-01-26 10:02:58',5,NULL,NULL),
(221,20,'员工6','2026-01-27',16,'上二休四',NULL,'','2026-01-26 10:02:58',5,NULL,NULL),
(222,21,'员工7','2026-01-05',16,'上二休四',NULL,'','2026-01-26 10:03:17',5,NULL,NULL),
(223,21,'员工7','2026-01-06',16,'上二休四',NULL,'','2026-01-26 10:03:17',5,NULL,NULL),
(224,21,'员工7','2026-01-11',16,'上二休四',NULL,'','2026-01-26 10:03:17',5,NULL,NULL),
(225,21,'员工7','2026-01-12',16,'上二休四',NULL,'','2026-01-26 10:03:17',5,NULL,NULL),
(226,21,'员工7','2026-01-17',16,'上二休四',NULL,'','2026-01-26 10:03:17',5,NULL,NULL),
(227,21,'员工7','2026-01-18',16,'上二休四',NULL,'','2026-01-26 10:03:17',5,NULL,NULL),
(228,21,'员工7','2026-01-23',16,'上二休四',NULL,'','2026-01-26 10:03:17',5,NULL,NULL),
(229,21,'员工7','2026-01-24',16,'上二休四',NULL,'','2026-01-26 10:03:17',5,NULL,NULL),
(230,21,'员工7','2026-01-29',16,'上二休四',NULL,'','2026-01-26 10:03:17',5,NULL,NULL),
(231,21,'员工7','2026-01-30',16,'上二休四',NULL,'','2026-01-26 10:03:17',5,NULL,NULL),
(261,15,'员工1','2026-01-01',14,'主副休休',NULL,'','2026-01-28 18:19:39',5,'2026-01-28 18:30:34',9);
/*!40000 ALTER TABLE `exec_schedule` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `exec_schedule_shift`
--

DROP TABLE IF EXISTS `exec_schedule_shift`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exec_schedule_shift` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `work_days` int(11) DEFAULT NULL,
  `rest_days` int(11) DEFAULT NULL,
  `shift_type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `color` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_default` tinyint(1) DEFAULT 0,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `updated_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `shift_type` (`shift_type`),
  KEY `is_default` (`is_default`)
) ENGINE=InnoDB AUTO_INCREMENT=17 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exec_schedule_shift`
--

LOCK TABLES `exec_schedule_shift` WRITE;
/*!40000 ALTER TABLE `exec_schedule_shift` DISABLE KEYS */;
INSERT INTO `exec_schedule_shift` VALUES
(12,'上一休二',1,2,'work_rest',NULL,'#1890ff',0,'2026-01-24 00:30:14',5,NULL,NULL),
(14,'主副休休',1,3,'work_rest',NULL,'#ff1aec',0,'2026-01-24 00:45:40',5,NULL,NULL),
(16,'上二休四',2,4,'work_rest',NULL,'#1aff47',0,'2026-01-24 15:24:33',5,NULL,NULL);
/*!40000 ALTER TABLE `exec_schedule_shift` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `exec_schedule_shift_time`
--

DROP TABLE IF EXISTS `exec_schedule_shift_time`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exec_schedule_shift_time` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `shift_id` int(11) NOT NULL,
  `shift_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `start_time` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `end_time` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `color` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `sort_order` int(11) DEFAULT 0,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `updated_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `shift_id` (`shift_id`),
  KEY `shift_name` (`shift_name`)
) ENGINE=InnoDB AUTO_INCREMENT=11 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exec_schedule_shift_time`
--

LOCK TABLES `exec_schedule_shift_time` WRITE;
/*!40000 ALTER TABLE `exec_schedule_shift_time` DISABLE KEYS */;
INSERT INTO `exec_schedule_shift_time` VALUES
(1,1,'白班','08:00','18:00','#52c41a',1,'2026-01-23 04:06:27',1,NULL,NULL),
(2,2,'夜班','18:00','08:00','#1890ff',2,'2026-01-23 04:06:27',1,NULL,NULL),
(3,1,'白班','08:00','18:00','#52c41a',1,'2026-01-23 04:07:39',1,NULL,NULL),
(4,2,'夜班','18:00','08:00','#1890ff',2,'2026-01-23 04:07:39',1,NULL,NULL),
(5,1,'白班','08:00','18:00','#52c41a',1,'2026-01-23 04:07:49',1,NULL,NULL),
(6,2,'夜班','18:00','08:00','#1890ff',2,'2026-01-23 04:07:49',1,NULL,NULL);
/*!40000 ALTER TABLE `exec_schedule_shift_time` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `exec_schedule_staff`
--

DROP TABLE IF EXISTS `exec_schedule_staff`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exec_schedule_staff` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) DEFAULT NULL,
  `user_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `department` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `phone` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_active` tinyint(1) DEFAULT 1,
  `unavailable_dates` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `updated_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `user_id` (`user_id`),
  KEY `is_active` (`is_active`)
) ENGINE=InnoDB AUTO_INCREMENT=25 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exec_schedule_staff`
--

LOCK TABLES `exec_schedule_staff` WRITE;
/*!40000 ALTER TABLE `exec_schedule_staff` DISABLE KEYS */;
INSERT INTO `exec_schedule_staff` VALUES
(1,6,'曹春城',NULL,NULL,0,'[]','2026-01-23 14:03:09',5,NULL,NULL),
(2,5,'12',NULL,NULL,0,'[]','2026-01-23 14:03:24',5,NULL,NULL),
(3,NULL,'曹春城',NULL,NULL,0,'[]','2026-01-23 14:38:37',5,NULL,NULL),
(4,NULL,'崔林杰',NULL,NULL,0,'[]','2026-01-23 23:51:24',5,NULL,NULL),
(5,NULL,'阿萨德',NULL,NULL,0,'[]','2026-01-23 23:51:37',5,NULL,NULL),
(6,NULL,'曹泽辉',NULL,NULL,0,'[]','2026-01-24 00:22:25',5,NULL,NULL),
(7,NULL,'林杰',NULL,NULL,0,'[]','2026-01-24 11:10:25',5,NULL,NULL),
(8,NULL,'何文辉',NULL,NULL,0,'[]','2026-01-24 11:10:34',5,NULL,NULL),
(9,NULL,'付扬',NULL,NULL,0,'[]','2026-01-24 11:10:50',5,NULL,NULL),
(10,NULL,'付杰',NULL,NULL,0,'[]','2026-01-24 11:10:55',5,NULL,NULL),
(11,NULL,'李钊',NULL,NULL,0,'[]','2026-01-24 11:10:58',5,NULL,NULL),
(12,NULL,'孙茂程',NULL,NULL,0,'[]','2026-01-24 11:11:09',5,NULL,NULL),
(13,NULL,'吕福羲',NULL,NULL,0,'[]','2026-01-24 11:11:18',5,NULL,NULL),
(14,NULL,'陈鲁明',NULL,NULL,0,'[]','2026-01-24 11:11:27',5,NULL,NULL),
(15,NULL,'员工1',NULL,NULL,1,'[]','2026-01-25 21:31:13',5,NULL,NULL),
(16,NULL,'员工2',NULL,NULL,1,'[]','2026-01-25 21:31:18',5,NULL,NULL),
(17,NULL,'员工3',NULL,NULL,1,'[]','2026-01-25 21:31:27',5,NULL,NULL),
(18,NULL,'员工4',NULL,NULL,1,'[]','2026-01-25 21:31:33',5,NULL,NULL),
(19,NULL,'员工5',NULL,NULL,1,'[]','2026-01-25 21:31:36',5,NULL,NULL),
(20,NULL,'员工6',NULL,NULL,1,'[]','2026-01-25 21:31:39',5,NULL,NULL),
(21,NULL,'员工7',NULL,NULL,1,'[]','2026-01-25 21:31:42',5,NULL,NULL),
(22,NULL,'员工7',NULL,NULL,0,'[]','2026-01-25 21:31:45',5,NULL,NULL),
(23,NULL,'员工8',NULL,NULL,1,'[]','2026-01-25 21:31:52',5,NULL,NULL),
(24,NULL,'员工9',NULL,NULL,1,'[]','2026-01-25 21:31:55',5,NULL,NULL);
/*!40000 ALTER TABLE `exec_schedule_staff` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `exec_schedule_substitute`
--

DROP TABLE IF EXISTS `exec_schedule_substitute`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exec_schedule_substitute` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `original_staff_id` int(11) NOT NULL COMMENT '原值班人ID',
  `original_staff_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '原值班人姓名',
  `substitute_staff_id` int(11) NOT NULL COMMENT '替班人ID',
  `substitute_staff_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '替班人姓名',
  `schedule_date` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '替班日期',
  `shift_id` int(11) NOT NULL COMMENT '班次ID',
  `shift_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '班次名称',
  `reason` text COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '替班原因',
  `status` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT 'pending' COMMENT '状态: pending待审批, approved已通过, rejected已拒绝, cancelled已取消',
  `approved_by_id` int(11) DEFAULT NULL COMMENT '审批人ID',
  `approved_by_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '审批人姓名',
  `approved_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '审批时间',
  `remarks` text COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '审批备注',
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `updated_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `schedule_date` (`schedule_date`),
  KEY `status` (`status`),
  KEY `original_staff_id` (`original_staff_id`),
  KEY `substitute_staff_id` (`substitute_staff_id`)
) ENGINE=InnoDB AUTO_INCREMENT=11 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='替班记录表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exec_schedule_substitute`
--

LOCK TABLES `exec_schedule_substitute` WRITE;
/*!40000 ALTER TABLE `exec_schedule_substitute` DISABLE KEYS */;
INSERT INTO `exec_schedule_substitute` VALUES
(9,15,'员工1',16,'员工2','2026-01-02',14,'主副休休','','approved',9,'zidonghuake','2026-01-28 18:29:14','','2026-01-28 18:29:11',9,'2026-01-28 18:29:14',9),
(10,16,'员工2',15,'员工1','2026-01-01',14,'主副休休','','approved',9,'zidonghuake','2026-01-28 18:30:34','','2026-01-28 18:30:32',9,'2026-01-28 18:30:34',9);
/*!40000 ALTER TABLE `exec_schedule_substitute` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `exec_schedule_swap`
--

DROP TABLE IF EXISTS `exec_schedule_swap`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exec_schedule_swap` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `from_staff_id` int(11) NOT NULL COMMENT '申请人ID',
  `from_staff_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '申请人姓名',
  `to_staff_id` int(11) NOT NULL COMMENT '被换人ID',
  `to_staff_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '被换人姓名',
  `from_date` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `to_date` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `schedule_date` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '换班日期',
  `from_shift_id` int(11) NOT NULL COMMENT '申请人班次ID',
  `from_shift_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '申请人班次名称',
  `to_shift_id` int(11) NOT NULL COMMENT '被换人班次ID',
  `to_shift_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '被换人班次名称',
  `reason` text COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '换班原因',
  `status` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT 'pending' COMMENT '状态: pending待审批, approved已通过, rejected已拒绝, cancelled已取消',
  `approved_by_id` int(11) DEFAULT NULL COMMENT '审批人ID',
  `approved_by_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '审批人姓名',
  `approved_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '审批时间',
  `remarks` text COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '审批备注',
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `updated_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `schedule_date` (`schedule_date`),
  KEY `status` (`status`),
  KEY `from_staff_id` (`from_staff_id`),
  KEY `to_staff_id` (`to_staff_id`)
) ENGINE=InnoDB AUTO_INCREMENT=15 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='换班记录表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exec_schedule_swap`
--

LOCK TABLES `exec_schedule_swap` WRITE;
/*!40000 ALTER TABLE `exec_schedule_swap` DISABLE KEYS */;
INSERT INTO `exec_schedule_swap` VALUES
(13,15,'员工1',16,'员工2','2026-01-01','2026-01-02','2026-01-01',14,'主副休休',14,'主副休休','','approved',9,'zidonghuake','2026-01-28 18:28:58','','2026-01-28 18:28:53',9,'2026-01-28 18:28:58',9),
(14,19,'员工5',16,'员工2','2026-01-01','2026-01-02','2026-01-01',12,'上一休二',14,'主副休休','','approved',9,'zidonghuake','2026-01-28 18:30:39','','2026-01-28 18:29:30',9,'2026-01-28 18:30:39',9);
/*!40000 ALTER TABLE `exec_schedule_swap` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `exec_templates`
--

DROP TABLE IF EXISTS `exec_templates`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exec_templates` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `body` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `interpreter` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `host_ids` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `desc` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `parameters` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `updated_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `exec_templates_created_by_id_7aa08310_fk_users_id` (`created_by_id`),
  KEY `exec_templates_updated_by_id_d219fc24_fk_users_id` (`updated_by_id`),
  CONSTRAINT `exec_templates_created_by_id_7aa08310_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `exec_templates_updated_by_id_d219fc24_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exec_templates`
--

LOCK TABLES `exec_templates` WRITE;
/*!40000 ALTER TABLE `exec_templates` DISABLE KEYS */;
INSERT INTO `exec_templates` VALUES
(1,'111','11','1111','sh','[]',NULL,'[]','2026-01-20 13:29:24',5,NULL,NULL);
/*!40000 ALTER TABLE `exec_templates` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `exec_transfer`
--

DROP TABLE IF EXISTS `exec_transfer`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exec_transfer` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `digest` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `host_id` int(11) DEFAULT NULL,
  `src_dir` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `dst_dir` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `host_ids` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  KEY `exec_transfer_user_id_ec8f8fdf_fk_users_id` (`user_id`),
  KEY `exec_transfer_digest_b3f7d4b8` (`digest`),
  CONSTRAINT `exec_transfer_user_id_ec8f8fdf_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exec_transfer`
--

LOCK TABLES `exec_transfer` WRITE;
/*!40000 ALTER TABLE `exec_transfer` DISABLE KEYS */;
/*!40000 ALTER TABLE `exec_transfer` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `exec_upgrade_records`
--

DROP TABLE IF EXISTS `exec_upgrade_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `exec_upgrade_records` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `upgrade_no` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `system` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `upgrade_type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `version` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `plan_time` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'å¾…å¤„ç†',
  `result` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `owner` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `actual_time` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `duration` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `checklist` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `dependencies` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `issues` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `lessons` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `updated_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `upgrade_no` (`upgrade_no`),
  KEY `system` (`system`),
  KEY `status` (`status`),
  KEY `plan_time` (`plan_time`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exec_upgrade_records`
--

LOCK TABLES `exec_upgrade_records` WRITE;
/*!40000 ALTER TABLE `exec_upgrade_records` DISABLE KEYS */;
INSERT INTO `exec_upgrade_records` VALUES
(1,'123','123','功能升级','12121','2026-01-22 00:00:06','待处理','成功','曹春城',NULL,NULL,'[{\"id\": 1769046217466, \"text\": \"1\", \"checked\": false}, {\"id\": 1769046218588, \"text\": \"2\", \"checked\": false}]','[]','[]',NULL,'2026-01-22 09:38:35',5,'2026-01-22 09:43:39',5),
(2,'124','自动转报系统','Bug修复','12121','2026-01-22 00:06:07','待处理',NULL,'曹春城',NULL,NULL,'[{\"id\": 1769046258818, \"text\": \"1\", \"checked\": false}, {\"id\": 1769046259779, \"text\": \"1\", \"checked\": false}]','[{\"id\": 1769046270826, \"upgrade_no\": \"123\"}]','[{\"id\": 1769046300859, \"description\": \"123\", \"severity\": \"\\u4f4e\", \"status\": \"\\u5f85\\u5904\\u7406\"}]','121','2026-01-22 09:44:21',5,'2026-01-22 09:45:11',5);
/*!40000 ALTER TABLE `exec_upgrade_records` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `login_histories`
--

DROP TABLE IF EXISTS `login_histories`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `login_histories` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `username` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `type` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `ip` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `agent` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `message` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_success` tinyint(1) NOT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=191 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `login_histories`
--

LOCK TABLES `login_histories` WRITE;
/*!40000 ALTER TABLE `login_histories` DISABLE KEYS */;
INSERT INTO `login_histories` VALUES
(19,'admin','APP','172.20.0.1','Other / Other / curl 8.16.0',NULL,1,'2026-01-20 12:24:49'),
(20,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0','用户名或密码错误，连续多次错误账户将会被禁用',0,'2026-01-20 12:25:16'),
(21,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0','用户名或密码错误，连续多次错误账户将会被禁用',0,'2026-01-20 12:25:52'),
(22,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0','用户名或密码错误，连续多次错误账户将会被禁用',0,'2026-01-20 12:26:27'),
(23,'admin','APP','172.20.0.1','Other / Other / curl 8.16.0',NULL,1,'2026-01-20 12:26:32'),
(24,'admin','default','172.20.0.1','Other / Other / curl 8.16.0',NULL,1,'2026-01-20 12:29:23'),
(25,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 12:29:39'),
(26,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 12:30:19'),
(27,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 13:16:07'),
(28,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 13:27:41'),
(29,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 13:27:49'),
(30,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 13:49:23'),
(31,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 13:49:56'),
(32,'admin1','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 13:50:47'),
(33,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 13:50:54'),
(34,'admin1','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 13:51:26'),
(35,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 13:51:33'),
(36,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 13:59:02'),
(37,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 14:17:08'),
(38,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 16:22:02'),
(39,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 16:34:07'),
(40,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 16:41:17'),
(41,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 16:49:25'),
(42,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 22:16:57'),
(43,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-20 22:56:30'),
(44,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-21 08:38:00'),
(45,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-21 10:07:40'),
(46,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-21 10:09:16'),
(47,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-21 10:16:44'),
(48,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-21 10:22:18'),
(49,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-21 10:39:47'),
(50,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-21 12:08:26'),
(51,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-21 12:49:29'),
(52,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-21 12:50:28'),
(53,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-22 09:25:04'),
(54,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-22 21:36:29'),
(55,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-23 09:43:06'),
(56,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-23 11:45:14'),
(57,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-23 20:24:13'),
(58,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-23 20:36:28'),
(59,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-23 22:57:04'),
(60,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-24 00:08:53'),
(61,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-24 00:18:41'),
(62,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-24 00:21:00'),
(63,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-24 00:40:27'),
(64,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-24 01:07:37'),
(65,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-24 01:09:50'),
(66,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-24 09:37:33'),
(67,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-24 11:32:01'),
(68,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-24 11:34:37'),
(69,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-24 11:35:33'),
(70,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-24 11:41:21'),
(71,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-24 11:47:48'),
(72,'admin','','127.0.0.1','Other / Other / curl 7.81.0','用户名或密码错误，连续多次错误账户将会被禁用',0,'2026-01-24 20:47:10'),
(73,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-24 20:47:28'),
(74,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-24 21:30:25'),
(75,'admin','','127.0.0.1','Other / Other / curl 7.81.0','用户名或密码错误，连续多次错误账户将会被禁用',0,'2026-01-24 21:42:37'),
(76,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-24 21:44:01'),
(77,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-24 21:49:17'),
(78,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-25 00:01:14'),
(79,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-25 09:00:49'),
(80,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-25 10:35:16'),
(81,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-25 10:53:00'),
(82,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-25 10:53:37'),
(83,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-25 10:53:49'),
(84,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-25 12:53:04'),
(85,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-25 12:59:23'),
(86,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-25 20:12:16'),
(87,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-25 20:22:18'),
(88,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0','用户名或密码错误，连续多次错误账户将会被禁用',0,'2026-01-25 21:07:57'),
(89,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-25 21:07:58'),
(90,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-25 21:08:07'),
(91,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-25 22:48:20'),
(92,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-25 22:57:26'),
(93,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 08:58:39'),
(94,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 09:26:15'),
(95,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 09:30:11'),
(96,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 13:15:46'),
(97,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 13:23:29'),
(98,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 15:44:29'),
(99,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 16:03:26'),
(100,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 16:03:34'),
(101,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 16:04:02'),
(102,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 16:04:15'),
(103,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 16:04:52'),
(104,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 16:05:10'),
(105,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 16:05:36'),
(106,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 16:11:53'),
(107,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 16:12:09'),
(108,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 16:12:23'),
(109,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 16:12:41'),
(110,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 19:22:37'),
(111,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 20:52:54'),
(112,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 20:59:12'),
(113,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 21:04:33'),
(114,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 21:24:58'),
(115,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-26 21:33:36'),
(116,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 00:07:42'),
(117,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 00:14:14'),
(118,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 00:16:07'),
(119,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 00:20:01'),
(120,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 09:20:04'),
(121,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 09:40:28'),
(122,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 09:49:07'),
(123,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 09:50:22'),
(124,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 09:51:21'),
(125,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 09:54:21'),
(126,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 09:54:31'),
(127,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 10:11:40'),
(128,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 10:32:58'),
(129,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 10:36:44'),
(130,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 10:39:38'),
(131,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 10:46:50'),
(132,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 10:55:13'),
(133,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 14:04:33'),
(134,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 14:05:21'),
(135,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 14:07:32'),
(136,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 14:07:48'),
(137,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 14:08:57'),
(138,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 14:09:22'),
(139,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 14:14:32'),
(140,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 14:15:02'),
(141,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 16:27:33'),
(142,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 16:28:16'),
(143,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 16:33:19'),
(144,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 16:43:53'),
(145,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 16:44:29'),
(146,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 16:46:34'),
(147,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 16:50:21'),
(148,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 18:46:09'),
(149,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 18:46:14'),
(150,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 18:49:57'),
(151,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 18:50:33'),
(152,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 18:50:40'),
(153,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 18:50:55'),
(154,'zidonghuake','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 19:26:44'),
(155,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 19:27:01'),
(156,'zidonghuake','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 19:27:41'),
(157,'zidonghuake','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 19:28:01'),
(158,'zidonghuake','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 19:28:12'),
(159,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 19:32:05'),
(160,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 19:43:04'),
(161,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 19:46:32'),
(162,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 19:49:43'),
(163,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 19:51:56'),
(164,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 19:53:01'),
(165,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 21:42:53'),
(166,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 21:43:12'),
(167,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 23:50:00'),
(168,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 23:50:32'),
(169,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-27 23:51:01'),
(170,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 09:38:07'),
(171,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 09:39:10'),
(172,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 10:08:09'),
(173,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 10:11:43'),
(174,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 10:20:07'),
(175,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 10:20:41'),
(176,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 10:21:19'),
(177,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 10:21:56'),
(178,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 16:27:29'),
(179,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 16:53:13'),
(180,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 16:58:42'),
(181,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 16:58:57'),
(182,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 17:32:07'),
(183,'tongxinke','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 17:32:26'),
(184,'zidonghuake','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 17:33:06'),
(185,'zidonghuake','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 17:33:20'),
(186,'zidonghuake','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 17:33:50'),
(187,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 18:54:44'),
(188,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 19:01:44'),
(189,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-28 19:30:54'),
(190,'admin','default','172.20.0.1','PC / Windows 10 / Edge 144.0.0',NULL,1,'2026-01-29 08:49:09');
/*!40000 ALTER TABLE `login_histories` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `navigations`
--

DROP TABLE IF EXISTS `navigations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `navigations` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
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
  `id` int(11) NOT NULL AUTO_INCREMENT,
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
-- Table structure for table `notifies`
--

DROP TABLE IF EXISTS `notifies`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `notifies` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `title` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `source` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `type` varchar(2) COLLATE utf8mb4_unicode_ci NOT NULL,
  `content` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `unread` tinyint(1) NOT NULL,
  `link` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `notifies`
--

LOCK TABLES `notifies` WRITE;
/*!40000 ALTER TABLE `notifies` DISABLE KEYS */;
/*!40000 ALTER TABLE `notifies` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `repositories`
--

DROP TABLE IF EXISTS `repositories`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `repositories` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `app_id` int(11) NOT NULL,
  `env_id` int(11) NOT NULL,
  `deploy_id` int(11) NOT NULL,
  `version` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `spug_version` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `remarks` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `extra` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(2) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime(6) NOT NULL,
  `created_by_id` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `repositories_app_id_c9b36bc1_fk_apps_id` (`app_id`),
  KEY `repositories_env_id_3c1fe483_fk_environments_id` (`env_id`),
  KEY `repositories_deploy_id_86833134_fk_deploys_id` (`deploy_id`),
  KEY `repositories_created_by_id_3cc1d549_fk_users_id` (`created_by_id`),
  CONSTRAINT `repositories_app_id_c9b36bc1_fk_apps_id` FOREIGN KEY (`app_id`) REFERENCES `apps` (`id`),
  CONSTRAINT `repositories_created_by_id_3cc1d549_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `repositories_deploy_id_86833134_fk_deploys_id` FOREIGN KEY (`deploy_id`) REFERENCES `deploys` (`id`),
  CONSTRAINT `repositories_env_id_3c1fe483_fk_environments_id` FOREIGN KEY (`env_id`) REFERENCES `environments` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `repositories`
--

LOCK TABLES `repositories` WRITE;
/*!40000 ALTER TABLE `repositories` DISABLE KEYS */;
/*!40000 ALTER TABLE `repositories` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `roles`
--

DROP TABLE IF EXISTS `roles`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `roles` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `desc` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `page_perms` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `deploy_perms` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `group_perms` longtext COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `roles_created_by_id_4f97b4da_fk_users_id` (`created_by_id`),
  CONSTRAINT `roles_created_by_id_4f97b4da_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `roles`
--

LOCK TABLES `roles` WRITE;
/*!40000 ALTER TABLE `roles` DISABLE KEYS */;
INSERT INTO `roles` VALUES
(1,'导航科',NULL,'{\"dashboard\": {\"dashboard\": []}, \"host\": {\"host\": [], \"console\": []}, \"document\": {\"document\": []}, \"exec\": {\"runlog\": []}, \"interference\": {\"interference\": []}, \"upgrade\": {\"upgrade\": [], \"statistics\": []}, \"duty\": {\"duty\": [], \"handover\": []}, \"schedule\": {\"schedule\": [\"view\", \"add\", \"edit\", \"del\", \"auto_schedule\"], \"swap\": [\"view\", \"add\", \"edit\", \"del\"], \"substitute\": [\"view\", \"add\", \"edit\", \"del\"]}, \"fault\": {\"faultrecord\": [], \"faultpart\": []}, \"task\": {\"schedule\": []}, \"config\": {\"env\": [], \"src\": [], \"app\": []}}',NULL,NULL,'2026-01-20 13:40:33',5),
(2,'通信科',NULL,'{\"dashboard\": {\"dashboard\": []}, \"host\": {\"host\": [], \"console\": []}, \"document\": {\"document\": [\"view\", \"upload\", \"download\", \"delete\", \"create_folder\", \"copy\", \"move\"]}, \"exec\": {\"runlog\": [\"view\", \"add\", \"edit\", \"del\"]}, \"interference\": {\"interference\": [\"view\", \"add\", \"edit\", \"del\"]}, \"upgrade\": {\"upgrade\": [\"view\", \"add\", \"edit\", \"del\"], \"statistics\": [\"view\"]}, \"duty\": {\"duty\": [\"view\", \"add\", \"edit\", \"del\"], \"handover\": [\"view\", \"add\", \"edit\", \"del\", \"confirm\"]}, \"schedule\": {\"schedule\": [\"view\", \"add\", \"edit\", \"del\", \"auto_schedule\"], \"swap\": [\"view\", \"add\", \"edit\", \"cancel\"], \"substitute\": [\"view\", \"add\", \"edit\", \"cancel\"]}, \"fault\": {\"faultrecord\": [\"view\", \"add\", \"edit\", \"del\"], \"faultpart\": [\"view\", \"add\", \"edit\", \"del\"]}, \"task\": {\"schedule\": []}, \"config\": {\"env\": [], \"src\": [], \"app\": []}, \"runlog\": {\"runlog\": [\"view\", \"add\", \"edit\", \"del\"]}}',NULL,NULL,'2026-01-25 21:08:33',5),
(3,'自动化',NULL,'{\"dashboard\": {\"dashboard\": []}, \"host\": {\"host\": [], \"console\": []}, \"document\": {\"document\": []}, \"exec\": {\"runlog\": []}, \"interference\": {\"interference\": []}, \"upgrade\": {\"upgrade\": [], \"statistics\": []}, \"duty\": {\"duty\": [], \"handover\": []}, \"schedule\": {\"schedule\": [\"view\", \"add\", \"edit\", \"del\", \"auto_schedule\"], \"swap\": [\"view\", \"add\", \"edit\", \"cancel\"], \"substitute\": [\"view\", \"add\", \"edit\", \"cancel\"]}, \"fault\": {\"faultrecord\": [], \"faultpart\": []}, \"task\": {\"schedule\": []}, \"config\": {\"env\": [], \"src\": [], \"app\": []}}',NULL,NULL,'2026-01-27 19:26:23',5);
/*!40000 ALTER TABLE `roles` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `services`
--

DROP TABLE IF EXISTS `services`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `services` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `key` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `desc` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `key` (`key`),
  KEY `services_created_by_id_6871d3a6_fk_users_id` (`created_by_id`),
  CONSTRAINT `services_created_by_id_6871d3a6_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `services`
--

LOCK TABLES `services` WRITE;
/*!40000 ALTER TABLE `services` DISABLE KEYS */;
/*!40000 ALTER TABLE `services` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `settings`
--

DROP TABLE IF EXISTS `settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `settings` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `key` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `desc` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `key` (`key`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `settings`
--

LOCK TABLES `settings` WRITE;
/*!40000 ALTER TABLE `settings` DISABLE KEYS */;
/*!40000 ALTER TABLE `settings` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `spug_document_file`
--

DROP TABLE IF EXISTS `spug_document_file`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `spug_document_file` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(200) NOT NULL COMMENT 'æ–‡ä»¶å',
  `folder_id` int(11) DEFAULT NULL COMMENT 'æ‰€å±žæ–‡ä»¶å¤¹ID',
  `file_path` varchar(500) NOT NULL COMMENT 'æ–‡ä»¶å­˜å‚¨è·¯å¾„',
  `file_size` bigint(20) NOT NULL DEFAULT 0 COMMENT 'æ–‡ä»¶å¤§å°(å­—èŠ‚)',
  `file_type` varchar(500) DEFAULT NULL,
  `created_by_id` int(11) DEFAULT NULL COMMENT 'ä¸Šä¼ äººID',
  `created_at` datetime NOT NULL COMMENT 'ä¸Šä¼ æ—¶é—´',
  PRIMARY KEY (`id`),
  KEY `spug_document_file_folder_id_idx` (`folder_id`),
  KEY `spug_document_file_created_by_id_idx` (`created_by_id`),
  CONSTRAINT `spug_document_file_created_by_id_refs_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`) ON DELETE SET NULL,
  CONSTRAINT `spug_document_file_folder_id_refs_id` FOREIGN KEY (`folder_id`) REFERENCES `spug_document_folder` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=66 DEFAULT CHARSET=utf8mb4 COMMENT='æ–‡æ¡£æ–‡ä»¶è¡¨';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `spug_document_file`
--

LOCK TABLES `spug_document_file` WRITE;
/*!40000 ALTER TABLE `spug_document_file` DISABLE KEYS */;
INSERT INTO `spug_document_file` VALUES
(64,'1.jpg',NULL,'/data/spug/spug_api/storage/documents/1_136979386013280.jpg',7610042,'image/jpeg',5,'2026-01-23 13:40:56'),
(65,'3.20通信科实操大纲.docx',74,'/data/spug/spug_api/storage/documents/3_124870485746896.docx',198210,'application/vnd.openxmlformats-officedocument.wordprocessingml.document',5,'2026-01-24 23:51:31');
/*!40000 ALTER TABLE `spug_document_file` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `spug_document_folder`
--

DROP TABLE IF EXISTS `spug_document_folder`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `spug_document_folder` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(200) NOT NULL COMMENT 'æ–‡ä»¶å¤¹åç§°',
  `parent_id` int(11) DEFAULT NULL COMMENT 'çˆ¶æ–‡ä»¶å¤¹ID',
  `created_by_id` int(11) DEFAULT NULL COMMENT 'åˆ›å»ºäººID',
  `created_at` datetime NOT NULL COMMENT 'åˆ›å»ºæ—¶é—´',
  `updated_at` datetime NOT NULL COMMENT 'æ›´æ–°æ—¶é—´',
  PRIMARY KEY (`id`),
  KEY `spug_document_folder_parent_id_idx` (`parent_id`),
  KEY `spug_document_folder_created_by_id_idx` (`created_by_id`),
  CONSTRAINT `spug_document_folder_created_by_id_refs_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`) ON DELETE SET NULL,
  CONSTRAINT `spug_document_folder_parent_id_refs_id` FOREIGN KEY (`parent_id`) REFERENCES `spug_document_folder` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=77 DEFAULT CHARSET=utf8mb4 COMMENT='æ–‡æ¡£æ–‡ä»¶å¤¹è¡¨';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `spug_document_folder`
--

LOCK TABLES `spug_document_folder` WRITE;
/*!40000 ALTER TABLE `spug_document_folder` DISABLE KEYS */;
INSERT INTO `spug_document_folder` VALUES
(70,'通信科',NULL,5,'2026-01-21 23:51:29','2026-01-21 23:51:29'),
(71,'自动转报系统',70,5,'2026-01-21 23:51:39','2026-01-21 23:51:39'),
(72,'晋江系统',70,5,'2026-01-21 23:51:44','2026-01-21 23:51:44'),
(73,'123',NULL,5,'2026-01-24 09:42:44','2026-01-24 09:42:44'),
(74,'111',NULL,5,'2026-01-24 23:51:16','2026-01-24 23:51:16'),
(75,'123',74,5,'2026-01-24 23:51:43','2026-01-24 23:51:43'),
(76,'2223455',74,5,'2026-01-24 23:51:52','2026-01-24 23:51:52');
/*!40000 ALTER TABLE `spug_document_folder` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `task_histories`
--

DROP TABLE IF EXISTS `task_histories`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `task_histories` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `task_id` int(11) NOT NULL,
  `status` smallint(6) NOT NULL,
  `run_time` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `output` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `task_histories`
--

LOCK TABLES `task_histories` WRITE;
/*!40000 ALTER TABLE `task_histories` DISABLE KEYS */;
INSERT INTO `task_histories` VALUES
(1,1,2,'2026-01-25 20:50:21','{\"local\": [127, 0.027, \"/bin/sh: 1: qwedf: not found\\n\"]}');
/*!40000 ALTER TABLE `task_histories` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `tasks`
--

DROP TABLE IF EXISTS `tasks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tasks` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `interpreter` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `command` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `targets` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `trigger` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `trigger_args` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  `desc` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `latest_id` int(11) DEFAULT NULL,
  `rst_notify` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) NOT NULL,
  `updated_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `updated_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `tasks_latest_id_79c3245c_fk_task_histories_id` (`latest_id`),
  KEY `tasks_created_by_id_454154e7_fk_users_id` (`created_by_id`),
  KEY `tasks_updated_by_id_1a0a4696_fk_users_id` (`updated_by_id`),
  CONSTRAINT `tasks_created_by_id_454154e7_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tasks_latest_id_79c3245c_fk_task_histories_id` FOREIGN KEY (`latest_id`) REFERENCES `task_histories` (`id`),
  CONSTRAINT `tasks_updated_by_id_1a0a4696_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tasks`
--

LOCK TABLES `tasks` WRITE;
/*!40000 ALTER TABLE `tasks` DISABLE KEYS */;
INSERT INTO `tasks` VALUES
(1,'洪心艺','阿萨斯','sh','qwedf','[\"local\"]','interval','1',0,NULL,NULL,'{\"mode\": \"0\"}','2026-01-25 20:50:12',5,NULL,NULL);
/*!40000 ALTER TABLE `tasks` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `user_role_rel`
--

DROP TABLE IF EXISTS `user_role_rel`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `user_role_rel` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `role_id` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `user_role_rel_user_id_role_id_62a7d1cf_uniq` (`user_id`,`role_id`),
  KEY `user_role_rel_role_id_57d24f6b_fk_roles_id` (`role_id`),
  CONSTRAINT `user_role_rel_role_id_57d24f6b_fk_roles_id` FOREIGN KEY (`role_id`) REFERENCES `roles` (`id`),
  CONSTRAINT `user_role_rel_user_id_b88b83f1_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `user_role_rel`
--

LOCK TABLES `user_role_rel` WRITE;
/*!40000 ALTER TABLE `user_role_rel` DISABLE KEYS */;
INSERT INTO `user_role_rel` VALUES
(2,7,2),
(4,8,1),
(3,9,3);
/*!40000 ALTER TABLE `user_role_rel` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `user_settings`
--

DROP TABLE IF EXISTS `user_settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `user_settings` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `key` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
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
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `username` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `nickname` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `password_hash` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `type` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_supper` tinyint(1) NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  `access_token` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `token_expired` int(11) DEFAULT NULL,
  `last_login` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `last_ip` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `wx_token` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_by_id` int(11) DEFAULT NULL,
  `deleted_at` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `deleted_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `users_created_by_id_19a92469_fk_users_id` (`created_by_id`),
  KEY `users_deleted_by_id_d342c553_fk_users_id` (`deleted_by_id`),
  CONSTRAINT `users_created_by_id_19a92469_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `users_deleted_by_id_d342c553_fk_users_id` FOREIGN KEY (`deleted_by_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `users`
--

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` VALUES
(5,'admin','管理员','pbkdf2_sha256$150000$z89pYxkiYBut$jQn+ZIakdLJUGtb0ERPUBY3h0EJ5+Mul3FCqgebvjzQ=','default',1,1,'63843cf6139d4e6c92eb9aa2cc3d5eb0',1769677523,'2026-01-29 08:49:09','172.20.0.1',NULL,'2026-01-20 04:24:23',NULL,NULL,NULL),
(6,'admin1','洪心艺','pbkdf2_sha256$150000$vYwwcfeeJsAj$1uv4LwN+ePYpLocOj3LkMy3qqwgMMhvuLwZW5JIcL4g=','default',0,1,'825397a285064fe3865f01bf36576a1c',0,'2026-01-20 13:51:26','172.20.0.1',NULL,'2026-01-20 13:50:34',5,'2026-01-25 21:06:02',5),
(7,'tongxinke','通信科','pbkdf2_sha256$150000$wAgHWlntm9Z6$NjzxZE7Rgg5QhCeJUxCaipMdZTORWITdoBUtFsxAQrk=','default',0,1,'49a48803dd1a45ca9b66d9d554c5267a',1769621555,'2026-01-28 17:32:26','172.20.0.1',NULL,'2026-01-25 21:05:52',5,NULL,NULL),
(8,'daohangke','导航科','pbkdf2_sha256$150000$BWrY4Sfyrjae$dKels22IDEUr1rMbiOcDD7/2KWn4tb1YN7+ATlSizM4=','default',0,1,'',0,'','',NULL,'2026-01-25 21:06:50',5,NULL,NULL),
(9,'zidonghuake','自动化科','pbkdf2_sha256$150000$P9jsNI5OcGbR$hsh7Fd1YomRGvFqeTQu3qojEd652GfK4xXzEtUkI8hA=','default',0,1,'4dbc38b828f243d9b1de89f0c9ae342a',1769626470,'2026-01-28 17:33:50','172.20.0.1',NULL,'2026-01-25 21:07:11',5,NULL,NULL);
/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-01-29  1:17:12
