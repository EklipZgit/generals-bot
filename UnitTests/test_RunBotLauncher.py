"""Regression tests for run-bot.ps1 launcher path validation and temp script lifecycle.

Each test spawns an isolated pwsh subprocess that loads only the function
definitions from the real run-bot.ps1 via the PowerShell AST parser, so the real
run_config.txt, real bot paths, real log folders, and the user-owned
block_bot.txt are never read or touched and no bot interpreter or game process
is ever launched (Start-Process is stubbed to inspect the generated script).
All filesystem fixtures are generated fresh per test via tempfile.mkdtemp under
C:\\cascade-debug-output\\generals-bot and left on disk as evidence.
"""
import ast
import os
import re
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass

import logbook


_LOG = logbook.Logger('RunBotLauncherTests')

REPO_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_BOT_PS1: str = os.path.normpath(os.path.join(REPO_ROOT, 'run-bot.ps1'))

# Sanctioned per-project debug output area; every test gets a unique child dir.
OUTPUT_BASE: str = r'C:\cascade-debug-output\generals-bot'

# Every (version folder, entrypoint) pair referenced by Get-HistoricalBotPath calls
# inside run-bot.ps1.
HISTORICAL_ENTRYPOINTS: list[tuple[str, str]] = [
    ('generals-bot-2023-07-24', 'bot_ek0x45.py'),
    ('generals-bot-2023-07-29', 'bot_ek0x45.py'),
    ('generals-bot-2023-07-31', 'bot_ek0x45.py'),
    ('generals-bot-2023-08-04', 'BotHost.py'),
    ('generals-bot-2023-08-07', 'BotHost.py'),
    ('generals-bot-2023-08-08', 'BotHost.py'),
    ('generals-bot-2023-08-26', 'BotHost.py'),
    ('generals-bot-2023-09-15', 'BotHost.py'),
    ('generals-bot-2023-10-23', 'BotHost.py'),
]

_MARKER_PATTERN: re.Pattern[str] = re.compile(r'^[A-Z_0-9]+$')
_GUID_STEM_PATTERN: re.Pattern[str] = re.compile(r'^[0-9a-f]{32}$')

# External blob/path bot viewer source; a local machine path outside the repo.
BLOB_PATH_VIEWER: str = r'C:\old-bots\generals-blob-and-path\base\viewer.py'


@dataclass(slots=True)
class PwshResult:
    """Captured output of a single isolated pwsh subprocess invocation."""
    returncode: int
    stdout: str
    stderr: str


def _ps_literal(value: str) -> str:
    """Quotes a string as a PowerShell single-quoted literal.

    :param value: Raw string to embed in a pwsh payload.
    :return: Single-quoted, escaped PowerShell literal.
    """
    return "'" + value.replace("'", "''") + "'"


