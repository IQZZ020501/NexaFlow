import type { AgentSessionInput } from "@/lib/api/agents"

type AppliedInput = Pick<
  AgentSessionInput,
  "sequence" | "input_id" | "mode" | "content" | "previous_answer_turn"
>

export function splitAgentSessionEvents<T extends { turn: number }>(
  events: T[],
  inputs: AgentSessionInput[] = [],
  isAnswerReady: (event: T) => boolean
): T[][] {
  const completed = inputs.filter((input) => Boolean(input.previous_answer))
  if (!completed.length) return [events]

  if (completed.every((input) => input.previous_answer_turn != null)) {
    const segments = Array.from(
      { length: completed.length + 1 },
      () => [] as T[]
    )
    for (const event of events) {
      const index = completed.findIndex(
        (input) => event.turn <= input.previous_answer_turn!
      )
      segments[index === -1 ? completed.length : index].push(event)
    }
    return segments
  }

  const segments: T[][] = []
  let pending: T[] = []
  for (const event of events) {
    pending.push(event)
    if (isAnswerReady(event) && segments.length < completed.length) {
      segments.push(pending)
      pending = []
    }
  }
  segments.push(pending)
  while (segments.length < completed.length + 1) segments.unshift([])
  return segments
}

export function sessionInputsAfterAnswerHandoff(
  run: { id: string; result: string; session_inputs?: AgentSessionInput[] },
  appliedInputs: AppliedInput[] = []
): AgentSessionInput[] {
  const inputs = [...(run.session_inputs ?? [])]
  for (const input of appliedInputs) {
    if (!inputs.some((current) => current.input_id === input.input_id)) {
      inputs.push({ ...input, run_id: run.id })
    }
  }
  const appliedIds = new Set(appliedInputs.map((input) => input.input_id))
  const firstInputId = appliedInputs[0]?.input_id
  return inputs.map((input) => {
    if (!appliedIds.has(input.input_id)) return input
    const applied = appliedInputs.find(
      (item) => item.input_id === input.input_id
    )
    return {
      ...input,
      status: "applied",
      previous_answer:
        input.input_id === firstInputId
          ? run.result || input.previous_answer
          : input.previous_answer,
      previous_answer_turn:
        applied?.previous_answer_turn ?? input.previous_answer_turn,
    }
  })
}

export function mergeAgentSessionInputReceipt(
  inputs: AgentSessionInput[] = [],
  receipt: AgentSessionInput
): AgentSessionInput[] {
  const existing = inputs.find((input) => input.input_id === receipt.input_id)
  return [
    ...inputs.filter((input) => input.input_id !== receipt.input_id),
    {
      ...receipt,
      status: existing?.status === "applied" ? "applied" : receipt.status,
      previous_answer: receipt.previous_answer ?? existing?.previous_answer,
      previous_answer_turn:
        receipt.previous_answer_turn ?? existing?.previous_answer_turn,
    },
  ]
}
