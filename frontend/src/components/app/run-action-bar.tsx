"use client"

import * as React from "react"
import {
  CheckIcon,
  CopyIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import type { TFunction } from "@/i18n"
import { copyText } from "@/lib/clipboard"

type FeedbackValue = "positive" | "negative" | null

type RunActionBarProps = {
  result: string
  feedback?: FeedbackValue
  regenerating?: boolean
  feedbackPending?: boolean
  regenerateDisabled?: boolean
  onRegenerate: () => void
  onFeedback: (value: FeedbackValue) => void
  t: TFunction
}

export function RunActionBar({
  result,
  feedback = null,
  regenerating = false,
  feedbackPending = false,
  regenerateDisabled = false,
  onRegenerate,
  onFeedback,
  t,
}: RunActionBarProps) {
  const [copied, setCopied] = React.useState(false)
  const regenerateButtonDisabled =
    regenerateDisabled || regenerating || feedbackPending
  const feedbackButtonsDisabled = regenerating || feedbackPending
  const copyLabel = t(copied ? "已复制" : "复制")

  async function handleCopy() {
    try {
      await copyText(result)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="mt-1 flex items-center justify-end gap-1">
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        className="text-muted-foreground"
        aria-label={t(regenerating ? "正在重新生成" : "重新生成")}
        title={t(regenerating ? "正在重新生成" : "重新生成")}
        aria-busy={regenerating}
        disabled={regenerateButtonDisabled}
        onClick={onRegenerate}
      >
        {regenerating ? (
          <LoaderCircleIcon className="animate-spin" />
        ) : (
          <RefreshCwIcon />
        )}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        className={
          feedback === "positive"
            ? "bg-muted text-foreground"
            : "text-muted-foreground"
        }
        aria-label={t(feedback === "positive" ? "取消点赞" : "点赞")}
        title={t(feedback === "positive" ? "取消点赞" : "点赞")}
        aria-pressed={feedback === "positive"}
        disabled={feedbackButtonsDisabled}
        onClick={() => onFeedback(feedback === "positive" ? null : "positive")}
      >
        <ThumbsUpIcon />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        className={
          feedback === "negative"
            ? "bg-muted text-foreground"
            : "text-muted-foreground"
        }
        aria-label={t(feedback === "negative" ? "取消点踩" : "点踩")}
        title={t(feedback === "negative" ? "取消点踩" : "点踩")}
        aria-pressed={feedback === "negative"}
        disabled={feedbackButtonsDisabled}
        onClick={() => onFeedback(feedback === "negative" ? null : "negative")}
      >
        <ThumbsDownIcon />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        className="text-muted-foreground"
        aria-label={copyLabel}
        title={copyLabel}
        onClick={() => void handleCopy()}
      >
        {copied ? <CheckIcon /> : <CopyIcon />}
      </Button>
    </div>
  )
}
