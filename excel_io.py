# excel_io.py
"""Read and write task data from/to Excel files."""

from dataclasses import dataclass
from pathlib import Path
from openpyxl import load_workbook


@dataclass(frozen=True)
class Task:
    task_id: str
    url: str
    instructions: str


def read_tasks(path: str | Path) -> list[Task]:
    """Read tasks from Excel, skipping rows where status is 'success'."""
    wb = load_workbook(path)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]

    task_id_col = headers.index("task_id")
    url_col = headers.index("url")
    instructions_col = headers.index("instructions")
    status_col = headers.index("status") if "status" in headers else None

    tasks = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if status_col is not None and row[status_col] == "success":
            continue
        tasks.append(Task(
            task_id=str(row[task_id_col]),
            url=str(row[url_col]),
            instructions=str(row[instructions_col]),
        ))
    return tasks


def update_task_result(
    path: str | Path,
    task_id: str,
    screenshot_link: str,
    status: str,
    error: str,
) -> None:
    """Write task results back to the Excel file."""
    wb = load_workbook(path)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]

    # Add result columns if missing
    for col_name in ("screenshot_link", "status", "error"):
        if col_name not in headers:
            headers.append(col_name)
            ws.cell(row=1, column=len(headers), value=col_name)

    task_id_col = headers.index("task_id")
    ss_col = headers.index("screenshot_link") + 1  # openpyxl is 1-indexed
    status_col = headers.index("status") + 1
    error_col = headers.index("error") + 1

    for row in ws.iter_rows(min_row=2):
        if str(row[task_id_col].value) == task_id:
            ws.cell(row=row[0].row, column=ss_col, value=screenshot_link)
            ws.cell(row=row[0].row, column=status_col, value=status)
            ws.cell(row=row[0].row, column=error_col, value=error)
            break

    wb.save(path)
