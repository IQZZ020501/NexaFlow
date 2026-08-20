import { ChevronDownIcon, CircleCheckIcon } from "lucide-react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"

export type FilterDropdownOption = {
  value: string
  label: string
}

/**
 * Renders a dropdown for selecting a value from a list of labeled options.
 *
 * @param ariaLabel - Accessible label for the dropdown trigger
 * @param value - Currently selected option value
 * @param options - Available dropdown options
 * @param onChange - Called with the selected option value
 * @returns The rendered filter dropdown
 */
export function FilterDropdown({
  id,
  ariaLabel,
  value,
  options,
  className,
  disabled = false,
  modal,
  onChange,
}: {
  id?: string
  ariaLabel: string
  value: string
  options: FilterDropdownOption[]
  className?: string
  disabled?: boolean
  modal?: boolean
  onChange: (value: string) => void
}) {
  const selectedOption = options.find((option) => option.value === value)

  return (
    <DropdownMenu modal={modal}>
      <DropdownMenuTrigger asChild>
        <button
          id={id}
          type="button"
          className={cn(
            "flex h-8 w-full items-center justify-between gap-2 rounded-lg border bg-background px-2 text-sm disabled:pointer-events-none disabled:opacity-50",
            className,
          )}
          aria-label={ariaLabel}
          title={selectedOption?.label ?? value}
          disabled={disabled}
        >
          <span className="truncate">{selectedOption?.label ?? value}</span>
          <ChevronDownIcon className="size-4 shrink-0 text-muted-foreground" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        sideOffset={6}
        collisionPadding={8}
        className="max-h-80 min-w-[var(--radix-dropdown-menu-trigger-width)] overflow-y-auto overscroll-contain"
      >
        <DropdownMenuGroup>
          {options.map((option) => (
            <DropdownMenuItem
              key={option.value}
              onSelect={() => onChange(option.value)}
              className="justify-between"
              title={option.label}
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
