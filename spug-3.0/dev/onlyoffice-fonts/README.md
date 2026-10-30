# onlyoffice-fonts — 容器中文字体补充（ONLYOFFICE 与后端转换共用）

此目录**同时**挂载进两个容器（只读）：
- `tdyw-onlyoffice-test`（ONLYOFFICE Docs 在线编辑）→ `/usr/share/fonts/custom`
- `tdyw-test`（后端，LibreOffice `.doc→.docx` 转换）→ `/usr/share/fonts/custom`

用于补齐容器相对 WPS/Word 缺失的常用字体。**字体文件不入 Git**
（微软/方正授权字体，仅限本机已授权 Windows 拷贝到内网开发容器）。

## 现有文件（2026-10-29 从本机 C:\Windows\Fonts 拷贝）

| 文件 | 字体 |
|---|---|
| simkai.ttf | 楷体 KaiTi |
| msyh.ttc / msyhbd.ttc / msyhl.ttc | 微软雅黑 Regular/Bold/Light |
| Deng.ttf / Dengb.ttf / Dengl.ttf | 等线 Regular/Bold/Light |
| STKAITI.TTF | 华文楷体 STKaiti |
| times.ttf / timesbd.ttf | Times New Roman Regular/Bold |
| arial.ttf / arialbd.ttf | Arial Regular/Bold |
| simsun.ttc | 宋体/新宋体 SimSun/NSimSun |
| simfang.ttf | 仿宋 FangSong |
| simhei.ttf | 黑体 SimHei |
| SIMYOU.TTF | 幼圆 YouYuan |
| SIMLI.TTF | 隶书 LiSu |

**注意：原版 `onlyoffice/documentserver:8.1` 镜像不带任何中文字体**（只有
dejavu/liberation/msttcorefonts 西文字体）。此前容器里的宋体等 5 个字体是手工塞入的，
容器重建即丢失，表现为"编辑视图字体与 WPS 不一致"复发——所以全部中文字体必须走本目录
持久化挂载。

## 新增/更换字体的步骤

1. 从本机 `C:\Windows\Fonts` 拷贝 ttf/ttc 到本目录（文件名保持原名即可）。
2. **onlyoffice 容器**：重建字体索引并重启文档服务：

   ```
   docker exec tdyw-onlyoffice-test documentserver-generate-allfonts.sh
   ```

   （脚本结尾自动重启 ds:docservice/ds:converter，无需手动 supervisorctl）
   后端 tdyw 容器无需额外操作（LibreOffice 每次转换进程启动时重新扫描字体）。
3. 浏览器重新打开手册编辑页（编辑器启动时才加载 AllFonts.js）。

## 验证

```
docker exec tdyw-onlyoffice-test fc-list :lang=zh
```

已知边界：文档使用了本目录与镜像自带字体之外的字体（如 仿宋_GB2312、
楷体_GB2312、方正小标宋）时，DS 仍会替换显示；需要时把对应字体文件补进来
再执行步骤 2。
