# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""兼容外壳：Chromium 打印 worker 实现已上提至公共层 libs.html_pdf_worker
（2026-10-22，数字表单 PDF 成为第二个调用场景后按解耦规则上提）。

`python -m apps.equipment_lifecycle.excel_print_pdf_worker` 历史命令形态
保持可用，参数与行为与 libs.html_pdf_worker 完全一致。
"""
import sys

if __name__ == '__main__':
    from libs.html_pdf_worker import main

    main()
    sys.exit(0)