class RunBotLauncherTests(unittest.TestCase):
    """Regression tests driving run-bot.ps1 functions through isolated pwsh subprocesses."""

    __slots__ = ()

    # Per-test fixture paths assigned by setUp under a unique mkdtemp root.
    fixture_root: str
    temp_with_spaces: str
    expected_temp_root: str
    hist_root: str
    fake_repo: str
    log_dir: str
    grouped_dir: str
    fake_bot_path: str
    missing_bot_path: str
    missing_hist_root: str
    sora_bot: str
    blob_bot: str
    path_bot: str
    fixture_config_path: str
    order_temp_dir: str

    @classmethod
    def setUpClass(cls) -> None:
        """Pushes a logbook stream handler so test diagnostics reach stdout."""
        cls._log_handler = logbook.StreamHandler(sys.stdout)
        cls._log_handler.push_application()

    @classmethod
    def tearDownClass(cls) -> None:
        """Pops the logbook stream handler installed by setUpClass."""
        cls._log_handler.pop_application()

    def setUp(self) -> None:
        """Builds a fresh isolated fixture tree under the debug output root.

        Nothing is ever deleted: fixture trees are left in place as evidence.
        """
        self.fixture_root = tempfile.mkdtemp(prefix='run_bot_launcher_', dir=OUTPUT_BASE)
        self.temp_with_spaces = os.path.join(self.fixture_root, 'temp with spaces')
        self.expected_temp_root = os.path.join(self.temp_with_spaces, 'generals-bot', 'run-bot')
        self.hist_root = os.path.join(self.fixture_root, 'historical bots')
        self.fake_repo = os.path.join(self.fixture_root, 'fake-repo')
        self.log_dir = os.path.join(self.fixture_root, 'logs')
        self.grouped_dir = os.path.join(self.fixture_root, 'grouped')
        self.fake_bot_path = os.path.join(self.fixture_root, 'bots', 'fake_bot.py')
        self.missing_bot_path = os.path.join(self.fixture_root, 'bots', 'missing_bot.py')
        self.missing_hist_root = os.path.join(self.fixture_root, 'missing-hist-root')
        self.sora_bot = os.path.join(self.fixture_root, 'external', 'sora_bot.py')
        self.blob_bot = os.path.join(self.fixture_root, 'external', 'blob_bot.py')
        self.path_bot = os.path.join(self.fixture_root, 'external', 'path_bot.py')
        self.fixture_config_path = os.path.join(self.fixture_root, 'run_config.txt')
        self.order_temp_dir = os.path.join(self.fixture_root, 'order-temp')

        os.makedirs(self.temp_with_spaces)
        os.makedirs(self.fake_repo)
        os.makedirs(os.path.dirname(self.fake_bot_path))
        os.makedirs(os.path.dirname(self.sora_bot))
        for entrypoint in (self.fake_bot_path, self.sora_bot, self.blob_bot, self.path_bot,
                           os.path.join(self.fake_repo, 'BotHost.py')):
            with open(entrypoint, 'w', encoding='utf-8') as file_handle:
                file_handle.write('# fixture bot entrypoint, never executed\n')
        for version_folder, bot_file in HISTORICAL_ENTRYPOINTS:
            version_dir = os.path.join(self.hist_root, version_folder)
            os.makedirs(version_dir)
            with open(os.path.join(version_dir, bot_file), 'w', encoding='utf-8') as file_handle:
                file_handle.write('# fixture historical bot entrypoint, never executed\n')
        _LOG.info('fixture root: {}', self.fixture_root)

    def _run_pwsh(self, script: str) -> PwshResult:
        """Runs the given script under pwsh -NoProfile -NonInteractive -Command.

        :param script: PowerShell source executed as the -Command payload.
        :return: Captured return code and stream text.
        """
        proc = subprocess.run(
            ['pwsh', '-NoProfile', '-NonInteractive', '-Command', script],
            capture_output=True,
            text=True,
            timeout=180)
        result = PwshResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
        _LOG.info('pwsh rc={}\nstdout:\n{}\nstderr:\n{}', result.returncode, result.stdout, result.stderr)
        # Marker-based assertions rely on the payload ending cleanly; a nonzero exit
        # means an uncaught error escaped and must fail loudly rather than hide.
        self.assertEqual(result.returncode, 0, f'pwsh exited {result.returncode}: {result.stderr}')
        return result

    def _markers(self, result: PwshResult) -> dict[str, list[str]]:
        """Parses `KEY|value` marker lines from pwsh stdout into a lookup.

        :param result: Completed pwsh subprocess result.
        :return: Mapping of uppercase marker key to all emitted values.
        """
        markers: dict[str, list[str]] = {}
        for line in result.stdout.splitlines():
            key, separator, value = line.partition('|')
            if separator and _MARKER_PATTERN.fullmatch(key.strip()):
                markers.setdefault(key.strip(), []).append(value.strip())
        return markers

    def _load_functions_prelude(self) -> str:
        """Builds a pwsh prelude loading only run-bot.ps1 function definitions.

        The real script is parsed with the PowerShell AST parser and each
        top-level function is defined via Invoke-Expression, so the script's
        top-level Initialize-RunConfig call (and hence the real run_config.txt)
        never runs. The script-level state the functions read is set manually
        to per-test fixture values. A Get-RunConfigFilePath override is needed
        because AST-loaded functions have an empty $PSScriptRoot which would
        make Join-Path throw. Test-Path/Get-Content are overridden only for
        the 'block_bot.txt' leaf so the user-owned real file is never touched
        and the suite behaves identically whether or not bots are blocked.
        """
        return f"""
$scriptTokens = $null
$scriptParseErrors = $null
$scriptAst = [System.Management.Automation.Language.Parser]::ParseFile({_ps_literal(RUN_BOT_PS1)}, [ref]$scriptTokens, [ref]$scriptParseErrors)
foreach ($definition in $scriptAst.EndBlock.Statements) {{
    if ($definition -is [System.Management.Automation.Language.FunctionDefinitionAst]) {{
        Invoke-Expression $definition.Extent.Text
    }}
}}
$Script:RunConfig = @{{
    repo_root = {_ps_literal(self.fake_repo)}
    log_folder = {_ps_literal(self.log_dir)}
    grouped_folder = {_ps_literal(self.grouped_dir)}
    historical_bots_root = {_ps_literal(self.hist_root)}
    sora_bot_path = {_ps_literal(self.sora_bot)}
    blob_bot_path = {_ps_literal(self.blob_bot)}
    path_bot_path = {_ps_literal(self.path_bot)}
    current_gen_python_path = 'python3.14.exe'
    legacy_python_path = 'python3.14.exe'
}}
$Script:CheapBotCpuAffinityMask = [IntPtr]0x10000
function Get-RunConfigFilePath {{ return {_ps_literal(self.fixture_config_path)} }}
function Get-CurrentGenPythonPath {{ return 'python3.14.exe' }}
function Get-LegacyPythonPath {{ return 'python3.14.exe' }}
function Test-Path {{
    param(
        [string[]]$Path,
        [string[]]$LiteralPath,
        [string]$PathType
    )
    $targetPath = $Path
    if ($PSBoundParameters.ContainsKey('LiteralPath')) {{
        $targetPath = $LiteralPath
    }}
    if ([IO.Path]::GetFileName(($targetPath | Select-Object -First 1)) -eq 'block_bot.txt') {{
        return $true
    }}
    Microsoft.PowerShell.Management\\Test-Path @PSBoundParameters
}}
function Get-Content {{
    param(
        [string[]]$Path,
        [string[]]$LiteralPath,
        [switch]$Raw
    )
    $targetPath = $Path
    if ($PSBoundParameters.ContainsKey('LiteralPath')) {{
        $targetPath = $LiteralPath
    }}
    if ([IO.Path]::GetFileName(($targetPath | Select-Object -First 1)) -eq 'block_bot.txt') {{
        return 'False'
    }}
    Microsoft.PowerShell.Management\\Get-Content @PSBoundParameters
}}
"""

    def _temp_launch_script(self, simulate_played: bool) -> str:
        """Builds a pwsh payload that runs Run-BotOnce with all launch effects stubbed.

        Redirects TMP/TEMP to a fixture dir containing spaces before .NET
        GetTempPath is read, and stubs Start-Process so the generated script is
        inspected but never executed.

        :param simulate_played: When True the stubbed Start-Process creates the
            matching .played marker so Run-BotOnce should return True.
        :return: Full PowerShell test payload.
        """
        played_flag = '$true' if simulate_played else '$false'
        return f"""
$env:TMP = {_ps_literal(self.temp_with_spaces)}
$env:TEMP = $env:TMP
{self._load_functions_prelude()}
# Stub markers are buffered because anything Write-Output emits inside the
# Start-Process stub becomes part of Run-BotOnce's return value.
$global:Markers = [System.Collections.ArrayList]::new()
function Get-BotUserIdForName {{ param($Name) return $null }}
function Start-Process {{
    param($FilePath, $ArgumentList, [switch]$Wait, [switch]$NoNewWindow, [switch]$PassThru)
    $argLine = ($ArgumentList -join ' ')
    [void]$global:Markers.Add("SPAWN|$FilePath|$argLine")
    if ($argLine -match '-File\\s+"([^"]+\\.ps1)"') {{
        $scriptPath = $Matches[1]
        $global:LastPs1 = $scriptPath
        $global:LastPlayed = $scriptPath -replace '\\.ps1$', '.played'
        [void]$global:Markers.Add("SCRIPT_PATH|$scriptPath")
        $parseTokens = $null
        $parseErrors = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$parseTokens, [ref]$parseErrors)
        [void]$global:Markers.Add("PARSE_ERRORS|$($parseErrors.Count)")
        $scriptContent = Get-Content -LiteralPath $scriptPath -Raw
        [void]$global:Markers.Add("HAS_NOUI|$($scriptContent.Contains('--no-ui'))")
        [void]$global:Markers.Add("HAS_NOLOG|$($scriptContent.Contains('--no-log'))")
        [void]$global:Markers.Add("HAS_NOTEXTLOG|$($scriptContent.Contains('--no-text-log'))")
        [void]$global:Markers.Add("HAS_ROOMID_FLAG|$($scriptContent.Contains('-roomID'))")
        [void]$global:Markers.Add("HAS_ROOMID_VALUE|$($scriptContent.Contains('room99'))")
        [void]$global:Markers.Add("HAS_PRIVATE|$($scriptContent -match "-g', 'private'")")
        [void]$global:Markers.Add("HAS_CPU_MASK|$($scriptContent.Contains('[IntPtr]::new(16)'))")
        [void]$global:Markers.Add("HAS_BOT_PATH|$($scriptContent.Contains('fake_bot.py'))")
        if ($scriptContent -match "Start-Process -FilePath '([^']+)'") {{
            [void]$global:Markers.Add("INTERP|$($Matches[1])")
        }}
        if ($global:SimulatePlayed) {{
            Set-Content -LiteralPath $global:LastPlayed -Value 'fakeReplayId'
        }}
    }}
    else {{
        [void]$global:Markers.Add("UNQUOTED_FILE_ARG|$argLine")
    }}
}}
$global:SimulatePlayed = {played_flag}
$result = Run-BotOnce -name 'LauncherTestBot' -game 'ffa' -path {_ps_literal(self.fake_bot_path)} -noui -nolog -noTextLog -privateGame -roomID 'room99' -cpuAffinityMask '4'
foreach ($marker in $global:Markers) {{ Write-Output $marker }}
Write-Output "RESULT|$result"
Write-Output "LEFTOVER_PS1|$(if ($global:LastPs1) {{ Test-Path -LiteralPath $global:LastPs1 }} else {{ 'Unknown' }})"
Write-Output "LEFTOVER_PLAYED|$(if ($global:LastPlayed) {{ Test-Path -LiteralPath $global:LastPlayed }} else {{ 'Unknown' }})"
Write-Output "EFFECTIVE_TEMP|$([IO.Path]::GetTempPath())"
"""

    def _assert_launch_markers(self, markers: dict[str, list[str]], expected_result: str) -> None:
        """Asserts the shared invariants of a stubbed Run-BotOnce launch.

        :param markers: Parsed marker output from a temp-launch pwsh payload.
        :param expected_result: Expected stringified boolean returned by Run-BotOnce.
        """
        self.assertIn('SPAWN', markers, 'stubbed Start-Process was never invoked')
        spawn = markers['SPAWN'][0]
        spawn_parts = spawn.split('|')
        self.assertIn(spawn_parts[0], ('Powershell', 'pwsh'))
        quoted_match = re.search(r'-File\s+"([^"]+\.ps1)"', spawn_parts[1])
        self.assertIsNotNone(quoted_match, f'-File script argument was not properly quoted: {spawn_parts[1]}')
        self.assertNotIn('UNQUOTED_FILE_ARG', markers)

        script_path = markers['SCRIPT_PATH'][0]
        script_dir = os.path.normcase(os.path.normpath(os.path.dirname(script_path)))
        self.assertEqual(script_dir, os.path.normcase(os.path.normpath(self.expected_temp_root)))
        script_stem, script_ext = os.path.splitext(os.path.basename(script_path))
        self.assertEqual(script_ext, '.ps1')
        self.assertTrue(_GUID_STEM_PATTERN.fullmatch(script_stem), f'temp script name is not a GUID: {script_stem}')

        self.assertEqual(markers.get('PARSE_ERRORS', ['1'])[0], '0', 'generated script failed PowerShell parsing')
        self.assertEqual(markers.get('INTERP', [''])[0], 'python3.14.exe')
        for flag in ('HAS_NOUI', 'HAS_NOLOG', 'HAS_NOTEXTLOG', 'HAS_ROOMID_FLAG', 'HAS_ROOMID_VALUE', 'HAS_PRIVATE', 'HAS_CPU_MASK', 'HAS_BOT_PATH'):
            self.assertEqual(markers.get(flag, ['missing'])[0], 'True', f'generated script missing expected content for {flag}')

        self.assertEqual(markers.get('RESULT', [''])[0], expected_result)
        self.assertEqual(markers.get('LEFTOVER_PS1', ['True'])[0], 'False', 'generated .ps1 was not cleaned up')
        self.assertEqual(markers.get('LEFTOVER_PLAYED', ['True'])[0], 'False', '.played marker was not cleaned up')
        self.assertEqual(
            os.path.normcase(os.path.normpath(markers.get('EFFECTIVE_TEMP', [''])[0])),
            os.path.normcase(os.path.normpath(self.temp_with_spaces + os.sep)))

    def test_missing_historical_bots_root_throws_config_error(self) -> None:
        """historical_bots_root pointing at a missing dir must throw naming config/key/path."""
        script = f"""
{self._load_functions_prelude()}
$Script:RunConfig['historical_bots_root'] = {_ps_literal(self.missing_hist_root)}
try {{
    Get-HistoricalBotsRoot
    Write-Output 'NO_THROW'
}} catch {{
    Write-Output "THREW|$($_.Exception.Message)"
}}
"""
        result = self._run_pwsh(script)
        markers = self._markers(result)
        self.assertNotIn('NO_THROW', markers, 'Get-HistoricalBotsRoot returned without validating the configured root')
        threw = markers.get('THREW', [''])[0]
        self.assertIn('historical_bots_root', threw)
        self.assertIn('run_config.txt', threw)
        self.assertIn(self.missing_hist_root, threw)

    def test_get_historical_bot_path_resolves_existing_entrypoint(self) -> None:
        """The configured historical root must resolve to a real bot entrypoint file."""
        script = f"""
{self._load_functions_prelude()}
try {{
    $p = Get-HistoricalBotPath -VersionFolder 'generals-bot-2023-08-26' -BotFile 'BotHost.py'
    Write-Output "PATH|$p"
    Write-Output "EXISTS|$(Test-Path -LiteralPath $p -PathType Leaf)"
}} catch {{
    Write-Output "THREW|$($_.Exception.Message)"
}}
"""
        result = self._run_pwsh(script)
        markers = self._markers(result)
        self.assertNotIn('THREW', markers, f'Get-HistoricalBotPath threw: {markers.get("THREW")}')
        self.assertEqual(
            os.path.normcase(os.path.normpath(markers.get('PATH', [''])[0])),
            os.path.normcase(os.path.normpath(os.path.join(self.hist_root, 'generals-bot-2023-08-26', 'BotHost.py'))))
        self.assertEqual(markers.get('EXISTS', ['False'])[0], 'True')

    def test_get_historical_bot_path_throws_for_missing_entrypoint(self) -> None:
        """A missing version/entrypoint under a valid root must throw naming all parts."""
        script = f"""
{self._load_functions_prelude()}
try {{
    Get-HistoricalBotPath -VersionFolder 'generals-bot-1999-01-01' -BotFile 'BotHost.py'
    Write-Output 'NO_THROW'
}} catch {{
    Write-Output "THREW|$($_.Exception.Message)"
}}
"""
        result = self._run_pwsh(script)
        markers = self._markers(result)
        self.assertNotIn('NO_THROW', markers, 'Get-HistoricalBotPath did not validate the joined entrypoint file')
        threw = markers.get('THREW', [''])[0]
        self.assertIn('historical_bots_root', threw)
        self.assertIn('generals-bot-1999-01-01', threw)
        self.assertIn('BotHost.py', threw)

    def test_all_configured_bot_entrypoint_paths_exist(self) -> None:
        """Every Get-HistoricalBotPath invocation and other configured bot path must exist."""
        pair_cases = '\n'.join(
            f"    Write-Output \"HIST_ENTRY|{version}/{bot}|$(Test-Path -LiteralPath (Get-HistoricalBotPath -VersionFolder '{version}' -BotFile '{bot}') -PathType Leaf)\""
            for version, bot in HISTORICAL_ENTRYPOINTS)
        script = f"""
{self._load_functions_prelude()}
Write-Output "HIST_ROOT|$(Get-HistoricalBotsRoot)"
{pair_cases}
Write-Output "OTHER_ENTRY|sora_bot_path|$(Test-Path -LiteralPath (Get-SoraBotPath) -PathType Leaf)"
Write-Output "OTHER_ENTRY|blob_bot_path|$(Test-Path -LiteralPath (Get-BlobBotPath) -PathType Leaf)"
Write-Output "OTHER_ENTRY|path_bot_path|$(Test-Path -LiteralPath (Get-PathBotPath) -PathType Leaf)"
Write-Output "OTHER_ENTRY|default_bot|$(Test-Path -LiteralPath (Join-Path (Get-ConfiguredRepoRoot) 'BotHost.py') -PathType Leaf)"
"""
        result = self._run_pwsh(script)
        markers = self._markers(result)
        self.assertEqual(
            os.path.normcase(os.path.normpath(markers.get('HIST_ROOT', [''])[0])),
            os.path.normcase(os.path.normpath(self.hist_root)))
        for entry in markers.get('HIST_ENTRY', []):
            name, _, exists = entry.rpartition('|')
            self.assertEqual(exists, 'True', f'configured historical entrypoint missing: {name}')
        self.assertEqual(len(markers.get('HIST_ENTRY', [])), len(HISTORICAL_ENTRYPOINTS))
        for entry in markers.get('OTHER_ENTRY', []):
            key, _, exists = entry.rpartition('|')
            self.assertEqual(exists, 'True', f'configured entrypoint missing: {key}')

    def test_run_botonce_invalid_path_throws_before_launcher_work(self) -> None:
        """A nonexistent -path must throw before userID lookup, block_bot, temp, or log work."""
        script = f"""
$env:TMP = {_ps_literal(self.order_temp_dir)}
$env:TEMP = $env:TMP
{self._load_functions_prelude()}
function Get-BotUserIdForName {{ param($Name) throw 'SENTINEL_USERID_LOOKUP' }}
try {{
    Run-BotOnce -name 'LauncherTestBot' -game 'ffa' -path {_ps_literal(self.missing_bot_path)}
    Write-Output 'NO_THROW'
}} catch {{
    Write-Output "THREW|$($_.Exception.Message)"
}}
Write-Output "LOGDIR_CREATED|$(Test-Path -LiteralPath {_ps_literal(self.log_dir)})"
Write-Output "TEMPDIR_CREATED|$(Test-Path -LiteralPath {_ps_literal(os.path.join(self.order_temp_dir, 'generals-bot'))})"
"""
        result = self._run_pwsh(script)
        markers = self._markers(result)
        self.assertNotIn('NO_THROW', markers)
        threw = markers.get('THREW', [''])[0]
        self.assertNotIn('SENTINEL_USERID_LOOKUP', threw, 'path validation ran after the userID lookup')
        self.assertIn(self.missing_bot_path, threw)
        self.assertEqual(markers.get('LOGDIR_CREATED', ['True'])[0], 'False', 'log folders were created before path validation')
        self.assertEqual(markers.get('TEMPDIR_CREATED', ['True'])[0], 'False', 'temp dir was created before path validation')

    def test_run_botonce_played_game_returns_true_and_cleans_temp_files(self) -> None:
        """A played launch returns True and removes its GUID temp script and marker."""
        result = self._run_pwsh(self._temp_launch_script(simulate_played=True))
        self._assert_launch_markers(self._markers(result), 'True')

    def test_run_botonce_unplayed_game_returns_false_and_cleans_temp_files(self) -> None:
        """An unplayed launch returns False and still removes its GUID temp script."""
        result = self._run_pwsh(self._temp_launch_script(simulate_played=False))
        self._assert_launch_markers(self._markers(result), 'False')

    def test_run_botonce_temp_scripts_use_unique_guid_names(self) -> None:
        """Back-to-back launches must generate distinct GUID-named temp scripts."""
        script = f"""
$env:TMP = {_ps_literal(self.temp_with_spaces)}
$env:TEMP = $env:TMP
{self._load_functions_prelude()}
function Get-BotUserIdForName {{ param($Name) return $null }}
$global:Markers = [System.Collections.ArrayList]::new()
function Start-Process {{
    param($FilePath, $ArgumentList, [switch]$Wait, [switch]$NoNewWindow, [switch]$PassThru)
    $argLine = ($ArgumentList -join ' ')
    if ($argLine -match '-File\\s+"([^"]+\\.ps1)"') {{
        [void]$global:Markers.Add("SCRIPT_PATH|$($Matches[1])")
    }}
}}
$null = Run-BotOnce -name 'LauncherTestBot' -game 'ffa' -path {_ps_literal(self.fake_bot_path)} -noui -nolog -noTextLog
$null = Run-BotOnce -name 'LauncherTestBot' -game 'ffa' -path {_ps_literal(self.fake_bot_path)} -noui -nolog -noTextLog
foreach ($marker in $global:Markers) {{ Write-Output $marker }}
$tempRoot = Join-Path (Join-Path ([IO.Path]::GetTempPath()) 'generals-bot') 'run-bot'
if (Test-Path -LiteralPath $tempRoot) {{
    Write-Output "TEMPFILE_COUNT|$(@(Get-ChildItem -LiteralPath $tempRoot).Count)"
}} else {{
    Write-Output 'TEMPFILE_COUNT|0'
}}
"""
        result = self._run_pwsh(script)
        markers = self._markers(result)
        script_paths = markers.get('SCRIPT_PATH', [])
        self.assertEqual(len(script_paths), 2)
        stems = {os.path.splitext(os.path.basename(p))[0] for p in script_paths}
        self.assertEqual(len(stems), 2, 'temp script names collided across launches')
        for stem in stems:
            self.assertTrue(_GUID_STEM_PATTERN.fullmatch(stem), f'temp script name is not a GUID: {stem}')
        self.assertEqual(markers.get('TEMPFILE_COUNT', ['1'])[0], '0', 'temp scripts were left behind')

    def test_run_botonce_spawn_failure_still_cleans_temp_files(self) -> None:
        """A Start-Process failure must propagate while still removing the temp script."""
        script = f"""
$env:TMP = {_ps_literal(self.temp_with_spaces)}
$env:TEMP = $env:TMP
{self._load_functions_prelude()}
function Get-BotUserIdForName {{ param($Name) return $null }}
function Start-Process {{
    param($FilePath, $ArgumentList, [switch]$Wait, [switch]$NoNewWindow, [switch]$PassThru)
    $argLine = ($ArgumentList -join ' ')
    if ($argLine -match '-File\\s+"([^"]+\\.ps1)"') {{
        $global:LastPs1 = $Matches[1]
    }}
    throw 'SENTINEL_SPAWN'
}}
try {{
    Run-BotOnce -name 'LauncherTestBot' -game 'ffa' -path {_ps_literal(self.fake_bot_path)} -noui -nolog -noTextLog
    Write-Output 'NO_THROW'
}} catch {{
    Write-Output "THREW|$($_.Exception.Message)"
}}
Write-Output "LEFTOVER_PS1|$(if ($global:LastPs1) {{ Test-Path -LiteralPath $global:LastPs1 }} else {{ 'Unknown' }})"
$tempRoot = Join-Path (Join-Path ([IO.Path]::GetTempPath()) 'generals-bot') 'run-bot'
if (Test-Path -LiteralPath $tempRoot) {{
    Write-Output "TEMPFILE_COUNT|$(@(Get-ChildItem -LiteralPath $tempRoot).Count)"
}} else {{
    Write-Output 'TEMPFILE_COUNT|0'
}}
"""
        result = self._run_pwsh(script)
        markers = self._markers(result)
        self.assertNotIn('NO_THROW', markers)
        self.assertIn('SENTINEL_SPAWN', markers.get('THREW', [''])[0])
        self.assertEqual(markers.get('LEFTOVER_PS1', ['True'])[0], 'False', 'generated .ps1 survived a failed spawn')
        self.assertEqual(markers.get('TEMPFILE_COUNT', ['1'])[0], '0', 'temp files were left behind after a failed spawn')

    def test_blob_and_path_default_to_headless_and_allow_explicit_viewer(self) -> None:
        """Run-Blob/Run-Path must default -noui on while honoring an explicit -noui:$false.

        Fleet callsites omit -noui; these bots should launch headless by default.
        Run-BotOnce is stubbed to record its bound parameters then throw a sentinel
        that breaks the helpers' infinite retry loop after one iteration; any other
        error is rethrown rather than swallowed.
        """
        script = f"""
{self._load_functions_prelude()}
$global:Markers = [System.Collections.ArrayList]::new()
function Run-BotOnce {{
    param($name, $game, [switch]$public, [switch]$right, $privateGame, $roomID, [switch]$noui, $path, $userID, [switch]$nolog, [switch]$noTextLog, [switch]$publicLobby, $cpuAffinityMask)
    $pairs = foreach ($kv in $PSBoundParameters.GetEnumerator()) {{ "$($kv.Key)=$($kv.Value)" }}
    [void]$global:Markers.Add("CALL|$($pairs -join ';')")
    throw 'SENTINEL_LOOP_BREAK'
}}
foreach ($helper in @('Run-Path', 'Run-Blob')) {{
    foreach ($nouiArg in @('omitted', 'on', 'off')) {{
        try {{
            if ($nouiArg -eq 'omitted') {{ & $helper }}
            elseif ($nouiArg -eq 'on') {{ & $helper -noui }}
            else {{ & $helper -noui:$false }}
        }} catch {{
            if ($_.Exception.Message -ne 'SENTINEL_LOOP_BREAK') {{ throw }}
        }}
    }}
}}
foreach ($marker in $global:Markers) {{ Write-Output $marker }}
"""
        result = self._run_pwsh(script)
        calls = [self._parse_call_marker(value) for value in self._markers(result).get('CALL', [])]
        self.assertEqual(len(calls), 6, f'expected 6 stubbed helper launches, got {calls}')
        expected_noui = ['True', 'True', 'False', 'True', 'True', 'False']
        for index, call in enumerate(calls):
            helper = 'Run-Path' if index < 3 else 'Run-Blob'
            expected_path = self.path_bot if helper == 'Run-Path' else self.blob_bot
            expected_name = 'PurdPath' if helper == 'Run-Path' else 'PurdBlob'
            self.assertEqual(call.get('noui'), expected_noui[index],
                             f'{helper} invocation {index} forwarded wrong noui value')
            self.assertEqual(call.get('path'), expected_path, f'{helper} forwarded wrong bot path')
            self.assertEqual(call.get('name'), expected_name, f'{helper} forwarded wrong name')
            self.assertEqual(call.get('game'), 'ffa', f'{helper} forwarded wrong game')
            self.assertEqual(call.get('cpuAffinityMask'), '65536',
                             f'{helper} did not forward the shared cheap-bot CPU affinity mask')
            self.assertEqual(call.get('nolog'), 'False', f'{helper} changed default nolog forwarding')
            self.assertEqual(call.get('noTextLog'), 'False', f'{helper} changed default noTextLog forwarding')
            self.assertEqual(call.get('public'), 'False', f'{helper} changed default public forwarding')

    @staticmethod
    def _parse_call_marker(value: str) -> dict[str, str]:
        """Parses a `key=value;key=value` parameter dump emitted by the Run-BotOnce stub.

        :param value: Marker payload after the CALL| prefix.
        :return: Mapping of bound parameter name to stringified value.
        """
        parameters: dict[str, str] = {}
        for pair in value.split(';'):
            key, separator, val = pair.partition('=')
            if separator:
                parameters[key] = val
        return parameters

    @unittest.skipUnless(os.path.isfile(BLOB_PATH_VIEWER), 'external blob/path viewer not installed')
    def test_blob_and_path_viewer_has_no_screenshot_writer(self) -> None:
        """The blob/path viewer must be display-only: no screenshot writer, dir, or thread.

        Pure source inspection (AST + compile); the viewer module and pygame are
        never imported so no window, network, or filesystem writes can occur.
        """
        with open(BLOB_PATH_VIEWER, 'rb') as file_handle:
            source = file_handle.read()
        compile(source, BLOB_PATH_VIEWER, 'exec')
        text = source.decode('utf-8', errors='replace')
        tree = ast.parse(text)

        self.assertNotIn('OtherGeneralsLogs', text, 'screenshot log directory constant still present')
        self.assertNotIn('_spawn', text, 'background writer thread spawn still present')
        self.assertNotIn('save_image', text, 'save_image method still present')
        function_names = {node.name for node in ast.walk(tree)
                          if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertNotIn('save_image', function_names)
        attribute_names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertNotIn('logDirectory', attribute_names)
        call_names = {self._dotted_name(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        self.assertNotIn('pygame.image.save', call_names, 'pygame.image.save call still present')
        self.assertNotIn('os.makedirs', call_names)
        self.assertNotIn('os.path.exists', call_names)
        self.assertIn('pygame.display.set_mode', call_names, 'on-screen rendering was removed')
        self.assertIn('pygame.display.flip', call_names, 'on-screen rendering was removed')

    @staticmethod
    def _dotted_name(node: ast.expr) -> str:
        """Builds a dotted name (e.g. 'pygame.image.save') from a Name/Attribute chain.

        :param node: AST expression to flatten.
        :return: Dotted name string, or '' for non-name expressions.
        """
        parts: list[str] = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return '.'.join(reversed(parts))


if __name__ == '__main__':
    unittest.main()
