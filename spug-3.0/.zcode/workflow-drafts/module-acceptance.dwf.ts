/* zcode-workflow
description: 模块验收：对 spug_api/apps/<app> 下的一个 Django 模块做多镜头静态审计（租户隔离/权限端点/API 契约/前端一致性）与确定性门禁（Django 检查、迁移一致性、行尾、测试套件、代码质量门禁），中高严重度发现逐条独立复核，最后由独立审读汇总为验收报告。
args:
  app:
    type: string
    required: true
    description: Django app 名（apps/ 下的目录名，如 institution）
  webDir:
    type: string
    required: false
    default: ""
    description: 前端页面目录名（spug_web/src/pages/ 下的目录名）；留空则自动探测
*/

interface RawFinding {
  /** 工作区相对路径，尽量带行号："spug_api/apps/x/views.py:42"。 */
  where: string;
  /** 一句话：问题是什么，不是怎么修。 */
  what: string;
  /** 证据：读到的代码行或命令输出摘录。 */
  evidence: string;
  /** 严重度。high 留给越权、跨租户泄露、数据丢失或崩溃。 */
  severity: "low" | "medium" | "high";
}

interface LensResult {
  /** 这个镜头的一句话总评；没有问题时也写。 */
  summary: string;
  /** 发现的问题列表；没有问题就给空数组。 */
  findings: RawFinding[];
}

interface Confirmation {
  /** 亲自核对代码后：true=属实；false=证据不成立或误读。 */
  confirmed: boolean;
  /** 复核结论一句话。 */
  note: string;
}

interface GateOutcome {
  /** 检查项名，如 "模块测试套件"。 */
  name: string;
  /** 检查状态。 */
  status: "进行中" | "通过" | "未通过" | "被阻断";
  /** 一句话结论，含关键数字或退出码。 */
  detail: string;
}

interface Verdict {
  /** 验收结论一句话：通过/不通过，点出最关键原因。 */
  verdict: string;
  /** 2-3 句支撑要点。 */
  rationale: string;
  /** 审读发现的自相矛盾或关键信息缺失；没有就给空数组。 */
  inconsistencies: string[];
}

interface Finding extends RawFinding {
  /** verified=独立复核或确定性命令坐实；unconfirmed=复核未坐实或未复核。 */
  status: "verified" | "unconfirmed";
}

interface WorkflowReport {
  /** 验收结论，两三句话回答"这个模块能不能验收"。 */
  conclusion: string;
  findings: Finding[];
  /** 本次实际检查了什么、怎么检查的。 */
  verified: string[];
  /** 没查什么、为什么查不了。 */
  notCovered: string[];
}

// ---- 参数与栈常量 ----
const app = String(args.app ?? "").trim();
if (!/^[a-z][a-z0-9_]*$/.test(app)) {
  throw new Error("参数 app 必须是 Django app 名（字母开头的小写标识符，如 institution），收到：" + String(args.app));
}
const webDir = String(args.webDir ?? "").trim();
const CONTAINER = "tdyw-test"; // 后端测试容器（bind mount 当前工作区，改动实时可见）
const API_DIR = "/data/spug/spug_api"; // 容器内代码路径

artifact.table("checks", {
  title: "验收检查项",
  key: "name",
  columns: [
    { field: "name", label: "检查项" },
    { field: "status", label: "状态" },
    { field: "detail", label: "结论" },
  ],
});

// ---- 确定性盘点：文件清单与能力开关 ----
const appGlob = "spug_api/apps/" + app;
const pyFiles = await files.glob(appGlob + "/**/*.py");
if (pyFiles.length === 0) {
  throw new Error("在 " + appGlob + " 下没有找到任何 Python 文件——请确认 app 名是否正确。");
}
const testFiles = pyFiles.filter((p) => p.includes("/tests/"));
const viewFiles = pyFiles.filter((p) => /\/views[^/]*\.py$/.test(p) || p.endsWith("/urls.py") || p.endsWith("/serializers.py"));
const modelFiles = pyFiles.filter((p) => /\/(models|services|storage)\.py$/.test(p) || p.includes("/migrations/"));
const hasAttachments = (await files.grep("EvidenceAttachment", appGlob + "/**")).length > 0;
const hasCelery = (await files.grep("shared_task|@app\\.task", appGlob + "/**")).length > 0;
let feDir = "";
if (webDir) {
  feDir = webDir;
} else {
  const fePages = await files.glob("spug_web/src/pages/" + app + "/**/*.js*");
  if (fePages.length > 0 || (await files.grep(app, "spug_web/src/routes.js")).length > 0) {
    feDir = app;
  }
}
const hasFrontend = feDir !== "";
const crlfBackend = await files.grep("\\r$", appGlob + "/**");
const crlfFrontend = hasFrontend ? await files.grep("\\r$", "spug_web/src/pages/" + feDir + "/**") : [];
log("盘点完成：apps/" + app + " 共 " + pyFiles.length + " 个 py 文件，测试文件 " + testFiles.length + " 个，附件=" + hasAttachments + "，Celery=" + hasCelery + "，前端=" + hasFrontend + "，CRLF 命中 " + (crlfBackend.length + crlfFrontend.length) + " 行");

