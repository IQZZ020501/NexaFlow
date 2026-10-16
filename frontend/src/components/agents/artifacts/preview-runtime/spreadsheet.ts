import ExcelJS, { type CellValue } from "exceljs"
import type { Viewer } from "../preview-protocol"

const MAX_ROWS = 500
const MAX_COLUMNS = 50

function cellText(value: CellValue): string {
  if (value == null) return ""
  if (value instanceof Date)
    return value.toISOString().replace("T00:00:00.000Z", "")
  if (typeof value !== "object") return String(value)
  if ("richText" in value)
    return value.richText.map(({ text }) => text).join("")
  if ("text" in value) return value.text
  if ("error" in value) return value.error
  if ("result" in value) return cellText(value.result)
  return ""
}

function color(argb?: string) {
  return argb && /^[a-f\d]{8}$/i.test(argb) ? `#${argb.slice(2)}` : ""
}

export async function openSpreadsheet(
  container: HTMLElement,
  bytes: ArrayBuffer,
  emptyLabel: string
): Promise<Viewer> {
  const workbook = new ExcelJS.Workbook()
  // ExcelJS's browser loader accepts ArrayBuffer; its declarations call this Buffer.
  await workbook.xlsx.load(
    bytes as unknown as Parameters<typeof workbook.xlsx.load>[0]
  )
  const sheets = workbook.worksheets.filter(
    (sheet) => sheet.state === "visible"
  )
  if (!sheets.length) throw new Error("No visible worksheets")
  const content = document.createElement("div")
  container.append(content)
  let currentSheet = -1
  const metadata = {
    pageCount: 0,
    sheets: sheets.map((sheet) => sheet.name),
    truncated: false,
  }
  return {
    metadata,
    render({ sheet: index, zoom }) {
      content.style.zoom = String(zoom)
      if (index === currentSheet) return
      const sheet = sheets[index]
      currentSheet = index
      content.replaceChildren()
      metadata.truncated =
        sheet.rowCount > MAX_ROWS || sheet.columnCount > MAX_COLUMNS
      if (!sheet.actualRowCount) {
        content.textContent = emptyLabel
        return
      }
      const table = document.createElement("table")
      const heading = table.createTHead().insertRow()
      heading.append(document.createElement("th"))
      const columns = Math.min(sheet.columnCount, MAX_COLUMNS)
      for (let column = 1; column <= columns; column++) {
        const th = document.createElement("th")
        th.scope = "col"
        th.textContent = sheet.getColumn(column).letter
        heading.append(th)
      }
      const body = table.createTBody()
      for (
        let rowIndex = 1;
        rowIndex <= Math.min(sheet.rowCount, MAX_ROWS);
        rowIndex++
      ) {
        const row = sheet.getRow(rowIndex)
        const tr = body.insertRow()
        const th = document.createElement("th")
        th.scope = "row"
        th.textContent = String(rowIndex)
        tr.append(th)
        for (let column = 1; column <= columns; column++) {
          const cell = row.getCell(column)
          const td = tr.insertCell()
          td.textContent =
            cell.isMerged && cell.master.address !== cell.address
              ? ""
              : cellText(cell.value)
          td.style.color = color(cell.font?.color?.argb)
          td.style.fontWeight = cell.font?.bold ? "700" : "400"
          td.style.fontStyle = cell.font?.italic ? "italic" : "normal"
          const alignment = cell.alignment?.horizontal
          if (alignment && ["left", "center", "right"].includes(alignment))
            td.style.textAlign = alignment
          const fill = cell.fill
          if (fill?.type === "pattern" && fill.pattern === "solid")
            td.style.backgroundColor = color(fill.fgColor?.argb)
        }
      }
      content.append(table)
    },
    destroy() {
      content.remove()
    },
  }
}
