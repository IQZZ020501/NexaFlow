import { Button } from "@/components/ui/button"

export function App() {
  return (
    <div className="flex min-h-svh p-6">
      <div className="flex max-w-md min-w-0 flex-col gap-4 text-sm leading-loose">
        <div>
          <h1 className="font-medium">NexaFlow Web</h1>
          <p>React + Vite + TypeScript + shadcn/ui is ready.</p>
          <p>Backend stays in the app directory; frontend starts here.</p>
          <Button className="mt-2">Start building</Button>
        </div>
        <div className="font-mono text-xs text-muted-foreground">
          (Press <kbd>d</kbd> to toggle dark mode)
        </div>
      </div>
    </div>
  )
}

export default App
