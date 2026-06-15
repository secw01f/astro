import click
import httpx

from lib.auth import persist_token
from lib.banner import banner
from lib.color import cyan, green, red, white, yellow
from lib.config import DEFAULT_URL, ensure_config_file, load_config, set_url

DEFAULT_STACK_USER = "stack"

def _check_api(url: str) -> tuple[bool, str]:
    try:
        response = httpx.get(f"{url.rstrip('/')}/health", timeout=5.0)
    except httpx.ConnectError:
        return False, "Could not connect. Is the API running?"
    except httpx.TimeoutException:
        return False, "Connection timed out."
    except httpx.HTTPError as exc:
        return False, str(exc)

    if response.status_code != 200:
        return False, f"API returned HTTP {response.status_code}."
    return True, "API is reachable."

def _login(url: str, username: str, password: str) -> tuple[bool, str, str | None]:
    try:
        response = httpx.post(
            f"{url.rstrip('/')}/auth/token",
            json={"username": username, "password": password},
            timeout=30.0,
        )
    except httpx.ConnectError:
        return False, "Could not connect to the API.", None
    except httpx.HTTPError as exc:
        return False, str(exc), None

    if response.status_code != 200:
        detail = response.text
        try:
            detail = response.json().get("detail", detail)
        except Exception:
            pass
        return False, f"Login failed: {detail}", None

    data = response.json()
    token = data.get("token")
    if not token:
        return False, "Login response did not include a token.", None

    expires = data.get("expires")
    if expires:
        return True, f"Logged in (token expires in {expires}).", token
    return True, "Logged in successfully.", token

def _create_user(
    url: str,
    admin_token: str,
    username: str,
    email: str,
    role: str,
    password: str | None,
) -> tuple[bool, str]:
    payload = {"username": username, "email": email, "role": role}
    if password is not None:
        payload["password"] = password
    try:
        response = httpx.post(
            f"{url.rstrip('/')}/auth/user/create",
            headers={"X-API-KEY": admin_token},
            json=payload,
            timeout=30.0,
        )
    except httpx.ConnectError:
        return False, "Could not connect to the API.", None
    except httpx.HTTPError as exc:
        return False, str(exc), None

    if response.status_code != 200:
        detail = response.text
        try:
            detail = response.json().get("detail", detail)
        except Exception:
            pass
        return False, f"Failed to create user: {detail}"

    return True, "User created."

def _prompt_new_password() -> str:
    while True:
        new_password = click.prompt("Choose a password", hide_input=True)
        confirm = click.prompt("Confirm password", hide_input=True)
        if new_password == confirm:
            return new_password
        click.echo(red("Passwords do not match. Try again.", "bold"))

def _setup_permanent_user(
    api_url: str,
    admin_token: str,
    *,
    yes: bool,
    skip_create_user: bool,
    role: str,
) -> bool:
    if skip_create_user:
        return False

    click.echo("")
    click.echo(green("Create your permanent account", "bold"))
    click.echo(
        white(
            "The stack user is temporary. Create your own account and set a password now.",
            "normal",
        )
    )

    if not yes and not click.confirm("Create a permanent user?", default=True):
        return False

    new_username = click.prompt("Username")
    new_email = click.prompt("Email")
    if yes:
        new_role = role
    else:
        new_role = click.prompt("Role", type=click.Choice(["admin", "user"]), default=role)

    new_password = _prompt_new_password()

    success, message = _create_user(
        api_url, admin_token, new_username, new_email, new_role, new_password
    )
    if not success:
        click.echo(red(message, "bold"))
        raise SystemExit(1)
    click.echo(green(message, "bold"))

    success, login_message, token = _login(api_url, new_username, new_password)
    if not success:
        click.echo(red(login_message, "bold"))
        click.echo(white("Password was set; log in with: astro auth login", "normal"))
        raise SystemExit(1)

    persist_token(token)
    click.echo(green(login_message, "bold"))
    click.echo(f"{cyan('Permanent account ready', 'bold')}: {new_username} ({new_role})")
    return True

