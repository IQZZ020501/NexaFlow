import { ChevronDownIcon, CircleCheckIcon } from "lucide-react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

export type FilterDropdownOption = {
  value: string
  label: string
}

export function FilterDropdown({
  ariaLabel,
  value,
  options,
  onChange,
}: {
  ariaLabel: string
  value: string
  options: FilterDropdownOption[]
  onChange: (value: string) => void
}) {
  const selectedOption = options.find((option) => option.value === value)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex h-8 w-full items-center justify-between gap-2 rounded-lg border bg-background px-2 text-sm"
          aria-label={ariaLabel}
        >
          <span className="truncate">{selectedOption?.label ?? value}</span>
          <ChevronDownIcon className="size-4 shrink-0 text-muted-foreground" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="min-w-[var(--radix-dropdown-menu-trigger-width)]"
      >
        <DropdownMenuGroup>
          {options.map((option) => (
            <DropdownMenuItem
              key={option.value}
              onSelect={() => onChange(option.value)}
              className="justify-between"
            >
              <span className="truncate">{option.label}</span>
              {option.value === value ? (
                <CircleCheckIcon className="text-primary" />
              ) : null}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
