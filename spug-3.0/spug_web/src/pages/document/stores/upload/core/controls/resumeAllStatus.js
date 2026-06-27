/**
 * 批量恢复时使用的后端状态查询 helper。
 * 独立出来是为了避免 Jest 直接导入带 decorators 的 DebounceController。
 */
export async function fetchBackendStatusMap({ transferStore, transferIds, isPublic = false }) {
  const ids = (transferIds || []).filter(Boolean);
  if (ids.length === 0 || !transferStore?.fetchTransfers) {
    return new Map();
  }

  try {
    const transfers = await transferStore.fetchTransfers(isPublic);
    const wantedIds = new Set(ids);
    return new Map(
      transfers
        .filter(transfer => wantedIds.has(transfer.id))
        .map(transfer => [transfer.id, transfer.status])
    );
  } catch (error) {
    console.warn('[resumeAllStatus] 获取后端传输状态失败，将按本地 waiting 调度', error);
    return new Map();
  }
}

export function shouldResumeBackendPaused(item, backendStatusMap) {
  return !!item?.transferId && backendStatusMap.get(item.transferId) === 'PAUSED';
}