// ---- 审计镜头 ----
const lenses: { name: string; scope: string; focus: string }[] = [
  {
    name: "租户隔离",
    scope: modelFiles.join("\n") || appGlob,
    focus:
      "模型是否继承 TenantModelMixin 并使用 TenantModelManager；有没有绕过租户过滤的查询（裸 objects.all()、原生 SQL、update 不带租户条件）；" +
      "GLOBAL / apply_tenant_filter 用法是否正确；接口响应是否会泄露其他租户的数据。",
  },
  {
    name: "权限与端点",
    scope: viewFiles.join("\n") || appGlob,
    focus:
      "每个端点是否都有后端权限校验（@auth / has_perm，权限码格式 <app>.<model>.<action>）；有没有只靠前端隐藏按钮、后端裸奔的端点；" +
      (hasAttachments
        ? "本模块使用了 EvidenceAttachment：附件下载/删除/预览端点必须先做归属校验（附件存在且未软删、module/object_type 与本模块常量匹配、附件在当前用户租户范围内）。"
        : "本模块未使用 EvidenceAttachment；若发现直接的文件读写端点，请单独评估权限与路径穿越防护。"),
  },
  {
    name: "API契约与数据模型",
    scope: pyFiles.join("\n"),
    focus:
      "业务错误是否用 json_response(error=...)（HTTP 200 + error 约定）；参数校验是否在 View 层；" +
      "DateTimeField 查询是否用了被禁用的 __date/__year/__month/__startswith/__icontains（应改 __gte/__lt）；" +
      "CharField/TextField 是否有 null=True（禁止）；分页是否用 libs/pagination；迁移是否一功能一迁移。",
  },
];
if (hasFrontend) {
  lenses.push({
    name: "前端一致性",
    scope: "spug_web/src/pages/" + feDir + " 与 spug_web/src/routes.js",
    focus: "routes.js 的 auth 权限码必须与后端权限码一致；前端 API 路径与后端 urls.py 一致；HTTP 200 + error 不得当成功处理。",
  });
}
log("审计镜头 " + lenses.length + " 个：" + lenses.map((l) => l.name).join("、"));

// ---- 阶段：静态审计（逐镜头并行，中高发现逐条独立复核） ----
const auditF = future(async () => {
  phase("按镜头并行审计代码");
  return Promise.all(
    lenses.map(async (lens) => {
      report({ name: "审计·" + lens.name, status: "进行中", detail: "静态审计进行中" }, "checks");
      const res = await agent("审计·" + lens.name).ask<LensResult>(
        "你在验收 Django 模块 apps/" + app + "，负责「" + lens.name + "」这一个镜头的静态审计。\n" +
        "审计范围（按需读文件，不要读范围外的）：\n" + lens.scope + "\n" +
        "检查要点：" + lens.focus + "\n" +
        "项目规则见工作区根目录 AGENTS.md 与 spug_api/AGENTS.md，先读相关章节再下结论。\n" +
        "只挑毛病、给证据，不评审优点；where 尽量带行号；拿不准的宁可不报。\n" +
        "测试代码只作佐证：抽查与疑点直接相关的用例即可，不要逐行通读；结论保持精炼，把篇幅花在证据上。\n" +
        "不要修改任何文件。若发现越权、跨租户泄露或会崩溃的问题，severity 给 high。你的发现随后会被独立复核，请确保 evidence 能让没读过代码的人定位。",
      );
      const withStatus: Finding[] = await Promise.all(
        res.findings.map(async (f, i) => {
          if (f.severity === "low" || i >= 10) {
            return { ...f, status: "unconfirmed" as const };
          }
          const c = await agent("复核·" + lens.name + "-" + (i + 1)).ask<Confirmation>(
            "独立复核下面这条审计发现：亲自读 where 指向的代码与相关规则，判断 what 是否属实、证据是否成立。\n" +
            JSON.stringify(f) + "\n" +
            "不修改任何文件。属实给 confirmed=true，否则 false；note 用一句话写依据。",
          );
          return { ...f, status: c.confirmed ? ("verified" as const) : ("unconfirmed" as const) };
        }),
      );
      const verifiedCount = withStatus.filter((f) => f.status === "verified").length;
      const badCount = withStatus.filter((f) => f.status === "verified" && f.severity !== "low").length;
      report(
        {
          name: "审计·" + lens.name,
          status: withStatus.length === 0 ? "通过" : badCount > 0 ? "未通过" : "通过",
          detail: res.summary + "（发现 " + withStatus.length + " 条，坐实 " + verifiedCount + " 条" +
            (res.findings.length > withStatus.length ? "，超出部分未复核" : "") + "）",
        },
        "checks",
      );
      for (const f of withStatus) {
        report({ where: f.where, what: f.what, evidence: f.evidence, severity: f.severity, status: f.status });
      }
      return { lensName: lens.name, summary: res.summary, findings: withStatus };
    }),
  );
});

