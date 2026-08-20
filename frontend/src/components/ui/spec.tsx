/**
 * Renders a labeled value with truncation and the full value available as a tooltip.
 *
 * @param label - The label displayed above the value
 * @param value - The value displayed and exposed in the tooltip
 */
export function Spec({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 truncate font-medium" title={value}>
        {value}
      </dd>
    </div>
  )
}
