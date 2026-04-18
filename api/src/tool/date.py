from datetime import datetime

from haystack.tools import tool, Toolset

@tool(name="today")
def date_get_todays_date() -> str:
    return datetime.now().isoformat()

@tool(name="current_time")
def date_get_current_time() -> str:
    return datetime.now().strftime("%H:%M:%S")

def DateToolset() -> Toolset:
    return Toolset([date_get_todays_date, date_get_current_time])