// ---- 阶段：静态门禁（Django 检查 / 迁移一致性 / git 空白） ----
const gateStaticF = future(async () => {
  phase("跑 Django 检查与迁移一致性门禁");
  const outcomes: GateOutcome[] = [];
  const findings: Finding[] = [];
  const check = await world.run(
    "wsl",
    ["bash", "-c", "docker exec -e PYTHONIOENCODING=utf-8 -w " + API_DIR + " " + CONTAINER + " python manage.py check"],
    { timeoutMs: 180000 },
  );
  outcomes.push({
    name: "Django system check",
    status: check.exitCode === 0 ? "通过" : "未通过",
    detail: check.exitCode === 0 ? "python manage.py check 通过" : "退出码 " + check.exitCode + "：" + (check.stderr || check.stdout).slice(-400),
  });
  const mig = await world.run(
    "wsl",
    ["bash", "-c", "docker exec -e PYTHONIOENCODING=utf-8 -w " + API_DIR + " " + CONTAINER + " python manage.py makemigrations --check --dry-run apps." + app],
    { timeoutMs: 180000 },
  );
  if (mig.exitCode === 0) {
    outcomes.push({ name: "迁移一致性", status: "通过", detail: "模型与迁移一致（makemigrations --check 干净）" });
  } else if (/changes that are not yet reflected/i.test(mig.stdout)) {
    outcomes.push({ name: "迁移一致性", status: "未通过", detail: "存在未生成的迁移：" + (mig.stdout || mig.stderr).slice(-400) });
  } else {
    outcomes.push({
      name: "迁移一致性",
      status: "被阻断",
      detail: "退出码 " + mig.exitCode + "，无法判定模型/迁移一致性。stderr 尾部：" + (mig.stderr || "").slice(-300) + "；stdout 尾部：" + (mig.stdout || "").slice(-200),
    });
  }
  const ws = await world.run("git", ["diff", "--check"], { timeoutMs: 60000 });
  outcomes.push({
    name: "git diff --check",
    status: ws.exitCode === 0 ? "通过" : "未通过",
    detail: ws.exitCode === 0 ? "无空白/行尾错误（仅覆盖已跟踪文件的改动）" : "发现空白错误：" + (ws.stdout || "").slice(0, 400),
  });
  if (crlfBackend.length + crlfFrontend.length > 0) {
    const sample = (crlfBackend.length > 0 ? crlfBackend : crlfFrontend)[0];
    outcomes.push({
      name: "行尾检查（LF）",
      status: "未通过",
      detail: "模块内 " + (crlfBackend.length + crlfFrontend.length) + " 行是 CRLF，首例 " + sample.path + ":" + sample.line + "（项目要求全部 LF）",
    });
    findings.push({
      where: sample.path + ":" + sample.line,
      what: "模块内有 CRLF 行尾（共 " + (crlfBackend.length + crlfFrontend.length) + " 行），项目要求统一 LF",
      evidence: "files.grep(\"\\\\r$\") 命中 " + (crlfBackend.length + crlfFrontend.length) + " 行",
      severity: "low",
      status: "verified",
    });
  } else {
    outcomes.push({ name: "行尾检查（LF）", status: "通过", detail: "模块内未发现 CRLF 行尾" });
  }
  for (const o of outcomes) report(o, "checks");
  return { outcomes, findings };
});

