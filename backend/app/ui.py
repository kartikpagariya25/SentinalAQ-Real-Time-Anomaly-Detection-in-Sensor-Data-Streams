import colorama

colorama.just_fix_windows_console()

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"


def paint(text, *styles):
    return "".join(styles) + str(text) + RESET


def title(text):
    bar = "=" * 78
    print(paint(f"\n{bar}\n  {text}\n{bar}", BOLD, CYAN))


def step(text):
    print(paint(f"\n> {text}", BOLD))


def ok(text):
    print(paint(f"  [ok] {text}", GREEN))


def warn(text):
    print(paint(f"  [!]  {text}", YELLOW))


def table(headers, rows, highlight=None):
    cells = [[str(c) for c in r] for r in rows]
    widths = [max(len(str(h)), *(len(r[i]) for r in cells)) if cells else len(str(h)) for i, h in enumerate(headers)]
    line = "  " + "-+-".join("-" * w for w in widths)
    print("  " + " | ".join(str(h).ljust(w) for h, w in zip(headers, widths)))
    print(line)
    for i, r in enumerate(cells):
        text = "  " + " | ".join(c.ljust(w) for c, w in zip(r, widths))
        if highlight is not None and highlight(i, rows[i]):
            text = paint(text, BOLD, GREEN)
        print(text)
