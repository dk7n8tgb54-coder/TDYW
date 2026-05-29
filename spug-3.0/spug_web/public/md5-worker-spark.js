/**
 * SparkMD5 Web Worker
 * 使用 spark-md5 库进行增量 MD5 计算
 * 避免阻塞主线程
 */

// 添加全局错误处理
self.onerror = function(error) {
    console.error('[MD5 Worker] Worker error:', error.message, error.filename, error.lineno);
    const errorMsg = error.message || '未知错误';
    self.postMessage({
        error: errorMsg,
        fileId: fileId || 'unknown'
    });
};

// 引入 spark-md5 库 (使用绝对路径，兼容开发和生产环境)
try {
    importScripts('/lib/spark-md5.min.js');
} catch (e) {
    console.error('[MD5 Worker] Failed to load spark-md5:', e);
    self.postMessage({ error: 'spark-md5 库加载失败' });
    throw e;
}

let spark = null;
let fileReceived = 0;
let fileSize = 0;
let fileId = null;

self.onmessage = function(e) {
    try {
        const { fileId: newFileId, fileChunk, isComplete, fileSize: newFileSize, fileName } = e.data;

        // 首次初始化 spark 实例
        if (!spark) {
            if (typeof SparkMD5 === 'undefined') {
                throw new Error('SparkMD5 未定义，库加载失败');
            }
            spark = new SparkMD5.ArrayBuffer();
        }

        if (newFileId) {
            fileId = newFileId;
        }

        if (newFileSize !== undefined) {
            fileSize = newFileSize;
        }

        // 验证 fileChunk 是否有效
        if (!fileChunk || fileChunk.byteLength === 0) {
            throw new Error(`无效的分片数据，byteLength: ${fileChunk ? fileChunk.byteLength : 'null'}`);
        }

        // 增量计算 MD5
        spark.append(new Uint8Array(fileChunk));
        fileReceived += fileChunk.byteLength;

        // 计算并返回进度
        const progress = Math.round((fileReceived / fileSize) * 100);
        self.postMessage({
            fileId,
            progress,
            isComplete: false
        });

        // 如果文件接收完成，返回最终 MD5
        if (isComplete) {
            const hash = spark.end();
            self.postMessage({
                fileId,
                hash,
                isComplete: true,
                progress: 100
            });
            // 重置 spark 实例以备下次使用
            spark.reset();
            fileReceived = 0;
        }
    } catch (error) {
        console.error('[MD5 Worker] Processing error:', error);
        self.postMessage({
            error: error.message || '处理错误',
            fileId: fileId || 'unknown'
        });
    }
};
