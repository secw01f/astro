import typer
import jinja2
from pathlib import Path

from typing import Annotated

app = typer.Typer()

@app.command()
def create(name: Annotated[str, typer.Option(default=...)], protected: Annotated[bool, typer.Option(default=False)]):
    template_dir = Path("../templates").resolve()
    router_dir = Path("../../src/router/").resolve()
    loader = jinja2.FileSystemLoader(searchpath=template_dir)
    env = jinja2.Environment(loader=loader)
    template = env.get_template("router.py.j2")
    router = template.render(name=name, protected=protected)
    output = router_dir / f"{name}.py"

    try:
        with output.open("w") as file:
            file.write(router)
    
        print(f"The {name} router has been created.")
    except OSError:
        print(f"The {name} router failed to create.")
