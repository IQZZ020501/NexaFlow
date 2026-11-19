"use client"

import { ArrowUpRightIcon } from "lucide-react"

import type { TFunction } from "@/i18n"

export function AgentSuggestedQuestions({
  questions,
  onSelect,
  disabled,
  t,
}: {
  questions?: string[]
  onSelect?: (question: string) => void
  disabled?: boolean
  t: TFunction
}) {
  if (!questions?.length || !onSelect) return null

  return (
    <section
      className="mt-4 flex flex-col items-start gap-1.5"
      aria-label={t("你可能还想问")}
    >
      <p className="mb-1 text-xs font-medium text-muted-foreground">
        {t("你可能还想问")}
      </p>
      {questions.slice(0, 3).map((question) => (
        <button
          key={question}
          type="button"
          disabled={disabled}
          onClick={() => onSelect(question)}
          className="group inline-flex w-fit max-w-full cursor-pointer items-start gap-2 rounded-lg border border-transparent px-3 py-1.5 text-left text-[13px] leading-5 text-foreground/80 transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50"
        >
          <span className="min-w-0 break-words">{question}</span>
          <ArrowUpRightIcon
            className="mt-0.5 size-3.5 shrink-0 text-muted-foreground transition-colors group-hover:text-foreground"
            aria-hidden="true"
          />
        </button>
      ))}
    </section>
  )
}
