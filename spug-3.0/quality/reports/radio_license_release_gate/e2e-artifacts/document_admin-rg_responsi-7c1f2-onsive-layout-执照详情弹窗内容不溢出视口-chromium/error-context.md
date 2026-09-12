# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: document_admin\rg_responsive_badge.spec.js >> Radio License release gate - responsive layout >> 执照详情弹窗内容不溢出视口
- Location: tests\document_admin\rg_responsive_badge.spec.js:48:3

# Error details

```
Error: expect(received).toBeLessThanOrEqual(expected)

Expected: <= 2
Received:    215
```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - generic [ref=e3]:
    - complementary:
      - generic:
        - img "Logo" [ref=e4]
        - generic:
          - menu:
            - menuitem "desktop 工作台":
              - img "desktop" [ref=e5] [cursor=pointer]
              - generic [ref=e8] [cursor=pointer]: 工作台
            - menuitem "bar-chart 数据分析":
              - img "bar-chart" [ref=e9] [cursor=pointer]
              - generic [ref=e12] [cursor=pointer]: 数据分析
            - menuitem "schedule 部门值班日志":
              - img "schedule" [ref=e13] [cursor=pointer]
              - generic [ref=e16] [cursor=pointer]: 部门值班日志
            - menuitem "safety-certificate 无线电执照管理" [expanded]:
              - img "safety-certificate" [ref=e17] [cursor=pointer]
              - generic [ref=e20] [cursor=pointer]: 无线电执照管理
            - menuitem "file-text 合同协议":
              - img "file-text" [ref=e21] [cursor=pointer]
              - generic [ref=e24] [cursor=pointer]: 合同协议
            - menuitem "team 协作任务":
              - img "team" [ref=e25] [cursor=pointer]
              - generic [ref=e28] [cursor=pointer]: 协作任务
            - menuitem "folder-open 资料库":
              - img "folder-open" [ref=e29] [cursor=pointer]
              - generic [ref=e32] [cursor=pointer]: 资料库
            - menuitem "file-text 跨日事项跟踪":
              - img "file-text" [ref=e33] [cursor=pointer]
              - generic [ref=e36] [cursor=pointer]: 跨日事项跟踪
            - menuitem "apartment 设备管理":
              - img "apartment" [ref=e37] [cursor=pointer]
              - generic [ref=e40] [cursor=pointer]: 设备管理
            - menuitem "field-time 设备生命周期":
              - img "field-time" [ref=e41] [cursor=pointer]
              - generic [ref=e45] [cursor=pointer]: 设备生命周期
            - menuitem "exception 干扰管理":
              - img "exception" [ref=e46] [cursor=pointer]
              - generic [ref=e49] [cursor=pointer]: 干扰管理
            - menuitem "clock-circle 值班日志":
              - img "clock-circle" [ref=e50] [cursor=pointer]
              - generic [ref=e54] [cursor=pointer]: 值班日志
            - menuitem "notification 公告与提醒":
              - img "notification" [ref=e55] [cursor=pointer]
              - generic [ref=e58] [cursor=pointer]: 公告与提醒
            - menuitem "tool 运维管理":
              - img "tool" [ref=e59] [cursor=pointer]
              - generic [ref=e62] [cursor=pointer]: 运维管理
            - menuitem "setting 系统管理":
              - img "setting" [ref=e63] [cursor=pointer]
              - generic [ref=e66] [cursor=pointer]: 系统管理
    - generic [ref=e67]:
      - generic [ref=e68]:
        - img "menu-unfold" [ref=e70] [cursor=pointer]
        - generic [ref=e73]:
          - generic [ref=e75] [cursor=pointer]:
            - img "bell" [ref=e76]
            - superscript [ref=e79]:
              - generic [ref=e80]: "2"
              - generic [ref=e81]: "2"
          - generic "管理员" [ref=e86] [cursor=pointer]
      - main [ref=e87]:
        - generic [ref=e88]:
          - navigation [ref=e90]:
            - list [ref=e91]:
              - listitem [ref=e92]: 首页/
              - listitem [ref=e93]: 无线电台执照
          - generic [ref=e96]:
            - generic [ref=e98]:
              - generic "台站" [ref=e100]
              - textbox "请输入台站名称" [ref=e105]
            - generic [ref=e108]:
              - generic "用途" [ref=e110]
              - textbox "请输入用途关键字" [ref=e115]
            - generic [ref=e118]:
              - generic "状态" [ref=e120]
              - generic [ref=e125] [cursor=pointer]:
                - combobox [ref=e127]
                - generic: 请选择状态
            - generic [ref=e129]:
              - generic "截止日期" [ref=e131]
              - generic [ref=e135]:
                - textbox "开始日期" [ref=e137]
                - generic "to" [ref=e139]:
                  - img "swap-right" [ref=e140]
                - textbox "结束日期" [ref=e144]
                - generic:
                  - img "calendar"
            - generic [ref=e149]:
              - button "查 询" [ref=e150] [cursor=pointer]
              - button "重 置" [ref=e152] [cursor=pointer]
          - generic [ref=e154]:
            - generic [ref=e155]:
              - generic [ref=e156]: 执照列表
              - generic [ref=e157]:
                - button "plus 新建" [ref=e160] [cursor=pointer]:
                  - img "plus" [ref=e161]
                  - generic [ref=e165]: 新建
                - separator [ref=e166]
                - generic [ref=e167]:
                  - img "reload" [ref=e169] [cursor=pointer]
                  - img "setting" [ref=e173] [cursor=pointer]
                  - img "fullscreen" [ref=e177] [cursor=pointer]
            - generic [ref=e182]:
              - table [ref=e186]:
                - rowgroup [ref=e199]:
                  - row [ref=e200]:
                    - columnheader "台站" [ref=e201]:
                      - text: 台站
                      - generic "拖动调整列宽，双击恢复默认宽度" [ref=e202]
                    - columnheader "频率" [ref=e203]:
                      - text: 频率
                      - generic "拖动调整列宽，双击恢复默认宽度" [ref=e204]
                    - columnheader "用途" [ref=e205]:
                      - text: 用途
                      - generic "拖动调整列宽，双击恢复默认宽度" [ref=e206]
                    - columnheader "起始日期" [ref=e207]:
                      - text: 起始日期
                      - generic "拖动调整列宽，双击恢复默认宽度" [ref=e208]
                    - columnheader "截止日期" [ref=e209]:
                      - text: 截止日期
                      - generic "拖动调整列宽，双击恢复默认宽度" [ref=e210]
                    - columnheader "剩余天数" [ref=e211]:
                      - text: 剩余天数
                      - generic "拖动调整列宽，双击恢复默认宽度" [ref=e212]
                    - columnheader "状态" [ref=e213]:
                      - text: 状态
                      - generic "拖动调整列宽，双击恢复默认宽度" [ref=e214]
                    - columnheader "责任人" [ref=e215]:
                      - text: 责任人
                      - generic "拖动调整列宽，双击恢复默认宽度" [ref=e216]
                    - columnheader "附件" [ref=e217]:
                      - text: 附件
                      - generic "拖动调整列宽，双击恢复默认宽度" [ref=e218]
                    - columnheader "创建时间" [ref=e219]:
                      - text: 创建时间
                      - generic "拖动调整列宽，双击恢复默认宽度" [ref=e220]
                    - columnheader "操作" [ref=e221]
                - rowgroup [ref=e222]:
                  - row [ref=e223] [cursor=pointer]:
                    - cell "对讲机中继台" [ref=e224]
                    - cell "-" [ref=e225]
                    - cell "对讲机中继" [ref=e226]
                    - cell "2026-06-18" [ref=e227]
                    - cell "2029-06-18" [ref=e228]
                    - cell "1010 天" [ref=e229]
                    - cell "正常" [ref=e231]
                    - cell "赵惠滨" [ref=e233]
                    - cell "paper-clip 1" [ref=e234]:
                      - generic [ref=e236]:
                        - img "paper-clip" [ref=e238]
                        - generic [ref=e241]: "1"
                    - cell "2026-08-16 17:11:50" [ref=e242]
                    - cell [ref=e243]:
                      - generic [ref=e244]:
                        - button "查看" [ref=e245]
                        - separator [ref=e247]
                        - button "编辑" [ref=e248]
                        - separator [ref=e250]
                        - button "删除" [ref=e251]
                  - row [ref=e253] [cursor=pointer]:
                    - cell "对讲机手台" [ref=e254]
                    - cell "-" [ref=e255]
                    - cell "对讲机" [ref=e256]
                    - cell "2026-06-18" [ref=e257]
                    - cell "2029-06-18" [ref=e258]
                    - cell "1010 天" [ref=e259]
                    - cell "正常" [ref=e261]
                    - cell "赵惠滨" [ref=e263]
                    - cell "paper-clip 2" [ref=e264]:
                      - generic [ref=e266]:
                        - img "paper-clip" [ref=e268]
                        - generic [ref=e271]: "2"
                    - cell "2026-08-16 17:09:31" [ref=e272]
                    - cell [ref=e273]:
                      - generic [ref=e274]:
                        - button "查看" [ref=e275]
                        - separator [ref=e277]
                        - button "编辑" [ref=e278]
                        - separator [ref=e280]
                        - button "删除" [ref=e281]
                  - row [ref=e283] [cursor=pointer]:
                    - cell "屯里导航台" [ref=e284]
                    - cell "247 kHz" [ref=e285]
                    - cell "导航" [ref=e286]
                    - cell "2024-07-11" [ref=e287]
                    - cell "2029-07-10" [ref=e288]
                    - cell "1032 天" [ref=e289]
                    - cell "正常" [ref=e291]
                    - cell "陈明清" [ref=e293]
                    - cell "paper-clip 1" [ref=e294]:
                      - generic [ref=e296]:
                        - img "paper-clip" [ref=e298]
                        - generic [ref=e301]: "1"
                    - cell "2026-08-16 17:02:38" [ref=e302]
                    - cell [ref=e303]:
                      - generic [ref=e304]:
                        - button "查看" [ref=e305]
                        - separator [ref=e307]
                        - button "编辑" [ref=e308]
                        - separator [ref=e310]
                        - button "删除" [ref=e311]
                  - row [ref=e313] [cursor=pointer]:
                    - cell "全向信标台" [ref=e314]
                    - cell "116.4 MHz" [ref=e315]
                    - cell "导航" [ref=e316]
                    - cell "2024-07-11" [ref=e317]
                    - cell "2029-07-10" [ref=e318]
                    - cell "1032 天" [ref=e319]
                    - cell "正常" [ref=e321]
                    - cell "陈明清" [ref=e323]
                    - cell "paper-clip 1" [ref=e324]:
                      - generic [ref=e326]:
                        - img "paper-clip" [ref=e328]
                        - generic [ref=e331]: "1"
                    - cell "2026-08-16 17:00:17" [ref=e332]
                    - cell [ref=e333]:
                      - generic [ref=e334]:
                        - button "查看" [ref=e335]
                        - separator [ref=e337]
                        - button "编辑" [ref=e338]
                        - separator [ref=e340]
                        - button "删除" [ref=e341]
                  - row [ref=e343] [cursor=pointer]:
                    - cell "23跑道仪表着陆系统航向台" [ref=e344]
                    - cell "108.5 MHz" [ref=e345]
                    - cell "导航" [ref=e346]
                    - cell "2024-07-11" [ref=e347]
                    - cell "2029-07-10" [ref=e348]
                    - cell "1032 天" [ref=e349]
                    - cell "正常" [ref=e351]
                    - cell "陈明清" [ref=e353]
                    - cell "paper-clip 1" [ref=e354]:
                      - generic [ref=e356]:
                        - img "paper-clip" [ref=e358]
                        - generic [ref=e361]: "1"
                    - cell "2026-08-16 16:59:24" [ref=e362]
                    - cell [ref=e363]:
                      - generic [ref=e364]:
                        - button "查看" [ref=e365]
                        - separator [ref=e367]
                        - button "编辑" [ref=e368]
                        - separator [ref=e370]
                        - button "删除" [ref=e371]
                  - row [ref=e373] [cursor=pointer]:
                    - cell "23跑下滑台" [ref=e374]
                    - cell "329.9 MHz" [ref=e375]
                    - cell "导航" [ref=e376]
                    - cell "2024-07-11" [ref=e377]
                    - cell "2029-07-10" [ref=e378]
                    - cell "1032 天" [ref=e379]
                    - cell "正常" [ref=e381]
                    - cell "陈明清" [ref=e383]
                    - cell "paper-clip 1" [ref=e384]:
                      - generic [ref=e386]:
                        - img "paper-clip" [ref=e388]
                        - generic [ref=e391]: "1"
                    - cell "2026-08-16 16:58:22" [ref=e392]
                    - cell [ref=e393]:
                      - generic [ref=e394]:
                        - button "查看" [ref=e395]
                        - separator [ref=e397]
                        - button "编辑" [ref=e398]
                        - separator [ref=e400]
                        - button "删除" [ref=e401]
                  - row [ref=e403] [cursor=pointer]:
                    - cell "23跑道测距台" [ref=e404]
                    - cell "108.5 MHz" [ref=e405]
                    - cell "导航" [ref=e406]
                    - cell "2024-07-11" [ref=e407]
                    - cell "2029-07-10" [ref=e408]
                    - cell "1032 天" [ref=e409]
                    - cell "正常" [ref=e411]
                    - cell "陈明清" [ref=e413]
                    - cell "paper-clip 1" [ref=e414]:
                      - generic [ref=e416]:
                        - img "paper-clip" [ref=e418]
                        - generic [ref=e421]: "1"
                    - cell "2026-08-16 16:56:01" [ref=e422]
                    - cell [ref=e423]:
                      - generic [ref=e424]:
                        - button "查看" [ref=e425]
                        - separator [ref=e427]
                        - button "编辑" [ref=e428]
                        - separator [ref=e430]
                        - button "删除" [ref=e431]
                  - row [ref=e433] [cursor=pointer]:
                    - cell "05跑道仪表着陆系统航向台" [ref=e434]
                    - cell "108.9 MHz" [ref=e435]
                    - cell "导航" [ref=e436]
                    - cell "2024-07-11" [ref=e437]
                    - cell "2029-07-10" [ref=e438]
                    - cell "1032 天" [ref=e439]
                    - cell "正常" [ref=e441]
                    - cell "陈明清" [ref=e443]
                    - cell "paper-clip 1" [ref=e444]:
                      - generic [ref=e446]:
                        - img "paper-clip" [ref=e448]
                        - generic [ref=e451]: "1"
                    - cell "2026-08-16 16:54:50" [ref=e452]
                    - cell [ref=e453]:
                      - generic [ref=e454]:
                        - button "查看" [ref=e455]
                        - separator [ref=e457]
                        - button "编辑" [ref=e458]
                        - separator [ref=e460]
                        - button "删除" [ref=e461]
                  - row [ref=e463] [cursor=pointer]:
                    - cell "05跑道下滑台" [ref=e464]
                    - cell "329.3 MHz" [ref=e465]
                    - cell "导航" [ref=e466]
                    - cell "2024-07-11" [ref=e467]
                    - cell "2029-07-10" [ref=e468]
                    - cell "1032 天" [ref=e469]
                    - cell "正常" [ref=e471]
                    - cell "陈明清" [ref=e473]
                    - cell "paper-clip 1" [ref=e474]:
                      - generic [ref=e476]:
                        - img "paper-clip" [ref=e478]
                        - generic [ref=e481]: "1"
                    - cell "2026-08-16 16:53:49" [ref=e482]
                    - cell [ref=e483]:
                      - generic [ref=e484]:
                        - button "查看" [ref=e485]
                        - separator [ref=e487]
                        - button "编辑" [ref=e488]
                        - separator [ref=e490]
                        - button "删除" [ref=e491]
                  - row [ref=e493] [cursor=pointer]:
                    - cell "05跑道测距台" [ref=e494]
                    - cell "987 MHz（发射/接收）" [ref=e495]
                    - cell "导航" [ref=e496]
                    - cell "2024-07-11" [ref=e497]
                    - cell "2029-07-10" [ref=e498]
                    - cell "1032 天" [ref=e499]
                    - cell "正常" [ref=e501]
                    - cell "陈明清" [ref=e503]
                    - cell "paper-clip 1" [ref=e504]:
                      - generic [ref=e506]:
                        - img "paper-clip" [ref=e508]
                        - generic [ref=e511]: "1"
                    - cell "2026-08-16 16:50:20" [ref=e512]
                    - cell [ref=e513]:
                      - generic [ref=e514]:
                        - button "查看" [ref=e515]
                        - separator [ref=e517]
                        - button "编辑" [ref=e518]
                        - separator [ref=e520]
                        - button "删除" [ref=e521]
                  - row [ref=e523] [cursor=pointer]:
                    - cell "站坪塔台5楼VHF机房" [ref=e524]
                    - cell "121.5 MHz 等 3 个" [ref=e525]
                    - cell "VHF地空通信" [ref=e526]
                    - cell "2024-05-14" [ref=e527]
                    - cell "2029-05-13" [ref=e528]
                    - cell "974 天" [ref=e529]
                    - cell "正常" [ref=e531]
                    - cell "林杰" [ref=e533]
                    - cell "paper-clip 3" [ref=e534]:
                      - generic [ref=e536]:
                        - img "paper-clip" [ref=e538]
                        - generic [ref=e541]: "3"
                    - cell "2026-08-16 16:44:04" [ref=e542]
                    - cell [ref=e543]:
                      - generic [ref=e544]:
                        - button "查看" [ref=e545]
                        - separator [ref=e547]
                        - button "编辑" [ref=e548]
                        - separator [ref=e550]
                        - button "删除" [ref=e551]
                  - row [ref=e553] [cursor=pointer]:
                    - cell "综合楼4楼VHF机房" [ref=e554]
                    - cell "118.1 MHz 等 8 个" [ref=e555]
                    - cell "VHF地空通信" [ref=e556]
                    - cell "2024-06-14" [ref=e557]
                    - cell "2029-06-13" [ref=e558]
                    - cell "1005 天" [ref=e559]
                    - cell "正常" [ref=e561]
                    - cell "林杰" [ref=e563]
                    - cell "paper-clip 2" [ref=e564]:
                      - generic [ref=e566]:
                        - img "paper-clip" [ref=e568]
                        - generic [ref=e571]: "2"
                    - cell "2026-08-16 09:12:56" [ref=e572]
                    - cell [ref=e573]:
                      - generic [ref=e574]:
                        - button "查看" [ref=e575]
                        - separator [ref=e577]
                        - button "编辑" [ref=e578]
                        - separator [ref=e580]
                        - button "删除" [ref=e581]
                  - row [ref=e583] [cursor=pointer]:
                    - cell "航管楼12楼机房" [ref=e584]
                    - cell "118.1 MHz 等 8 个" [ref=e585]
                    - cell "VHF地空通信" [ref=e586]
                    - cell "2024-06-14" [ref=e587]
                    - cell "2029-06-13" [ref=e588]
                    - cell "1005 天" [ref=e589]
                    - cell "正常" [ref=e591]
                    - cell "林杰" [ref=e593]
                    - cell "paper-clip 2" [ref=e594]:
                      - generic [ref=e596]:
                        - img "paper-clip" [ref=e598]
                        - generic [ref=e601]: "2"
                    - cell "2026-08-16 08:59:37" [ref=e602]
                    - cell [ref=e603]:
                      - generic [ref=e604]:
                        - button "查看" [ref=e605]
                        - separator [ref=e607]
                        - button "编辑" [ref=e608]
                        - separator [ref=e610]
                        - button "删除" [ref=e611]
              - list [ref=e613]:
                - listitem [ref=e614]: 共 13 条
                - listitem "上一页" [ref=e615]:
                  - button [disabled] [ref=e616]:
                    - img "left" [ref=e617]
                - listitem "1" [ref=e620] [cursor=pointer]
                - listitem "下一页" [ref=e622]:
                  - button [disabled] [ref=e623]:
                    - img "right" [ref=e624]
      - generic [ref=e627]: © 2026 ZSYT
  - list [ref=e631]:
    - menuitem "无线电台执照" [ref=e632] [cursor=pointer]
    - menuitem "台站频率批复" [ref=e634] [cursor=pointer]
  - generic [ref=e637]:
    - dialog "执照详情":
      - generic [ref=e638]:
        - button "Close" [ref=e639] [cursor=pointer]:
          - img "close" [ref=e641]
        - generic [ref=e644]: 执照详情
        - generic [ref=e646]:
          - table [ref=e649]:
            - rowgroup [ref=e650]:
              - row [ref=e651]:
                - rowheader "台站" [ref=e652]
                - cell "对讲机中继台" [ref=e653]
                - rowheader "状态" [ref=e654]
                - cell "正常" [ref=e655]
              - row [ref=e658]:
                - rowheader "起始日期" [ref=e659]
                - cell "2026-06-18" [ref=e660]
                - rowheader "截止日期" [ref=e661]
                - cell "2029-06-18" [ref=e662]
              - row [ref=e663]:
                - rowheader "剩余天数" [ref=e664]
                - cell "1010 天" [ref=e665]
                - rowheader "责任人" [ref=e668]
                - cell "赵惠滨" [ref=e669]
              - row [ref=e670]:
                - rowheader "用途" [ref=e671]
                - cell "对讲机中继" [ref=e672]
              - row [ref=e673]:
                - rowheader "备注" [ref=e674]
                - cell "-" [ref=e675]
          - separator [ref=e678]:
            - generic [ref=e679]: 附件
          - generic [ref=e680]:
            - generic [ref=e681]:
              - button [ref=e686]:
                - button "upload 上传附件" [ref=e687] [cursor=pointer]:
                  - img "upload" [ref=e688]
                  - generic [ref=e691]: 上传附件
              - generic [ref=e692]: 单文件最大 50MB
            - table [ref=e699]:
              - rowgroup [ref=e706]:
                - row [ref=e707]:
                  - columnheader "文件名" [ref=e708]
                  - columnheader "大小" [ref=e709]
                  - columnheader "上传人" [ref=e710]
                  - columnheader "上传时间" [ref=e711]
                  - columnheader "操作" [ref=e712]
              - rowgroup [ref=e713]:
                - row [ref=e714]:
                  - cell [ref=e715]:
                    - generic [ref=e716]:
                      - img "paper-clip" [ref=e718]
                      - button "49bcab61-5609-4a47-897b-6a4d9955ef8d.png" [ref=e722] [cursor=pointer]
                  - cell "119.2 KB" [ref=e724]
                  - cell "管理员" [ref=e725]
                  - cell "2026-09-03 09:22:09" [ref=e726]
                  - cell [ref=e727]:
                    - generic [ref=e728]:
                      - button "eye 预览" [ref=e730] [cursor=pointer]:
                        - img "eye" [ref=e731]
                        - generic [ref=e734]: 预览
                      - button "download 下载" [ref=e736] [cursor=pointer]:
                        - img "download" [ref=e737]
                        - generic [ref=e740]: 下载
                      - button "delete 删除" [ref=e742] [cursor=pointer]:
                        - img "delete" [ref=e743]
                        - generic [ref=e746]: 删除
          - table [ref=e749]:
            - rowgroup [ref=e750]:
              - row [ref=e751]:
                - rowheader "创建人" [ref=e752]
                - cell "-" [ref=e753]
                - rowheader "创建时间" [ref=e754]
                - cell "2026-08-16 17:11:50" [ref=e755]
              - row [ref=e756]:
                - rowheader "更新人" [ref=e757]
                - cell "-" [ref=e758]
                - rowheader "更新时间" [ref=e759]
                - cell "2026-08-24 15:29:12" [ref=e760]
        - generic [ref=e761]:
          - button "关 闭" [ref=e762] [cursor=pointer]
          - button "编 辑" [ref=e764] [cursor=pointer]