// ---- 阶段：模块测试套件 ----
const gateTestsF = future(async () => {
  phase("跑模块测试套件");
  report({ name: "模块测试套件", status: "进行中", detail: "manage.py test apps." + app }, "checks");
  const run = await world.run(
    "wsl",
    ["bash", "-c", "docker exec -e PYTHONIOENCODING=utf-8 -w " + API_DIR + " " + CONTAINER + " python manage.py test apps." + app + " --noinput"],
    { timeoutMs: 1200000 },
  );
  // Django 测试进度与结果打印在 stderr，必须合并两个流后再解析
  const out = run.stdout + "\n" + run.stderr;
  const ran = /Ran (\d+) tests?/.exec(out);
  const count = ran ? Number(ran[1]) : -1;
  const verdictLine = /(FAILED \([^)]*\)|\bOK\b)/.exec(out);
  const outcomes: GateOutcome[] = [];
  const findings: Finding[] = [];
  if (count < 0) {
    outcomes.push({
      name: "模块测试套件",
      status: "被阻断",
      detail: "无法从输出解析测试结果（退出码 " + run.exitCode + "）：" + out.slice(-600),
    });
  } else if (count === 0) {
    outcomes.push({
      name: "模块测试套件",
      status: "未通过",
      detail: "apps." + app + " 下没有发现任何测试——项目要求行为测试，禁止以读源码代替（AGENTS.md 第七节）",
    });
    findings.push({
      where: appGlob,
      what: "模块没有任何行为测试",
      evidence: "docker exec " + CONTAINER + " python manage.py test apps." + app + " --noinput 输出 Ran 0 tests",
      severity: "medium",
      status: "verified",
    });
  } else if (run.exitCode === 0) {
    outcomes.push({ name: "模块测试套件", status: "通过", detail: "Ran " + count + " tests，全部通过" });
  } else {
    outcomes.push({
      name: "模块测试套件",
      status: "未通过",
      detail: "Ran " + count + " tests，" + (verdictLine ? verdictLine[1] : "退出码 " + run.exitCode) + "；输出尾部：" + out.slice(-500),
    });
  }
  for (const o of outcomes) report(o, "checks");
  return { outcomes, findings };
});

// ---- 阶段：代码质量门禁 ----
const gateQualityF = future(async () => {
  phase("跑代码质量门禁");
  const run = await world.run("python", ["scripts/code_quality_check.py", "--format", "json"], { timeoutMs: 900000 });
  const start = run.stdout.indexOf("{");
  const end = run.stdout.lastIndexOf("}");
  let parsed: { passed: boolean; errors: Array<{ file: string; line?: number; message: string }>; warnings: Array<{ file: string; line?: number; message: string }> } | null = null;
  if (start >= 0 && end > start) {
    try {
      parsed = JSON.parse(run.stdout.slice(start, end + 1));
    } catch {
      parsed = null;
    }
  }
  const outcomes: GateOutcome[] = [];
  const findings: Finding[] = [];
  if (!parsed) {
    outcomes.push({
      name: "代码质量门禁",
      status: "被阻断",
      detail: "无法解析门禁 JSON 输出（退出码 " + run.exitCode + "）：" + (run.stderr || run.stdout).slice(-300),
    });
  } else {
    outcomes.push({
      name: "代码质量门禁",
      status: parsed.passed ? "通过" : "未通过",
      detail:
        (parsed.passed ? "通过" : "存在 " + parsed.errors.length + " 个错误") +
        "；警告 " + parsed.warnings.length + " 个（新增超标即失败，历史超标以基线治理）" +
        (parsed.warnings.length > 0 && parsed.warnings.length <= 5
          ? "：" + parsed.warnings.map((w) => w.file.replace(/\\/g, "/") + " " + w.message).join("；")
          : ""),
    });
    for (const e of parsed.errors) {
      findings.push({
        where: e.file.replace(/\\/g, "/") + (e.line ? ":" + e.line : ""),
        what: "代码质量门禁错误：" + e.message,
        evidence: "scripts/code_quality_check.py --format json 输出 errors 列表",
        severity: "medium",
        status: "verified",
      });
    }
  }
  for (const o of outcomes) report(o, "checks");
  return { outcomes, findings };
});

// 汇总需要全部镜头与全部门禁的结果（最终报告要同时引用两边，这里是必要的 barrier）
const [auditResults, staticGate, testGate, qualityGate] = await Promise.all([auditF, gateStaticF, gateTestsF, gateQualityF]);

