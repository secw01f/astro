from haystack.tools import tool, Toolset

@tool(name="add")
def math_add(x: int, y: int) -> int:
    return x + y

@tool(name="subtract")
def math_subtract(x: int, y: int) -> int:
    return x - y

@tool(name="multiply")
def math_multiply(x: int, y: int) -> int:
    return x * y

@tool(name="divide")
def math_divide(x: int, y: int) -> float:
    return x / y

def MathToolset() -> Toolset:
    return Toolset([math_add, math_subtract, math_multiply, math_divide])
