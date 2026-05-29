/**
 * 文件夹编辑状态管理 Hook
 * 【修复】从 useExplorerState 拆分出来的独立 Hook
 * 职责：处理行内新建文件夹和重命名功能
 */
import { useState, useCallback } from 'react';

export const useFolderEditing = () => {
  // ========== 行内新建文件夹状态 ==========
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [tempFolderName, setTempFolderName] = useState('');

  const startCreateFolder = useCallback(() => {
    setCreatingFolder(true);
    setTempFolderName('');
  }, []);

  const cancelCreateFolder = useCallback(() => {
    setCreatingFolder(false);
    setTempFolderName('');
  }, []);

  // ========== 行内重命名状态 ==========
  const [renamingRecord, setRenamingRecord] = useState(null);
  const [tempRenameValue, setTempRenameValue] = useState('');

  const startRename = useCallback((record) => {
    setRenamingRecord(record);
    setTempRenameValue(record.display_name || record.name || '');
  }, []);

  const cancelRename = useCallback(() => {
    setRenamingRecord(null);
    setTempRenameValue('');
  }, []);

  // 重置编辑状态（用于切换文件夹时）
  const resetEditingState = useCallback(() => {
    let hasChanges = false;
    
    if (creatingFolder) {
      setCreatingFolder(false);
      setTempFolderName('');
      hasChanges = true;
    }
    
    if (renamingRecord) {
      setRenamingRecord(null);
      setTempRenameValue('');
      hasChanges = true;
    }
    
    return hasChanges;
  }, [creatingFolder, renamingRecord]);

  return {
    // 新建文件夹状态
    creatingFolder,
    tempFolderName,
    setTempFolderName,
    startCreateFolder,
    cancelCreateFolder,
    // 重命名状态
    renamingRecord,
    tempRenameValue,
    setTempRenameValue,
    startRename,
    cancelRename,
    // 工具函数
    resetEditingState,
  };
};

export default useFolderEditing;