const gateOutcomes: GateOutcome[] = [...staticGate.outcomes, ...testGate.outcomes, ...qualityGate.outcomes];
const gateFindings: Finding[] = [...staticGate.findings, ...testGate.findings, ...qualityGate.findings];
const lensFindings: Finding[] = auditResults.flatMap((r) => r.findings);
const findings: Finding[] = [...gateFindings, ...lensFindings];

const blockingGates = gateOutcomes.filter((g) => g.status === "未通过");
const blockedGates = gateOutcomes.filter((g) => g.status === "被阻断");
const highVerified = findings.filter((f) => f.severity === "high" && f.status === "verified");
const prelimPass = blockingGates.length === 0 && highVerified.length === 0;

// ---- 阶段：独立审读并汇总验收报告 ----
phase("独立审读并汇总验收报告");
const verdict = await agent("验收主笔").ask<Verdict>(
  "下面是 Django 模块 apps/" + app + " 的验收材料。请独立审读：按项目规则（根 AGENTS.md 第九节、spug_api/AGENTS.md），" +
  "程序按「存在未通过门禁或有坐实的 high 发现即不通过」初判为「" + (prelimPass ? "通过" : "不通过") + "」。\n" +
  "你审读材料后给出最终结论；不同意初判就说明理由。如果材料之间互相矛盾或关键信息缺失（例如门禁说失败但发现列表为空），写进 inconsistencies。\n" +
  "不要修改任何文件。\n" +
  JSON.stringify({
    gateOutcomes,
    lensSummaries: auditResults.map((r) => ({ lens: r.lensName, summary: r.summary })),
    findings: findings.map((f) => ({ where: f.where, what: f.what, severity: f.severity, status: f.status })),
    moduleFacts: { hasFrontend, hasAttachments, hasCelery, testFiles: testFiles.length, pyFiles: pyFiles.length },
  }),
);

const verifiedList: string[] = gateOutcomes.map((g) => g.name + "：" + g.status);
verifiedList.push(
  "静态审计：" + lenses.length + " 个镜头（" + lenses.map((l) => l.name).join("、") + "），中高严重度发现由独立子代理逐条复核代码坐实，低严重度与超出上限的发现标注 unconfirmed",
);
verifiedList.push("测试与迁移命令在 " + CONTAINER + " 容器内执行（bind mount 当前工作区），退出码与输出为准");

const notCovered: string[] = [];
for (const b of blockedGates) notCovered.push(b.name + "被阻断：" + b.detail);
if (!hasFrontend) notCovered.push("前端一致性未检查：spug_web/src/pages/" + app + " 不存在且 routes.js 无引用（纯后端模块）");
if (hasFrontend) notCovered.push("前端 jest 未在本工作流内执行，前端一致性为静态审计结论");
notCovered.push("实机 E2E 走查与性能压测不在本工作流范围内");

const md = [
  "# 模块验收报告 · apps/" + app,
  "",
  "## 结论",
  "",
  verdict.verdict,
  "",
  verdict.rationale,
  ...(verdict.inconsistencies.length > 0 ? ["", "> 审读提示：" + verdict.inconsistencies.join("；")] : []),
  "",
  "## 检查项",
  "",
  ...gateOutcomes.map((g) => "- **" + g.name + "**：" + g.status + " — " + g.detail),
  "",
  "## 静态审计",
  "",
  ...auditResults.map((r) => "- **" + r.lensName + "**：" + r.summary + "（发现 " + r.findings.length + " 条）"),
  "",
  "## 发现清单",
  "",
  ...(findings.length > 0
    ? findings.map(
        (f) =>
          "- [" + f.severity + "/" + f.status + "] `" + f.where + "` — " + f.what +
          (f.status === "unconfirmed" ? "（复核未坐实，供人工参考）" : ""),
      )
    : ["无"]),
  "",
  "## 已验证",
  "",
  ...verifiedList.map((v) => "- " + v),
  "",
  "## 未覆盖",
  "",
  ...notCovered.map((v) => "- " + v),
  "",
].join("\n");
await artifact.markdown("report", md, {
  title: "模块验收报告 · " + app,
  description: "多镜头静态审计 + 确定性门禁的验收结论与全部发现",
  primary: true,
});

const result: WorkflowReport = {
  conclusion: verdict.verdict + " " + verdict.rationale,
  findings,
  verified: verifiedList,
  notCovered,
};
return result;
