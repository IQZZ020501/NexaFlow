export function latestRunVersions<
  T extends {
    id: string
    regenerated_from_run_id?: string | null
    status?: string
  },
>(runs: T[]) {
  const failedRegenerations = new Set(
    runs
      .filter(
        (run) =>
          (run.status === "failed" || run.status === "cancelled") &&
          Boolean(run.regenerated_from_run_id)
      )
      .map((run) => run.id)
  )
  const superseded = new Set(
    runs
      .filter((run) => run.status !== "failed" && run.status !== "cancelled")
      .map((run) => run.regenerated_from_run_id)
      .filter((id): id is string => Boolean(id))
  )
  return runs.filter(
    (run) => !failedRegenerations.has(run.id) && !superseded.has(run.id)
  )
}
