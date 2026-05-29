-- Document Management Module Database Initialization
-- Spug Document Folder and File Tables

USE spug;

CREATE TABLE IF NOT EXISTS `spug_document_folder` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(200) NOT NULL,
  `parent_id` int(11) DEFAULT NULL,
  `created_by_id` int(11) DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `spug_document_folder_parent_id_idx` (`parent_id`),
  KEY `spug_document_folder_created_by_id_idx` (`created_by_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `spug_document_file` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(200) NOT NULL,
  `folder_id` int(11) DEFAULT NULL,
  `file_path` varchar(500) NOT NULL,
  `file_size` bigint(20) NOT NULL DEFAULT '0',
  `file_type` varchar(50) NOT NULL,
  `created_by_id` int(11) DEFAULT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `spug_document_file_folder_id_idx` (`folder_id`),
  KEY `spug_document_file_created_by_id_idx` (`created_by_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
