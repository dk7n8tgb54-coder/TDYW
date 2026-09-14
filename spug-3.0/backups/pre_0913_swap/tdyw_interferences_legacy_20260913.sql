-- MariaDB dump 10.19  Distrib 10.8.2-MariaDB, for debian-linux-gnu (x86_64)
--
-- Host: localhost    Database: tdyw
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
  `datetime` datetime(6) NOT NULL,
  `coordinates` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `interference_type` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `phenomenon` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `flight_number` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `aircraft_type` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
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
  `review_comment` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
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
  `close_summary` longtext COLLATE utf8mb4_unicode_ci NOT NULL,
  `voided_by_id` int(11) DEFAULT NULL,
  `voided_by_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `voided_at` datetime(6) DEFAULT NULL,
  `void_reason` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `snapshot_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `deleted_at` datetime(6) DEFAULT NULL,
  `is_deleted` tinyint(1) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `tdyw_interferences_created_by_id_395767df_fk_users_id` (`created_by_id`),
  KEY `tdyw_interferences_updated_by_id_c34acb4f_fk_users_id` (`updated_by_id`),
  KEY `inter_status_idx` (`tenant_id`,`status`),
  KEY `inter_time_idx` (`tenant_id`,`datetime` DESC,`id` DESC),
  CONSTRAINT `tdyw_interferences_created_by_id_395767df_fk_users_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `tdyw_interferences_updated_by_id_c34acb4f_fk_users_id` FOREIGN KEY (`updated_by_id`) REFERENCES `users` (`id`),
  CONSTRAINT `interference_status_valid` CHECK (`status` in ('draft','submitted','reviewed','reported','handled','closed','voided')),
  CONSTRAINT `interference_submit_fields` CHECK (`status` = 'draft' or `status` = 'voided' or `submitted_by_id` is not null and `submitted_at` is not null and `submitted_by_name` <> '' and `snapshot_hash` <> ''),
  CONSTRAINT `interference_review_fields` CHECK (`status` not in ('reviewed','reported','handled','closed') or `reviewed_by_id` is not null and `reviewed_at` is not null and `reviewed_by_name` <> ''),
  CONSTRAINT `interference_report_fields` CHECK (`status` not in ('reported','handled','closed') or `reported_by_id` is not null and `reported_at` is not null and `reported_by_name` <> ''),
  CONSTRAINT `interference_handle_fields` CHECK (`status` not in ('handled','closed') or `handled_by_id` is not null and `handled_at` is not null and `handled_by_name` <> ''),
  CONSTRAINT `interference_close_fields` CHECK (`status` <> 'closed' or `closed_by_id` is not null and `closed_at` is not null and `closed_by_name` <> '' and `close_summary` is not null and (`close_summary` <> '' or `close_summary` is null)),
  CONSTRAINT `interference_void_fields` CHECK (`status` <> 'voided' or `voided_by_id` is not null and `voided_at` is not null and `voided_by_name` <> '' and `void_reason` <> '')
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `tdyw_interferences`
--

LOCK TABLES `tdyw_interferences` WRITE;
/*!40000 ALTER TABLE `tdyw_interferences` DISABLE KEYS */;
INSERT INTO `tdyw_interferences` VALUES
(1,'admin',0,'121.6','塔台','2026-08-04 15:03:33.000000','未知','外来干扰','1、下午3点-4点，综业地面121.6MHz有非法占用频道通话干扰，本场设备正常。填写无线电干扰申诉单（附声音文件），发无委协助排查。\n2、塔设、机坪塔台均无干扰，暂时把综业121.6静噪门限由C/N模式改为RSSI，RSSI数值由-101调为-90','','','是','2026-08-04 18:54:42.568170','2026-08-04 18:55:06.656615',1,1,'draft',NULL,'',NULL,NULL,'',NULL,'',NULL,NULL,'','','',NULL,'',NULL,NULL,'',NULL,'',NULL,'',NULL,'','','2026-08-04 18:57:36.779961',1),
(2,'tongxinke',0,'121.6','塔台','2026-08-04 15:03:00.000000','未知','外来干扰','1、下午3点-4点，综业地面121.6MHz有非法占用频道通话干扰，本场设备正常。填写无线电干扰申诉单（附声音文件），发无委协助排查。\n2、塔设、机坪塔台均无干扰，暂时把综业121.6静噪门限由C/N模式改为RSSI，RSSI数值由-101调为-90','','','是','2026-08-04 18:57:06.533637',NULL,5,NULL,'draft',NULL,'',NULL,NULL,'',NULL,'',NULL,NULL,'','','',NULL,'',NULL,NULL,'',NULL,'',NULL,'',NULL,'','',NULL,0),
(3,'tongxinke',0,'1','1','2026-07-08 09:46:12.000000','111','gps','11','1','1','是','2026-08-28 09:46:01.037388',NULL,4,NULL,'draft',NULL,'',NULL,NULL,'',NULL,'',NULL,NULL,'','','',NULL,'',NULL,NULL,'',NULL,'',NULL,'',NULL,'','',NULL,0);
/*!40000 ALTER TABLE `tdyw_interferences` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-09-13 16:18:26
