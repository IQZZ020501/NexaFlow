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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { TFunction } from "@/i18n"
import { copyText } from "@/lib/clipboard"
import { cn } from "@/lib/utils"

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

/**
 * Returns the localized confirmation shown after feedback is saved.
 */
export function feedbackConfirmationLabel(
  feedback: FeedbackValue,
  t: TFunction
) {
  if (feedback === "positive") return t("已点赞")
  if (feedback === "negative") return t("已点踩")
  return t("已取消反馈")
}

/**
 * Renders controls for regenerating a result, submitting feedback, and copying its text.
 *
 * @param result - The result text to copy
 * @param feedback - The currently selected feedback option
 * @param regenerating - Whether result regeneration is in progress
 * @param feedbackPending - Whether feedback submission is in progress
 * @param regenerateDisabled - Whether regeneration is explicitly disabled
 * @param onRegenerate - Handles result regeneration
 * @param onFeedback - Handles feedback selection changes
 * @param t - Translates control labels
 */
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
  const positiveSelected = feedback === "positive"
  const negativeSelected = feedback === "negative"
  const positiveLabel = t(positiveSelected ? "取消点赞" : "点赞")
  const negativeLabel = t(negativeSelected ? "取消点踩" : "点踩")

  async function handleCopy() {
    try {
      await copyText(result)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <TooltipProvider delayDuration={250}>
      <div className="mt-1 flex flex-wrap items-center justify-end gap-1">
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
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              className={cn(
                "text-muted-foreground",
                positiveSelected &&
                  "bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary dark:bg-primary/20"
              )}
              aria-label={positiveLabel}
              aria-pressed={positiveSelected}
              disabled={feedbackButtonsDisabled}
              onClick={() => onFeedback(positiveSelected ? null : "positive")}
            >
              <ThumbsUpIcon
                className={
                  positiveSelected ? "fill-current stroke-[2.25]" : undefined
                }
              />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{positiveLabel}</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              className={cn(
                "text-muted-foreground",
                negativeSelected &&
                  "bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary dark:bg-primary/20"
              )}
              aria-label={negativeLabel}
              aria-pressed={negativeSelected}
              disabled={feedbackButtonsDisabled}
              onClick={() => onFeedback(negativeSelected ? null : "negative")}
            >
              <ThumbsDownIcon
                className={
                  negativeSelected ? "fill-current stroke-[2.25]" : undefined
                }
              />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{negativeLabel}</TooltipContent>
        </Tooltip>
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
    </TooltipProvider>
  )
}