```

# Test source

```ts
  1  | /**
  2  |  * 无线电执照上线门禁 E2E 补充：响应式布局 + 工作台徽标跳转（真实浏览器）。
  3  |  *
  4  |  * 覆盖：
  5  |  * - 桌面端（1440x900）与窄屏（375x667）下执照/批复页面表格渲染、无横向溢出
  6  |  * - 弹窗打开后内容不溢出视口
  7  |  * - 工作台到期提醒卡片跳转到正确页面
  8  |  */
  9  | const { test, expect, apiLogin, injectAuth, uiLogin } = require('../../fixtures/auth.fixture');
  10 | 
  11 | 
  12 | async function login(page, request) {
  13 |   const session = await apiLogin(request, 'admin');
  14 |   await injectAuth(page, session);
  15 | }
  16 | 
  17 | 
  18 | test.describe('Radio License release gate - responsive layout', () => {
  19 |   for (const viewport of [
  20 |     {name: 'desktop', width: 1440, height: 900},
  21 |     {name: 'narrow', width: 375, height: 667},
  22 |   ]) {
  23 |     test(`执照列表在${viewport.name}视口渲染且无横向溢出`, async ({page, request}) => {
  24 |       await login(page, request);
  25 |       await page.setViewportSize({width: viewport.width, height: viewport.height});
  26 |       await page.goto('/radio-license');
  27 |       await page.waitForSelector('.ant-table', {timeout: 15000});
  28 |       // 表格渲染出表头
  29 |       await expect(page.locator('.ant-table-thead')).toBeVisible();
  30 |       // 页面无不可控横向溢出（jsdom 无法验证，真实浏览器检查 body 滚动宽度）
  31 |       const overflow = await page.evaluate(
  32 |         () => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  33 |       expect(overflow).toBeLessThanOrEqual(2);
  34 |     });
  35 | 
  36 |     test(`批复列表在${viewport.name}视口渲染且无横向溢出`, async ({page, request}) => {
  37 |       await login(page, request);
  38 |       await page.setViewportSize({width: viewport.width, height: viewport.height});
  39 |       await page.goto('/station-frequency-approval');
  40 |       await page.waitForSelector('.ant-table', {timeout: 15000});
  41 |       await expect(page.locator('.ant-table-thead')).toBeVisible();
  42 |       const overflow = await page.evaluate(
  43 |         () => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  44 |       expect(overflow).toBeLessThanOrEqual(2);
  45 |     });
  46 |   }
  47 | 
  48 |   test('执照详情弹窗内容不溢出视口', async ({page, request}) => {
  49 |     await login(page, request);
  50 |     await page.setViewportSize({width: 375, height: 667});
  51 |     await page.goto('/radio-license');
  52 |     // 排除 rc-table 测量行，只等真实数据行
  53 |     await page.waitForSelector('tr.ant-table-row', {timeout: 15000});
  54 |     await page.locator('tr.ant-table-row').first().dblclick();
  55 |     await page.waitForSelector('.ant-modal', {timeout: 10000});
  56 |     await expect(page.locator('.ant-modal')).toBeVisible();
  57 |     const overflow = await page.evaluate(() => {
  58 |       const modal = document.querySelector('.ant-modal');
  59 |       return modal ? modal.scrollWidth - modal.clientWidth : 0;
  60 |     });
> 61 |     expect(overflow).toBeLessThanOrEqual(2);
     |                      ^ Error: expect(received).toBeLessThanOrEqual(expected)
  62 |   });
  63 | });
  64 | 
  65 | 
  66 | test.describe('Radio License release gate - workbench badge navigation', () => {
  67 |   test('工作台到期提醒卡片可跳转执照页面', async ({page}) => {
  68 |     // 用 UI 登录（最真实路径，规避 apiLogin+injectAuth 的间歇性失败）
  69 |     await uiLogin(page, 'admin');
  70 |     await page.setViewportSize({width: 1440, height: 900});
  71 |     // 登录后已在工作台：到期提醒卡片存在（admin 有执照查看权限）
  72 |     const card = page.locator('.ant-card').filter({hasText: '到期提醒'});
  73 |     await expect(card.first()).toBeVisible({timeout: 20000});
  74 |     // 点击执照行 → /radio-license
  75 |     await card.locator('span').filter({hasText: '无线电台执照'}).first().click();
  76 |     await page.waitForURL('**/radio-license**', {timeout: 10000});
  77 |     await expect(page.locator('.ant-table')).toBeVisible();
  78 |   });
  79 | });
  80 | 
```