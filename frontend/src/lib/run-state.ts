/** A late HTTP response cannot move a persisted terminal Run back to running. */
export function isStaleRunSnapshot(current: { id: string; status: string }, incoming: { id: string; status: string }) {
  return current.id === incoming.id && ["succeeded", "failed", "cancelled"].includes(current.status) && current.status !== incoming.status
}
