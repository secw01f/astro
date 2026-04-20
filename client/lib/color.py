color_map = {
    "red": "\033[91m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "blue": "\033[94m",
    "magenta": "\033[95m",
    "cyan": "\033[96m",
    "white": "\033[97m",
    "normal": "\033[0m",
}

weight_map = {
    "bold": "\033[1m",
    "italic": "\033[3m",
    "underline": "\033[4m",
    "strikethrough": "\033[9m",
    "normal": "\033[0m",
}   

def colorize(text: str, color: str, weight: str = "normal"):
    return f"{color_map[color]}{weight_map[weight]}{text}{color_map['normal']}"

def red(text: str, weight: str = "normal"):
    return colorize(text, "red", weight)

def green(text: str, weight: str = "normal"):
    return colorize(text, "green", weight)

def yellow(text: str, weight: str = "normal"):
    return colorize(text, "yellow", weight)

def blue(text: str, weight: str = "normal"):
    return colorize(text, "blue", weight)

def magenta(text: str, weight: str = "normal"):
    return colorize(text, "magenta", weight)

def cyan(text: str, weight: str = "normal"):
    return colorize(text, "cyan", weight)

def white(text: str, weight: str = "normal"):
    return colorize(text, "white", weight)