@click.command(help="Interactive first-time setup for the ASTRO CLI")
@click.option("--url", default=None, help=f"API base URL (default: {DEFAULT_URL})")
@click.option("--username", default=None, help="Username for login (default: stack on fresh installs)")
@click.option("--skip-login", is_flag=True, help="Only save the API URL, do not log in")
@click.option(
    "--skip-create-user",
    is_flag=True,
    help="Do not create a permanent user after logging in as stack",
)
@click.option("-y", "--yes", is_flag=True, help="Accept defaults without prompts where possible")
@click.option("--role", type=click.Choice(["admin", "user"]), default="user", help="Role for permanent user creation")
def init(
    url: str | None,
    username: str | None,
    skip_login: bool,
    skip_create_user: bool,
    yes: bool,
    role: str,
):
    click.echo(banner())
    click.echo(green("Welcome to ASTRO setup", "bold"))
    click.echo(white("This wizard configures your CLI, signs you in, and sets up your permanent account.", "normal"))
    click.echo("")

    config = ensure_config_file()
    current_url = config.get("url") or DEFAULT_URL
    default_url = url or current_url or DEFAULT_URL

    if url is None and not yes:
        api_url = click.prompt("API URL", default=default_url).strip()
    else:
        api_url = default_url.strip()

    if not api_url:
        click.echo(red("API URL is required.", "bold"))
        raise SystemExit(1)

    api_url = api_url.rstrip("/")
    set_url(api_url)
    click.echo(f"{green('API URL', 'bold')}: {api_url}")

    click.echo(white("Checking API…", "normal"), nl=False)
    ok, message = _check_api(api_url)
    click.echo("")
    if ok:
        click.echo(green(message, "bold"))
    else:
        click.echo(yellow(message, "bold"))
        if not yes and not click.confirm("Continue anyway?", default=False):
            raise SystemExit(1)

    if skip_login:
        _print_next_steps(logged_in=False)
        return

    has_token = bool(load_config().get("token"))
    if has_token and not yes and not username:
        if not click.confirm("You already have a saved token. Log in again?", default=False):
            _print_next_steps(logged_in=True)
            return

    if username is None and not yes:
        click.echo("")
        click.echo(white(
            "Fresh installs: use the stack user and password printed by ./deploy.sh.",
            "normal",
        ))
        login_now = click.confirm("Log in now?", default=True)
        if not login_now:
            _print_next_steps(logged_in=False)
            return
        username = click.prompt("Username", default=DEFAULT_STACK_USER)
    elif username is None:
        username = DEFAULT_STACK_USER

    password = click.prompt("Password", hide_input=True)
    success, login_message, token = _login(api_url, username, password)
    if not success:
        click.echo(red(login_message, "bold"))
        click.echo(white("You can retry with: astro init", "normal"))
        raise SystemExit(1)

    persist_token(token)
    click.echo(green(login_message, "bold"))

    signed_in_as = username
    try:
        me = httpx.get(
            f"{api_url}/auth/user/me",
            headers={"X-API-KEY": token},
            timeout=10.0,
        )
        if me.status_code == 200:
            user = me.json().get("user", {})
            signed_in_as = user.get("username", username)
            click.echo(
                f"{cyan('Signed in as', 'bold')} {signed_in_as} "
                f"({user.get('role', 'user')})"
            )
    except httpx.HTTPError:
        pass

    permanent_user_created = False
    if signed_in_as == DEFAULT_STACK_USER:
        permanent_user_created = _setup_permanent_user(
            api_url,
            token,
            yes=yes,
            skip_create_user=skip_create_user,
            role=role,
        )

    _print_next_steps(logged_in=True, permanent_user_created=permanent_user_created)

def _print_next_steps(*, logged_in: bool, permanent_user_created: bool = False) -> None:
    click.echo("")
    click.echo(green("Setup complete", "bold"))
    click.echo(white("Config file:", "normal"), nl=False)
    click.echo(f" ~/.astro/config.json")
    click.echo("")
    click.echo(cyan("Next steps", "bold"))
    if not logged_in:
        click.echo(f"  {white('astro init', 'normal')}           — run setup again to log in")
    elif not permanent_user_created:
        click.echo(
            f"  {white('astro init', 'normal')}           — finish creating your permanent user"
        )
    click.echo(f"  {white('astro config show', 'normal')}    — view current CLI settings")
    if logged_in:
        click.echo(
            f"  {white('astro llms create', 'normal')}     — register an LLM "
            f"(required before agents)"
        )
        click.echo(
            f"  {white('astro agents create', 'normal')}  — create an agent "
            f"(after you have an LLM)"
        )
        click.echo(f"  {white('astro llms list', 'normal')}        — list configured LLMs")
        click.echo(f"  {white('astro agents list', 'normal')}      — list agents")
    click.echo(f"  {white('astro --help', 'normal')}          — all commands")
