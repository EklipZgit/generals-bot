"""Offline server-routing checks across current, external, and historical bots."""
import argparse
import ast
import contextlib
import io
import os
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(slots=True, frozen=True)
class BotSource:
    """Source files comprising one independently runnable bot checkout."""

    root: Path
    entrypoint: Path
    client: Path
    bridge: Path | None
    protocol: int


class ServerResolver(Protocol):
    """The shared server-selection contract implemented by each standalone client."""

    __slots__ = ()

    def __call__(self, server: str | None = None, public_server: bool = False) -> str:
        """Resolve explicit selection or a legacy public-server flag."""
        ...


class EndpointResolver(Protocol):
    """Transport-specific endpoint builder, without creating a connection."""

    __slots__ = ()

    def __call__(self, server: str, transport: str = 'websocket') -> str:
        """Return an endpoint for a validated server selection."""
        ...


@dataclass(slots=True)
class SelectedServerState:
    """Minimal state needed to execute constructor routing without running the client."""

    server: str = 'unresolved'


@dataclass(slots=True, frozen=True)
class DirectConnection:
    """Record custom connection arguments without opening a socket."""

    url: str
    user_id: str
    username: str
    bot_key: str | None


@dataclass(slots=True)
class CustomConnectionState:
    """Only the fields used by the explicit custom-URL connection branch."""

    server: str
    bot_key: str | None
    _ws: DirectConnection | None = None


def record_direct_connection(
    server_url: str,
    user_id: str,
    username: str,
    bot_key: str | None,
) -> DirectConnection:
    """Replace the custom connection factory with a strictly offline argument record."""
    return DirectConnection(server_url, user_id, username, bot_key)


def bot_sources() -> list[BotSource]:
    """Find installed checkouts through the launcher's shared machine configuration."""
    sources = [BotSource(
        REPO_ROOT, REPO_ROOT / 'BotHost.py',
        REPO_ROOT / 'base/client/generals.py', REPO_ROOT / 'base/bot_base.py', 4)]
    config_path = REPO_ROOT.parent / 'run_config.txt'
    if not config_path.is_file():
        return sources
    config: dict[str, str] = {}
    for line in config_path.read_text(encoding='utf-8-sig').splitlines():
        key, separator, value = line.partition('=')
        if separator and not key.lstrip().startswith('#'):
            config[key.strip()] = value.strip()
    if 'sora_bot_path' in config:
        root = Path(config['sora_bot_path']).parent
        sources.append(BotSource(root, root / 'run_bot.py', root / 'generals.py', None, 4))
    if 'blob_bot_path' in config:
        root = Path(config['blob_bot_path']).parent
        sources.append(BotSource(
            root, root / 'startup.py', root / 'base/client/generals.py',
            root / 'base/bot_base.py', 4))
    if 'historical_bots_root' in config:
        for root in sorted(Path(config['historical_bots_root']).glob('generals-bot-*')):
            entrypoint = root / 'startup.py'
            if not entrypoint.is_file():
                entrypoint = root / 'BotHost.py'
            sources.append(BotSource(
                root, entrypoint, root / 'base/client/generals.py',
                root / 'base/bot_base.py', 3 if root.name < 'generals-bot-2023' else 4))
    return sources


def source_tree(path: Path) -> ast.Module:
    """Parse a bot source file without importing it or starting any runtime work."""
    return ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))


def parser_from_source(path: Path) -> argparse.ArgumentParser:
    """Execute only parser declarations, excluding imports, game startup, and I/O."""
    statements: list[ast.stmt] = []
    for node in sorted(ast.walk(source_tree(path)), key=lambda item: item.lineno if isinstance(item, ast.stmt) else -1):
        if not isinstance(node, (ast.Assign, ast.Expr)):
            continue
        value = node.value
        if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Attribute):
            continue
        if value.func.attr in ('ArgumentParser', 'add_mutually_exclusive_group', 'add_argument'):
            statements.append(node)
    namespace: dict[str, object] = {'argparse': argparse, 'os': os, 'botName': 'ParserTest'}
    exec(compile(ast.Module(body=statements, type_ignores=[]), str(path), 'exec'), namespace)
    return cast(argparse.ArgumentParser, namespace['parser'])


