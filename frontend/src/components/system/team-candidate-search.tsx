import * as React from "react"
import { SearchIcon, XIcon } from "lucide-react"

import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import type { WorkspaceMember } from "@/lib/api/system"
import { cn } from "@/lib/utils"

type TeamCandidateSearchProps = {
  id?: string
  ariaLabel?: string
  placeholder?: string
  candidates: WorkspaceMember[]
  value: string
  onChange: (userId: string) => void
  isLoading?: boolean
  disabled?: boolean
  className?: string
}

function isSubsequenceMatch(query: string, text: string): boolean {
  let qi = 0
  for (let ti = 0; ti < text.length && qi < query.length; ti += 1) {
    if (text[ti] === query[qi]) {
      qi += 1
    }
  }
  return qi === query.length
}

function scoreCandidate(query: string, candidate: WorkspaceMember): number {
  const fields = [
    candidate.user.name.toLowerCase(),
    candidate.user.username.toLowerCase(),
    candidate.user.email.toLowerCase(),
  ]
  if (fields.some((field) => field.startsWith(query))) {
    return 3
  }
  if (fields.some((field) => field.includes(query))) {
    return 2
  }
  if (fields.some((field) => isSubsequenceMatch(query, field))) {
    return 1
  }
  return 0
}

/**
 * Searchable fuzzy-match combobox for picking a workspace member candidate to
 * add to a team.
 */
export function TeamCandidateSearch({
  id,
  ariaLabel,
  placeholder,
  candidates,
  value,
  onChange,
  isLoading = false,
  disabled = false,
  className,
}: TeamCandidateSearchProps) {
  const { t } = useLanguage()
  const [query, setQuery] = React.useState("")
  const [isOpen, setIsOpen] = React.useState(false)
  const containerRef = React.useRef<HTMLDivElement | null>(null)

  const selectedCandidate = React.useMemo(
    () => candidates.find((candidate) => candidate.user.id === value) ?? null,
    [candidates, value]
  )

  const isInputDisabled = disabled || isLoading || !candidates.length

  const filteredCandidates = React.useMemo(() => {
    const normalized = query.trim().toLowerCase()
    if (!normalized) {
      return candidates
    }
    return candidates
      .map((candidate, index) => ({
        candidate,
        index,
        score: scoreCandidate(normalized, candidate),
      }))
      .filter((entry) => entry.score > 0)
      .sort((a, b) => b.score - a.score || a.index - b.index)
      .map((entry) => entry.candidate)
  }, [candidates, query])

  React.useEffect(() => {
    if (!isOpen) {
      return
    }
    function handleMouseDown(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false)
      }
    }
    document.addEventListener("mousedown", handleMouseDown)
    return () => document.removeEventListener("mousedown", handleMouseDown)
  }, [isOpen])

  const resolvedPlaceholder = isLoading
    ? t("正在加载")
    : !candidates.length
      ? t("暂无可加入成员")
      : (placeholder ?? t("搜索待添加成员"))

  const displayValue = selectedCandidate
    ? `${selectedCandidate.user.name} · ${selectedCandidate.user.username}`
    : query

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <div className="relative">
        <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          id={id}
          role="combobox"
          aria-label={ariaLabel}
          aria-expanded={Boolean(isOpen && !isInputDisabled)}
          aria-autocomplete="list"
          value={displayValue}
          placeholder={resolvedPlaceholder}
          disabled={isInputDisabled}
          className={cn("pr-8 pl-8", selectedCandidate && "font-medium")}
          onFocus={() => {
            if (!isInputDisabled) {
              setIsOpen(true)
            }
          }}
          onChange={(event) => {
            const nextQuery = event.target.value
            if (value) {
              onChange("")
            }
            setQuery(nextQuery)
            setIsOpen(true)
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setIsOpen(false)
            }
          }}
        />
        {!isInputDisabled && (selectedCandidate || query) ? (
          <button
            type="button"
            aria-label={t("清除选择")}
            title={t("清除选择")}
            className="absolute top-1/2 right-2 -translate-y-1/2 rounded-xs p-0.5 text-muted-foreground hover:text-foreground"
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => {
              onChange("")
              setQuery("")
              setIsOpen(true)
            }}
          >
            <XIcon className="size-3.5" />
          </button>
        ) : null}
      </div>

      {isOpen && !isInputDisabled ? (
        <div
          role="listbox"
          className="absolute top-full right-0 left-0 z-50 mt-1 max-h-60 overflow-y-auto overscroll-contain rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
        >
          {filteredCandidates.length ? (
            filteredCandidates.map((candidate) => (
              <button
                key={candidate.user.id}
                type="button"
                role="option"
                aria-selected={candidate.user.id === value}
                className={cn(
                  "flex w-full flex-col items-start rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent hover:text-accent-foreground",
                  candidate.user.id === value &&
                    "bg-accent text-accent-foreground"
                )}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  onChange(candidate.user.id)
                  setQuery("")
                  setIsOpen(false)
                }}
              >
                <span className="w-full truncate font-medium">
                  {candidate.user.name} · {candidate.user.username}
                </span>
                <span className="w-full truncate text-xs text-muted-foreground">
                  {candidate.user.email}
                </span>
              </button>
            ))
          ) : (
            <div className="px-2 py-3 text-center text-xs text-muted-foreground">
              {t("未找到可加入成员")}
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}
