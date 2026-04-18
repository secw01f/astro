import typer
import jinja2
import pathlib

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
    output = str(router_dir + f"{name}.py")

    try:
        with open(output, "w") as file:
            file.write(router)
            file.close()
    
        print(f"The {name} router has been created.")
    except:
        print(f"The {name} router failed to create.")