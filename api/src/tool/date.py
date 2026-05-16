from datetime import datetime

from haystack.tools import tool, Toolset

@tool(name="today", description="Return today's date in ISO 8601 format.")
def date_get_todays_date() -> str:
    return datetime.now().isoformat()

@tool(name="current_time", description="Return the current local time as HH:MM:SS.")
def date_get_current_time() -> str:
    return datetime.now().strftime("%H:%M:%S")

def DateToolset() -> Toolset:
    return Toolset([date_get_todays_date, date_get_current_time])
