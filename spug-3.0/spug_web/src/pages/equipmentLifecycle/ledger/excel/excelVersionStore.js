/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 历史版本查看/复制状态（2026-10-21，独立小 Store，不并入
 * excelTemplateStore 以免其继续膨胀）。
 *
 * 职责边界：
 * - open() 拉取版本内容快照（布局/绑定/打印参数/分页计划），历史版本
 *   只读：本 Store 不提供任何修改版本内容的方法；
 * - 失败时 error 记录真实错误文案并保持 version 为空——页面显示错误态
 *   与重试，绝不显示"空白成功"；
 * - 预览走版本自身的 preview/pdf 接口，blob URL 只在关闭/重开时释放；
 * - copyToDraft() 只调用后端复制接口并返回更新后的模板详情：当前草稿
 *   替换为目标版本快照，历史版本不变、不自动发布；成功后由页面
 *   applyDetail 刷新草稿视图，失败原样抛出（不提示成功）。
 */
import {observable, action} from 'mobx';

import {parsePdfMetaHeaders} from './excelTemplateStore';
import {
  copyVersionToDraft, fetchVersionContent, fetchVersionPreview,
} from './excelVersionView';

export class ExcelVersionStore {
  @observable visible = false;
  @observable templateId = null;
  @observable templateName = '';
  @observable templateIsActive = true;
  @observable versionNo = null;      // 当前查看的版本号（读取失败仍保留，供重试）
  @observable version = null;        // 版本内容快照（只读）
  @observable loading = false;
  @observable error = '';            // 版本内容读取失败（真实错误文案）
  @observable previewUrl = '';       // 版本打印预览 blob URL（iframe 展示）
  @observable previewMeta = null;    // {pages, paper, warnings}
  @observable previewLoading = false;
  @observable previewError = '';
  @observable copying = false;

  /** 打开某模板的某版本（只读）：先清空旧状态再拉取内容快照。 */
  @action async open(templateId, templateName, versionNo, isActive = true) {
    this._revokePreview();
    this.visible = true;
    this.templateId = templateId;
    this.templateName = templateName || '';
    this.templateIsActive = !!isActive;
    this.versionNo = versionNo;
    this.version = null;
    this.error = '';
    this.previewMeta = null;
    this.previewError = '';
    this.loading = true;
    try {
      this.version = await fetchVersionContent(templateId, versionNo);
      return this.version;
    } catch (e) {
      // 公共拦截器已提示业务错误；这里保留真实文案供页面展示与重试
      this.error = typeof e === 'string' ? e : '版本内容读取失败';
      throw e;
    } finally {
      this.loading = false;
    }
  }

  /** 关闭查看抽屉（释放预览 blob URL，不触碰当前草稿）。 */
  @action close() {
    this._revokePreview();
    this.visible = false;
    this.versionNo = null;
    this.version = null;
    this.error = '';
    this.previewMeta = null;
    this.previewError = '';
  }

  _revokePreview() {
    if (this.previewUrl) {
      try {
        window.URL.revokeObjectURL(this.previewUrl);
      } catch (e) {
        // URL 已释放时忽略
      }
    }
    this.previewUrl = '';
  }

  /**
   * 版本自身打印预览：用版本快照的源文件/布局/绑定/参数生成（后端保证），
   * 与当前草稿无关；失败记录错误态可重试，不返回陈旧预览冒充成功。
   */
  @action async loadPreview() {
    if (!this.templateId || !this.version || this.previewLoading) return '';
    this.previewLoading = true;
    this.previewError = '';
    try {
      const response = await fetchVersionPreview(
        this.templateId, this.versionNo);
      const bytes = response && response.data;
      if (!bytes || !bytes.byteLength) throw new Error('预览内容为空');
      const url = window.URL.createObjectURL(
        new Blob([bytes], {type: 'application/pdf'}));
      this._revokePreview();
      this.previewUrl = url;
      this.previewMeta = parsePdfMetaHeaders(response);
      return url;
    } catch (e) {
      this.previewError = '版本打印预览生成失败，可点击「刷新预览」重试';
      throw e;
    } finally {
      this.previewLoading = false;
    }
  }

  /**
   * 复制版本为新草稿（防重复提交）：返回更新后的模板详情。
   * 失败不修改任何本地状态，由调用方保留页面与当前草稿。
   */
  @action async copyToDraft() {
    if (!this.templateId || !this.version || this.copying) return null;
    this.copying = true;
    try {
      return await copyVersionToDraft(
        this.templateId, this.version.version_no);
    } finally {
      this.copying = false;
    }
  }
}

export default new ExcelVersionStore();
