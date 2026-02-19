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
ws.append([
    "T003",
    "https://mictests.com/",
    (
        "Click the 'Test my mic' button to start the microphone test. "
        "Wait for the audio visualization to appear (waveform or volume bars moving). "
        "Verify that the page detects audio input and shows a result like 'Microphone is working'. "
        "Take a screenshot showing the test result."
    ),
])
wb.save("tasks.xlsx")
print("Created tasks.xlsx with 3 sample tasks.")
