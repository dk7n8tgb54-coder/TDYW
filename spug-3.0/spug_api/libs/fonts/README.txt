中文字体文件目录
==================

用途：
-----
此目录用于存放PDF导出功能所需的中文字体文件，避免依赖宿主机系统字体。

说明：
-----
1. 推荐使用 simhei.ttf（黑体）字体文件，因为：
   - 兼容性好，Windows/Linux系统均可用
   - 字体文件体积较小（约10MB）
   - 支持GB2312基本汉字集

2. 将字体文件放置在此目录下，系统会自动优先加载：
   - simhei.ttf  (首选)
   - simhei.otf  (备选)

3. 如果此目录下没有字体文件，系统会回退到以下系统路径：
   - Windows: C:\Windows\Fonts\simhei.ttf
   - Linux: /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc

如何获取字体文件：
-----------------
方案1：从Windows系统复制
  Windows系统的 C:\Windows\Fonts\simhei.ttf 文件可直接复制到此目录

方案2：从Linux系统安装
  apt-get install fonts-wqy-zenhei
  cp /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc ./fonts/simhei.otf

方案3：下载开源字体
  - https://github.com/StellarCN/scp_zh/tree/master/fonts
  - 选择 NotoSansCJK-Regular.otf 并重命名为 simhei.otf

注意事项：
---------
- 请确保字体文件的版权符合项目使用许可
- 仅放置支持中文的TrueType或OpenType字体文件
- 放置字体后重启Spug容器生效
