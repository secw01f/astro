from haystack.tools import tool, Toolset

@tool(name="add", description="Add two integers.")
def math_add(x: int, y: int) -> int:
    return x + y

@tool(name="subtract", description="Subtract y from x.")
def math_subtract(x: int, y: int) -> int:
    return x - y

@tool(name="multiply", description="Multiply two integers.")
def math_multiply(x: int, y: int) -> int:
    return x * y

@tool(name="divide", description="Divide x by y.")
def math_divide(x: int, y: int) -> float:
    return x / y

def MathToolset() -> Toolset:
    return Toolset([math_add, math_subtract, math_multiply, math_divide])