class ServerSelectionTests(unittest.TestCase):
    """Exercise configuration and inspect the complete CLI-to-client argument chain."""

    __slots__ = ()

    def test_every_parser_accepts_server_and_defaults_to_bot(self) -> None:
        """Every standalone entrypoint must accept the same explicit server choices."""
        for source in bot_sources():
            with self.subTest(bot=source.root.name):
                parser = parser_from_source(source.entrypoint)
                self.assertEqual(vars(parser.parse_args([]))['server'], 'bot')
                for server in ('local', 'bot', 'na'):
                    for flag in ('-server', '--server'):
                        self.assertEqual(vars(parser.parse_args([flag, server]))['server'], server)
                self.assertEqual(vars(parser.parse_args(['--public']))['server'], 'na')
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        parser.parse_args(['-server', 'invalid'])
                    with self.assertRaises(SystemExit):
                        parser.parse_args(['-server', 'local', '--public'])

    def test_blob_and_path_entrypoints_use_the_shared_parameterized_startup(self) -> None:
        """Both Purd strategies must delegate CLI parsing to the updated startup module."""
        for source in bot_sources():
            if source.root.name != 'generals-blob-and-path':
                continue
            for filename in ('bot_blob.py', 'bot_path_collect.py'):
                with self.subTest(entrypoint=filename):
                    calls = [
                        node for node in ast.walk(source_tree(source.root / filename))
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == 'startup'
                        and node.func.attr == 'startup']
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(len(calls[0].args), 2)

    def test_clients_select_endpoints_without_mutating_global_state(self) -> None:
        """Each connection must independently select both websocket and polling origins."""
        for source in bot_sources():
            with self.subTest(bot=source.root.name):
                tree = source_tree(source.client)
                definitions = [
                    node for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name in ('resolve_server', 'get_server_endpoint')]
                self.assertEqual(len(definitions), 2, 'missing explicit server-routing functions')
                namespace: dict[str, object] = {}
                exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source.client), 'exec'), namespace)
                resolve = cast(ServerResolver, namespace['resolve_server'])
                endpoint = cast(EndpointResolver, namespace['get_server_endpoint'])
                self.assertEqual(resolve(None), 'bot')
                self.assertEqual(resolve(None, True), 'na')
                self.assertEqual(resolve('local', True), 'local')
                self.assertEqual(resolve('bot', True), 'bot')
                origins = [('local', 'localhost:8080'), ('bot', 'botws.generals.io'), ('na', 'ws.generals.io')]
                for server, host in origins * 2:
                    self.assertEqual(resolve(server), server)
                    ws_scheme = 'ws' if server == 'local' else 'wss'
                    http_scheme = 'http' if server == 'local' else 'https'
                    suffix = f'/socket.io/?EIO={source.protocol}'
                    self.assertEqual(endpoint(server), f'{ws_scheme}://{host}{suffix}&transport=websocket')
                    self.assertEqual(
                        endpoint(server, 'polling'),
                        f'{http_scheme}://{host}{suffix}&transport=polling')
                with self.assertRaises(ValueError):
                    resolve('invalid')
                with self.assertRaises(ValueError):
                    endpoint('invalid')
                with self.assertRaises(ValueError):
                    endpoint('bot', 'invalid')

    def test_constructors_resolve_public_authentication_before_connecting(self) -> None:
        """Explicit selection, not an old public boolean, must drive connection identity."""
        for source in bot_sources():
            with self.subTest(bot=source.root.name):
                tree = source_tree(source.client)
                resolver = next(
                    node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == 'resolve_server')
                owner = next(
                    node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name in ('Generals', 'GeneralsClient'))
                constructor = next(
                    node for node in owner.body
                    if isinstance(node, ast.FunctionDef) and node.name == '__init__')
                routing = ast.Module(body=[resolver] + constructor.body[:2], type_ignores=[])
                for selected, legacy_public, expected in [
                    (None, False, 'bot'), (None, True, 'na'),
                    ('local', True, 'local'), ('bot', True, 'bot'), ('na', False, 'na'),
                ]:
                    state = SelectedServerState()
                    namespace: dict[str, object] = {
                        'self': state, 'server': selected, 'public_server': legacy_public}
                    exec(compile(routing, str(source.client), 'exec'), namespace)
                    self.assertEqual(state.server, expected)
                    self.assertEqual(namespace['public_server'], expected == 'na')

    def test_explicit_custom_url_takes_precedence_for_sora_and_blob_path(self) -> None:
        """Their existing tournament/custom transport must bypass the standard endpoints."""
        checked = 0
        for source in bot_sources():
            if source.root.name not in ('Sora_AI', 'generals-blob-and-path'):
                continue
            with self.subTest(bot=source.root.name):
                owner = next(
                    node for node in source_tree(source.client).body
                    if isinstance(node, ast.ClassDef) and node.name == 'Generals')
                constructor = next(
                    node for node in owner.body
                    if isinstance(node, ast.FunctionDef) and node.name == '__init__')
                branch = next(
                    node for node in constructor.body
                    if isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                    and isinstance(node.test.left, ast.Name) and node.test.left.id == 'server_url')
                for server in ('local', 'bot', 'na'):
                    state = CustomConnectionState(server=server, bot_key=None)
                    namespace: dict[str, object] = {
                        'self': state, 'server_url': 'ws://custom.invalid/socket',
                        'userid': 'offline-id', 'username': 'OfflineBot',
                        'connect_direct': record_direct_connection}
                    # No networking imports exist in this namespace; a fallback cannot connect.
                    exec(compile(ast.Module(body=[branch], type_ignores=[]), str(source.client), 'exec'), namespace)
                    self.assertEqual(
                        state._ws, DirectConnection('ws://custom.invalid/socket', 'offline-id', 'OfflineBot', None))
                checked += 1
        installed = [source for source in bot_sources() if source.root.name in ('Sora_AI', 'generals-blob-and-path')]
        self.assertEqual(checked, len(installed))

    def test_server_reaches_every_client_constructor_including_rejoins(self) -> None:
        """Bridge objects must retain the selection and forward it on every connection."""
        for source in bot_sources():
            with self.subTest(bot=source.root.name):
                client_classes = [
                    node for node in source_tree(source.client).body
                    if isinstance(node, ast.ClassDef) and node.name in ('Generals', 'GeneralsClient')]
                self.assertEqual(len(client_classes), 1)
                constructor = next(
                    node for node in client_classes[0].body
                    if isinstance(node, ast.FunctionDef) and node.name == '__init__')
                self.assertIn('server', [argument.arg for argument in constructor.args.args])
                if source.bridge is None:
                    continue
                bridge = source_tree(source.bridge)
                calls = [
                    node for node in ast.walk(bridge)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == 'generals'
                    and node.func.attr in ('Generals', 'GeneralsClient')]
                self.assertGreater(len(calls), 0)
                for call in calls:
                    self.assertIn('server', [keyword.arg for keyword in call.keywords])

    def test_entrypoints_forward_selection_into_the_runtime(self) -> None:
        """Accepting a flag is insufficient: startup/host calls must propagate it."""
        for source in bot_sources():
            with self.subTest(bot=source.root.name):
                tree = source_tree(source.entrypoint)
                for owner in tree.body:
                    if isinstance(owner, ast.ClassDef) and owner.name == 'BotHostLiveServer':
                        constructor = next(
                            node for node in owner.body
                            if isinstance(node, ast.FunctionDef) and node.name == '__init__')
                        self.assertIn('server', [argument.arg for argument in constructor.args.args])
                calls = [
                    node for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr in ('GeneralsBot', 'GeneralsClientHost')
                        or isinstance(node.func, ast.Name)
                        and node.func.id in ('run_bothost', 'BotHostLiveServer', 'Generals', 'start_game'))]
                self.assertGreater(len(calls), 0)
                explicit_calls = [
                    node for node in calls
                    if any(keyword.arg == 'server' for keyword in node.keywords)]
                self.assertGreater(len(explicit_calls), 0, 'server selection is parsed but never forwarded')
