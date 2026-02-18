"""Generate a sample tasks.xlsx for testing."""

from openpyxl import Workbook

wb = Workbook()
ws = wb.active
ws.append(["task_id", "url", "instructions"])
ws.append([
    "T001",
    "https://example.com",
    "Verify the page title says 'Example Domain'. Click the 'More information...' link.",
])
ws.append([
    "T002",
    "https://httpbin.org/forms/post",
    (
        "Fill the form: set 'custname' to 'Test User', 'custtel' to '555-1234', "
        "select 'medium' pizza size, check 'bacon' topping, and submit the form."
    ),
])
wb.save("tasks.xlsx")
print("Created tasks.xlsx with 2 sample tasks.")
