/**
 * ChunkUploadCoordinator - 分片上传协调器（占位）
 *
 * 【P1修复】原 resumeChunkedUpload 实现的"startChunkIndex = item.currentChunk"是
 * 旧的 Math.max+1 模式：如果后端 uploaded_chunks 不连续（[0,2,3]），会跳过中间缺口
 * 导致分片永久丢失。统一改走 ChunkUploadStore.uploadFileChunked() 的
 * "遍历所有分片 + 跳过 uploadedChunks.has(chunkIndex)"补缺模型。
 *
 * 本类不再持有断点续传方法。如未来需要在此处扩展协调逻辑，请重新基于补缺模型设计。
 */
export class ChunkUploadCoordinator {
  constructor(coreStore) {
    this.core = coreStore;
  }
}

export default ChunkUploadCoordinator;
