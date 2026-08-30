"use client"

import { ArrowLeftIcon } from "lucide-react"
import Link from "next/link"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { BuiltinToolIcon } from "@/components/tools/builtin-tool-icon"
import { useLanguage } from "@/contexts/language-provider"

/** Shows the built-in Skill bundles and the deployment-side installation flow. */
export function SkillsPage() {
  const { t } = useLanguage()
  const skills = [
    {
      id: "documents",
      name: t("DOCX"),
      description: t("Word 与 Google Docs 文档"),
      runtime: t("DOCX · python-docx"),
      functionName: "documents_skill",
    },
    {
      id: "pdf",
      name: t("PDF"),
      description: t("PDF 创建、检查与渲染"),
      runtime: t("PDF · PyMuPDF"),
      functionName: "pdf_skill",
    },
    {
      id: "pptx",
      name: t("PPTX"),
      description: t("演示文稿、模板与品牌主题"),
      runtime: t("PPTX · python-pptx"),
      functionName: "pptx_skill",
    },
    {
      id: "spreadsheets",
      name: t("Excel"),
      description: t("电子表格创建与分析"),
      runtime: t("XLSX · openpyxl"),
      functionName: "spreadsheets_skill",
    },
  ]

  return (
    <main className="min-w-0 space-y-6">
      <Button asChild variant="ghost" className="-ml-3">
        <Link href="/app/tools">
          <ArrowLeftIcon />
          {t("返回工具")}
        </Link>
      </Button>

      <div>
        <h1 className="text-2xl font-semibold">{t("Skills")}</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          {t(
            "四个内置 Skills 都有自己的生成脚本，并作为工具出现在工具中心、Agent 选择器和 Workflow 节点库。"
          )}
        </p>
      </div>

      <section aria-labelledby="builtin-skills-heading">
        <h2 id="builtin-skills-heading" className="mb-3 text-sm font-semibold">
          {t("内置 Skills")}
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {skills.map((skill) => {
            return (
              <article key={skill.id} className="rounded-lg border p-4">
                <div className="flex items-start justify-between gap-3">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted/70">
                    <BuiltinToolIcon
                      functionName={skill.functionName}
                      className="size-5 text-base leading-none"
                    />
                  </span>
                  <Badge variant="secondary">{t("内置")}</Badge>
                </div>
                <h3 className="mt-4 font-medium">{skill.name}</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  {skill.description}
                </p>
                <p className="mt-3 text-xs text-muted-foreground">
                  {skill.runtime}
                </p>
              </article>
            )
          })}
        </div>
      </section>

      <section
        className="rounded-lg border p-4"
        aria-labelledby="install-heading"
      >
        <h2 id="install-heading" className="font-semibold">
          {t("手动安装")}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {t(
            "内置 Skill bundle 随 Worker 提供；自定义 bundle 仍由部署管理员写入 Worker 文件系统。"
          )}
        </p>
        <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm">
          <li>{t("在 Worker 配置的目录下创建 Skill 文件夹。")}</li>
          <li>
            {t(
              "在 SKILL.md 中声明 entrypoint 和 artifact-format，并提供对应的 Python 入口脚本。"
            )}
          </li>
          <li>{t("需要额外 Python 包时再添加 requirements.txt。")}</li>
          <li>
            {t(
              "重启 Worker，并注册匹配的 Tool 输入契约；仅复制目录不会自动出现在选择器中。"
            )}
          </li>
        </ol>
        <pre className="mt-4 overflow-x-auto rounded-md bg-muted p-4 text-xs leading-6">
          <code>{`$SANDBOX_SKILLS_DIR/invoice/
├── SKILL.md
├── scripts/
│   └── render.py
└── requirements.txt  # optional`}</code>
        </pre>
      </section>

      <section className="rounded-lg border p-4" aria-labelledby="use-heading">
        <h2 id="use-heading" className="font-semibold">
          {t("运行方式")}
        </h2>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <div>
            <h3 className="text-sm font-medium">{t("绑定到 Agent")}</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              {t(
                "在 Agent 工具选择器中授权 DOCX、PDF、PPTX 或 Excel 工具；运行时模型会根据用户目标和工具描述自主选择。"
              )}
            </p>
          </div>
          <div>
            <h3 className="text-sm font-medium">{t("Skill 自带执行")}</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              {t(
                "Agent 只提交 Markdown、结构化演示文稿或表格数据，Worker 运行 Skill bundle 内声明的入口脚本，不执行调用方提供的 Python。"
              )}
            </p>
          </div>
          <div>
            <h3 className="text-sm font-medium">{t("平台安全边界")}</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              {t(
                "沙箱隔离、资源限额、文件校验、临时存储和下载链接仍由平台统一负责。"
              )}
            </p>
          </div>
        </div>
      </section>
    </main>
  )
}
