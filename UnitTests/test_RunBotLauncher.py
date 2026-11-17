"""Regression tests for run-bot.ps1 launcher path validation and temp script lifecycle.

Each test spawns an isolated pwsh subprocess that loads only the function
definitions from the real run-bot.ps1 via the PowerShell AST parser. Launcher
tests use fixture config and paths, leaving real log folders and the user-owned
block_bot.txt untouched. One optional source-only viewer check reads the real
run_config.txt to locate the external blob/path viewer. No bot interpreter or
game process is launched: Start-Process is stubbed everywhere, and the
shutdown-log cleanup tests execute the real generated .ps1 child script
against synthetic stdout/stderr captures — in-process under pwsh, or under
powershell.exe through a wrapper for Windows PowerShell 5.1 coverage. All
filesystem fixtures are generated fresh per test via tempfile.mkdtemp under
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

HUMAN_LIVE_BOT_COMMANDS: list[str] = [
    'Run-Human -left -game 1v1 -sleepMax 600 -cpuAffinityMask P',
    'Run-Human -right -game ffa -sleepMax 120 -cpuAffinityMask P',
    'Run-Human -game team -right -sleepMax 5 -nolog -botServer -cpuAffinityMask 4',
    'Run-HumanTeammate -game team -right -sleepMax 60 -nolog -noui -cpuAffinityMask 6',
    'Run-Teammate -sleepMax 90 -left -nolog -cpuAffinityMask 8',
    'Run-Teammate -sleepMax 1 -left -roomID teammate -nolog -cpuAffinityMask 10',
]

NON_HUMAN_LIVE_BOT_COMMANDS: list[str] = [
    'run-blob -game 1v1 -sleepMax 120 -name "QueueT" -public -noui',
    'run-path -game 1v1 -sleepMax 120 -name "a98i40pwpfah" -public -noui',
    'run-SoraAlt -public -sleepMax 120',
]


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
        """Runs pwsh with terminating errors so path failures cannot look successful.

        :param script: PowerShell source executed as the -Command payload.
        :return: Captured return code and stream text.
        """
        # test_terminal_tabs_read_repo_and_alt_paths_from_config must fail on path errors.
        proc = subprocess.run(
            ['pwsh', '-NoProfile', '-NonInteractive', '-Command', "$ErrorActionPreference = 'Stop'\n" + script],
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

        Only AST-extracted function definitions are written to a fixture script
        and sourced, giving the functions a real $PSScriptRoot without running
        the launcher's top-level Initialize-RunConfig call. Script state and
        Get-RunConfigFilePath are set to per-test fixtures. Test-Path/Get-Content
        are overridden only for the 'block_bot.txt' leaf so the user-owned real
        file is never touched and tests behave identically with bots blocked.
        """
        return f"""
$scriptTokens = $null
$scriptParseErrors = $null
$scriptAst = [System.Management.Automation.Language.Parser]::ParseFile({_ps_literal(RUN_BOT_PS1)}, [ref]$scriptTokens, [ref]$scriptParseErrors)
if ($scriptParseErrors.Count -ne 0) {{ throw 'run-bot.ps1 has PowerShell parse errors.' }}
$functionDefinitions = foreach ($definition in $scriptAst.EndBlock.Statements) {{
    if ($definition -is [System.Management.Automation.Language.FunctionDefinitionAst]) {{
        $definition.Extent.Text
    }}
}}
# test_terminal_tabs_read_repo_and_alt_paths_from_config and
# test_all_configured_bot_entrypoint_paths_exist need a real script root,
# not the empty $PSScriptRoot produced by Invoke-Expression.
$functionPath = {_ps_literal(os.path.join(self.fixture_root, 'launcher-functions.ps1'))}
[IO.File]::WriteAllText($functionPath, [string]::Join([Environment]::NewLine, $functionDefinitions))
. $functionPath
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

    def _live_bot_launch_markers(self, arguments: str = '') -> dict[str, list[str]]:
        """Capture live-fleet tab selection without opening terminals, sleeping, or running bots."""
        script = f"""
{self._load_functions_prelude()}
function Start-RunBotWindowsTerminalTab {{
    param($WindowName, $Command, [switch]$LoadGameResultUtils)
    if ($LoadGameResultUtils) {{
        Write-Output "DEV_TAB|$WindowName"
    }} else {{
        Write-Output "LAUNCH|$Command"
    }}
}}
function Start-Sleep {{ param($Seconds) Write-Output "SLEEP|$Seconds" }}
try {{
    Start-WindowsTerminalLiveBots {arguments}
    Write-Output 'COMPLETED|True'
}} catch {{
    Write-Output "THREW|$($_.Exception.Message)"
}}
"""
        return self._markers(self._run_pwsh(script))

    def test_live_bots_default_launches_all_groups(self) -> None:
        """Omitting filters must retain all bot tabs and the shared development tab."""
        markers = self._live_bot_launch_markers()
        self.assertNotIn('THREW', markers)
        self.assertEqual(markers.get('LAUNCH'), HUMAN_LIVE_BOT_COMMANDS + NON_HUMAN_LIVE_BOT_COMMANDS)
        self.assertEqual(markers.get('DEV_TAB'), ['LiveBots'])
        self.assertEqual(markers.get('SLEEP'), ['3'])

    def test_live_bots_non_human_exe_only_excludes_human_and_team_bots(self) -> None:
        """NonHumanExeOnly must launch only Blob, Path, and Sora, not the current bot or its partners."""
        markers = self._live_bot_launch_markers('-NonHumanExeOnly')
        self.assertNotIn('THREW', markers)
        self.assertEqual(markers.get('LAUNCH'), NON_HUMAN_LIVE_BOT_COMMANDS)
        self.assertEqual(markers.get('DEV_TAB'), ['LiveBots'])

    def test_live_bots_only_human_exe_includes_all_team_bots(self) -> None:
        """OnlyHumanExe must include Human.exe 1v1/FFA and the full existing 2v2 partner group."""
        markers = self._live_bot_launch_markers('-OnlyHumanExe')
        self.assertNotIn('THREW', markers)
        self.assertEqual(markers.get('LAUNCH'), HUMAN_LIVE_BOT_COMMANDS)
        self.assertEqual(markers.get('DEV_TAB'), ['LiveBots'])

    def test_live_bots_rejects_conflicting_filters_before_opening_tabs(self) -> None:
        """Mutually exclusive filters must fail before opening even the development tab."""
        markers = self._live_bot_launch_markers('-NonHumanExeOnly -OnlyHumanExe')
        self.assertIn('THREW', markers)
        self.assertIn('NonHumanExeOnly', markers['THREW'][0])
        self.assertIn('OnlyHumanExe', markers['THREW'][0])
        self.assertNotIn('LAUNCH', markers)
        self.assertNotIn('DEV_TAB', markers)
        self.assertNotIn('SLEEP', markers)
        self.assertNotIn('COMPLETED', markers)

    def test_alt_tabs_use_configured_launcher_without_relative_imports(self) -> None:
        """Alternate tabs must rely on the shared config-based launcher import."""
        script = f"""
{self._load_functions_prelude()}
function Start-RunBotWindowsTerminalTab {{
    param($WindowName, $Command)
    Write-Output "WINDOW|$WindowName"
    Write-Output "LAUNCH|$Command"
}}
function Start-Sleep {{ param($Seconds) }}
Start-WindowsTerminalAltBots
"""
        markers = self._markers(self._run_pwsh(script))
        self.assertEqual(markers.get('WINDOW'), ['AltBots'] * 7)
        commands = markers.get('LAUNCH', [])
        self.assertEqual(len(commands), 7)
        self.assertEqual(commands[:6], [
            'Run-Blob -game ffa',
            'Run-Path -game ffa',
            'Run-Path -game 1v1 -SleepMax 60',
            'Run-Blob -game 1v1 -SleepMax 60',
            'Run-SoraAI -game ffa',
            'Run-SoraAI -game 1v1 -SleepMax 60',
        ])
        for command in commands:
            self.assertNotIn('run-bot.ps1', command)
        self.assertIn(
            os.path.join(self.hist_root, 'generals-bot-2023-07-24', 'bot_ek0x45.py'),
            commands[-1])

    def test_terminal_tabs_read_repo_and_alt_paths_from_config(self) -> None:
        """The config, not the current directory, must determine script and bot paths."""
        configured_repo = os.path.join(self.fixture_root, "configured repo's checkout")
        with open(self.fixture_config_path, 'w', encoding='utf-8') as file_handle:
            file_handle.write(
                '# Independent checkout and alternate-bot locations.\n'
                f'repo_root = {configured_repo}\n'
                f'sora_bot_path = {self.sora_bot}\n'
                f'blob_bot_path = {self.blob_bot}\n'
                f'path_bot_path = {self.path_bot}\n'
                f'historical_bots_root = {self.hist_root}\n')
        script = f"""
{self._load_functions_prelude()}
$Script:RunConfig = $null
function wt {{
    $encodedIndex = [Array]::IndexOf($args, '-EncodedCommand') + 1
    $decoded = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($args[$encodedIndex]))
    Write-Output "TAB_SCRIPT|$decoded"
    $parseTokens = $null
    $parseErrors = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput($decoded, [ref]$parseTokens, [ref]$parseErrors)
    Write-Output "PARSE_ERRORS|$($parseErrors.Count)"
}}
Start-RunBotWindowsTerminalTab -WindowName 'ConfigTest' -Command 'Run-Blob' -LoadGameResultUtils
Write-Output "SORA|$(Get-SoraBotPath)"
Write-Output "BLOB|$(Get-BlobBotPath)"
Write-Output "PATH|$(Get-PathBotPath)"
Write-Output "HISTORICAL|$(Get-HistoricalBotsRoot)"
"""
        markers = self._markers(self._run_pwsh(script))
        tab_script = markers['TAB_SCRIPT'][0]
        self.assertIn(f'Set-Location {_ps_literal(configured_repo)}', tab_script)
        self.assertIn(f". {_ps_literal(os.path.join(configured_repo, 'run-bot.ps1'))}", tab_script)
        self.assertIn(
            f". {_ps_literal(os.path.join(configured_repo, 'game-result-analysis-utils.ps1'))}",
            tab_script)
        self.assertNotIn(r'.\run-bot.ps1', tab_script)
        self.assertEqual(markers.get('PARSE_ERRORS'), ['0'])
        self.assertEqual(markers.get('SORA'), [self.sora_bot])
        self.assertEqual(markers.get('BLOB'), [self.blob_bot])
        self.assertEqual(markers.get('PATH'), [self.path_bot])
        self.assertEqual(markers.get('HISTORICAL'), [self.hist_root])

    def _temp_launch_script(self, simulate_played: bool, arguments: str = '') -> str:
        """Builds a pwsh payload that runs Run-BotOnce with all launch effects stubbed.

        Redirects TMP/TEMP to a fixture dir containing spaces before .NET
        GetTempPath is read, and stubs Start-Process so the generated script is
        inspected but never executed.

        :param simulate_played: When True the stubbed Start-Process creates the
            matching .played marker so Run-BotOnce should return True.
        :param arguments: Additional launcher arguments, including server selection.
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
        $serverMatch = [regex]::Match($scriptContent, "'-server', '(local|bot|na)'")
        [void]$global:Markers.Add("SERVER|$($serverMatch.Groups[1].Value)")
        [void]$global:Markers.Add("HAS_PUBLIC|$($scriptContent.Contains('--public'))")
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
$result = Run-BotOnce -name 'LauncherTestBot' -game 'ffa' -path {_ps_literal(self.fake_bot_path)} -noui -nolog -noTextLog -privateGame -roomID 'room99' -cpuAffinityMask '4' {arguments}
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

    def test_run_botonce_serializes_server_and_preserves_public_alias(self) -> None:
        """Serialize one canonical destination; explicit Server wins over legacy public."""
        for arguments, expected in [
            ('', 'bot'), ('-public', 'na'), ('-Server local', 'local'),
            ('-Server bot -public', 'bot'), ('-Server na', 'na'),
            ('-Server LOCAL', 'local'),
        ]:
            with self.subTest(arguments=arguments):
                markers = self._markers(self._run_pwsh(self._temp_launch_script(False, arguments)))
                self.assertEqual(markers.get('SERVER'), [expected])
                self.assertEqual(markers.get('HAS_PUBLIC'), ['False'])

    def test_all_run_helpers_forward_server_and_preserve_default_destinations(self) -> None:
        """Generic/alternate helpers retain bot defaults, Human helpers retain NA."""
        script = f"""
{self._load_functions_prelude()}
$Script:RunConfig['checkpoint_backup_root'] = {_ps_literal(os.path.join(self.fixture_root, 'checkpoints'))}
function Create-Checkpoint {{ param($backup) }}
function Run-BotOnce {{
    param($name, $game, [switch]$public, [switch]$right, $privateGame, $roomID,
          [switch]$noui, $path, $userID, [switch]$nolog, [switch]$noTextLog,
          [switch]$publicLobby, $cpuAffinityMask, [string]$Server)
    Write-Host "DESTINATION|$Server"
    throw 'SENTINEL_LOOP_BREAK'
}}
$helpers = @('Run-Bot', 'Run-BotCheckpoint', 'Run-Path', 'Run-Blob',
             'Run-SoraAI', 'Run-SoraAlt', 'Run-SoraAITeammate',
             'Run-Human', 'Run-HumanTeammate', 'Run-Teammate')
foreach ($helper in $helpers) {{
    foreach ($selection in @('default', 'local', 'bot', 'na', 'legacy', 'override')) {{
        $invokeArgs = @{{}}
        $parameters = (Get-Command $helper).Parameters
        if ($parameters.ContainsKey('game')) {{ $invokeArgs['game'] = @('1v1') }}
        if ($selection -in @('local', 'bot', 'na')) {{ $invokeArgs['Server'] = $selection }}
        if ($selection -in @('legacy', 'override')) {{
            if ($parameters.ContainsKey('botServer')) {{ $invokeArgs['botServer'] = $true }}
            else {{ $invokeArgs['public'] = $true }}
        }}
        if ($selection -eq 'override') {{ $invokeArgs['Server'] = 'local' }}
        Write-Output "CASE|$helper|$selection"
        try {{ & $helper @invokeArgs }} catch {{
            if ($_.Exception.Message -ne 'SENTINEL_LOOP_BREAK') {{ throw }}
        }}
    }}
}}
Write-Output 'CASES_COMPLETED|True'
"""
        markers = self._markers(self._run_pwsh(script))
        self.assertEqual(markers.get('CASES_COMPLETED'), ['True'])
        cases = markers.get('CASE', [])
        destinations = markers.get('DESTINATION', [])
        self.assertEqual(len(cases), 60)
        self.assertEqual(len(destinations), len(cases))
        human_helpers = ('Run-Human', 'Run-HumanTeammate', 'Run-Teammate')
        for case, destination in zip(cases, destinations):
            helper, selection = case.split('|')
            expected = selection
            if selection == 'default':
                expected = 'na' if helper in human_helpers else 'bot'
            elif selection == 'legacy':
                expected = 'bot' if helper in human_helpers else 'na'
            elif selection == 'override':
                expected = 'local'
            self.assertEqual(destination, expected, case)

    def test_invalid_server_is_rejected_before_launching_for_all_helpers_and_fleets(self) -> None:
        """Parameter validation must fail before bot processes, tabs, or copies can start."""
        script = f"""
{self._load_functions_prelude()}
function wt {{ throw 'UNEXPECTED_TERMINAL_LAUNCH' }}
function Start-Process {{ throw 'UNEXPECTED_PROCESS_LAUNCH' }}
function Start-Sleep {{ param($Seconds) }}
function Create-Checkpoint {{ throw 'UNEXPECTED_CHECKPOINT_COPY' }}
$helpers = @('Run-BotOnce', 'Run-Bot', 'Run-BotCheckpoint', 'Run-Path', 'Run-Blob',
             'Run-SoraAI', 'Run-SoraAlt', 'Run-SoraAITeammate',
             'Run-Human', 'Run-HumanTeammate', 'Run-Teammate',
             'Start-RunBotWindowsTerminalTab', 'Start-WindowsTerminalAltBots',
             'Start-WindowsTerminalHistoricalBots', 'Start-WindowsTerminalBigFfaBots',
             'Start-WindowsTerminalBigTeamBots', 'Start-WindowsTerminalLiveBots',
             'Start-WindowsTerminalBotServer2v2Bots', 'Start-WindowsTerminalBotServerLiveBots')
foreach ($helper in $helpers) {{
    $invokeArgs = @{{ Server = 'invalid' }}
    if ($helper -eq 'Start-RunBotWindowsTerminalTab') {{ $invokeArgs['WindowName'] = 'OfflineTest' }}
    try {{
        & $helper @invokeArgs
        throw 'INVALID_SERVER_ACCEPTED'
    }} catch {{
        # The concrete validation exception is internal; assert its public error ID instead.
        if ($_.FullyQualifiedErrorId -notlike 'ParameterArgumentValidationError,*') {{ throw }}
        Write-Output "INVALID_REJECTED|$helper"
    }}
}}
Write-Output 'CASES_COMPLETED|True'
"""
        markers = self._markers(self._run_pwsh(script))
        self.assertEqual(markers.get('CASES_COMPLETED'), ['True'])
        self.assertEqual(len(markers.get('INVALID_REJECTED', [])), 19)

    def test_all_fleets_forward_explicit_server_to_every_tab(self) -> None:
        """Every fleet can override its mixed historical defaults without dropping tabs."""
        script = f"""
{self._load_functions_prelude()}
function Start-Sleep {{ param($Seconds) }}
function Start-RunBotWindowsTerminalTab {{
    param($WindowName, $Command, [switch]$LoadGameResultUtils, $Server)
    Write-Output "FLEET_SERVER|$Server"
}}
foreach ($server in @('local', 'bot', 'na')) {{
    foreach ($fleet in @('Start-WindowsTerminalAltBots', 'Start-WindowsTerminalHistoricalBots',
                        'Start-WindowsTerminalBigFfaBots', 'Start-WindowsTerminalBigTeamBots',
                        'Start-WindowsTerminalLiveBots', 'Start-WindowsTerminalBotServer2v2Bots',
                        'Start-WindowsTerminalBotServerLiveBots')) {{
        & $fleet -Server $server
    }}
}}
"""
        markers = self._markers(self._run_pwsh(script))
        self.assertEqual(markers.get('FLEET_SERVER'), ['local'] * 80 + ['bot'] * 80 + ['na'] * 80)

    def test_terminal_tab_appends_server_override_to_legacy_commands(self) -> None:
        """Fleet overrides must survive command strings containing public/botServer aliases."""
        script = f"""
{self._load_functions_prelude()}
function wt {{
    $encodedIndex = [Array]::IndexOf($args, '-EncodedCommand') + 1
    $decoded = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($args[$encodedIndex]))
    Write-Output "TAB_SCRIPT|$decoded"
}}
Start-RunBotWindowsTerminalTab -WindowName 'Test' -Command 'Run-Human -botServer' -Server local
Start-RunBotWindowsTerminalTab -WindowName 'Test' -Command 'Run-Blob -public' -Server bot
"""
        scripts = self._markers(self._run_pwsh(script)).get('TAB_SCRIPT', [])
        self.assertEqual(len(scripts), 2)
        self.assertIn('Run-Human -botServer -Server local', scripts[0])
        self.assertIn('Run-Blob -public -Server bot', scripts[1])

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

    def test_blob_and_path_viewer_has_no_screenshot_writer(self) -> None:
        """The blob/path viewer must be display-only: no screenshot writer, dir, or thread.

        Pure source inspection (AST + compile); the viewer module and pygame are
        never imported so no window, network, or filesystem writes can occur.
        """
        config_path = os.path.normpath(os.path.join(REPO_ROOT, '..', 'run_config.txt'))
        if not os.path.isfile(config_path):
            self.skipTest('external blob/path viewer config not installed')
        # Follow blob_bot_path so moving the external checkout cannot silently skip this check.
        script = f"""
{self._load_functions_prelude()}
$Script:RunConfig = $null
function Get-RunConfigFilePath {{ return {_ps_literal(config_path)} }}
Write-Output "VIEWER|$(Join-Path (Split-Path (Get-BlobBotPath) -Parent) 'base\\viewer.py')"
"""
        viewer_path = self._markers(self._run_pwsh(script))['VIEWER'][0]
        if not os.path.isfile(viewer_path):
            self.skipTest(f'external blob/path viewer not installed at {viewer_path}')
        with open(viewer_path, 'rb') as file_handle:
            source = file_handle.read()
        compile(source, viewer_path, 'exec')
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

    # ------------------------------------------------------------------
    # Generated-child-script shutdown log cleanup tests. The Start-Process
    # stub executes the real generated .ps1 — in-process under pwsh, or under
    # powershell.exe via a wrapper script for Windows PowerShell 5.1 coverage —
    # against synthetic .stdout/.stderr captures; the inner python launch is
    # stubbed to write those captures and return $null, so no bot process
    # ever runs.
    # ------------------------------------------------------------------

    @staticmethod
    def _ps_nullable_literal(value: str | None) -> str:
        """Renders a string as a PowerShell literal, or ``$null`` for None.

        :param value: Text to embed in a pwsh payload.
        :return: PowerShell expression source.
        """
        if value is None:
            return '$null'
        return _ps_literal(value)

    @staticmethod
    def _capture_fixture_text(lines: list[str]) -> str:
        """Serializes synthetic capture lines with LF endings plus a trailing newline.

        :param lines: Exact lines the fake capture should contain.
        :return: Fixture file text.
        """
        return '\n'.join(lines) + '\n'

    def _write_capture_fixture(
        self,
        file_name: str,
        lines: list[str],
        *,
        bom: bool = False,
        encoding: str = 'utf-8',
    ) -> str:
        """Writes a synthetic bot capture fixture under the fixture root.

        :param file_name: File name inside fixture_root.
        :param lines: Exact capture lines; must be encodable with ``encoding``.
        :param bom: Prefix a UTF-8 BOM to mimic captures that carry one.
        :param encoding: Python codec for the fixture bytes. ``utf-8`` is the
            pwsh default; ``cp1252`` mimics Windows PowerShell 5.1 ANSI output
            redirects for non-ASCII text.
        :return: Absolute fixture path.
        """
        payload = self._capture_fixture_text(lines).encode(encoding)
        if bom:
            payload = b'\xef\xbb\xbf' + payload
        fixture_path = os.path.join(self.fixture_root, file_name)
        with open(fixture_path, 'wb') as file_handle:
            file_handle.write(payload)
        return fixture_path

    @staticmethod
    def _expected_merged_log_bytes(lines: list[str]) -> bytes:
        """Expected bytes for the raw merged ``.txt`` fallback log.

        Every captured line is written verbatim in file order (stdout block
        then stderr block) with CRLF endings and no BOM.

        :param lines: Merged raw log lines.
        :return: Expected file bytes, or b'' when there are no lines.
        """
        if not lines:
            return b''
        return ('\r\n'.join(lines) + '\r\n').encode('utf-8')

    @staticmethod
    def _expected_grouped_log_bytes(lines: list[str]) -> bytes:
        """Expected bytes for the normalized ``_<logFile>`` inside the replay folder.

        Mirrors the generated script's blank-line collapse exactly: a nonempty
        line always passes through; an empty line is emitted only while the
        previous state is empty (file start or a just-swallowed blank), which
        collapses blank runs and drops the blank right after text.

        :param lines: Merged raw log lines in file order.
        :return: Expected file bytes, or b'' when nothing is emitted.
        """
        previous = ''
        emitted: list[str] = []
        for line in lines:
            if line != '':
                previous = line
                emitted.append(line)
            elif previous == '':
                emitted.append(line)
                previous = 'h'
            else:
                previous = ''
        if not emitted:
            return b''
        return ('\r\n'.join(emitted) + '\r\n').encode('utf-8')

    def _log_dir_entries(self) -> list[str]:
        """Lists entries in the fixture log folder, which Run-BotOnce creates."""
        if not os.path.isdir(self.log_dir):
            return []
        return os.listdir(self.log_dir)

    def _grouped_dir_entries(self) -> list[str]:
        """Lists entries in the fixture grouped-log folder."""
        if not os.path.isdir(self.grouped_dir):
            return []
        return os.listdir(self.grouped_dir)

    def _assert_cleanup_launch_succeeded(self, markers: dict[str, list[str]]) -> None:
        """Asserts shared invariants of a generated-script cleanup run.

        :param markers: Parsed marker output from a cleanup-launch pwsh payload.
        """
        self.assertEqual(markers.get('PARSE_ERRORS', ['1'])[0], '0', 'generated script failed PowerShell parsing')
        self.assertEqual(markers.get('SCRIPT_THREW', ['MISSING'])[0], '', 'generated script threw during execution')
        self.assertNotIn('UNEXPECTED_SPAWN', markers)
        self.assertNotIn('SLEEP', markers, 'generated script still performs a fixed Start-Sleep')
        self.assertEqual(
            markers.get('HAS_LOGCLEANUP_TIMING', ['False'])[0], 'True',
            'generated script is missing LOGCLEANUP_* phase timing output')
        self.assertEqual(
            markers.get('HAS_FIXED_SLEEP', ['True'])[0], 'False',
            'generated script still contains the mandatory post-cleanup sleep')
        self.assertEqual(
            markers.get('HAS_EAP_STOP', ['False'])[0], 'True',
            'generated script does not set its own ErrorActionPreference=Stop')
        script_path = markers.get('SCRIPT_PATH', [''])[0]
        self.assertTrue(script_path, 'generated script path was never captured')
        self.assertFalse(os.path.exists(script_path), 'generated .ps1 was not cleaned up')
        played_path = re.sub(r'\.ps1$', '.played', script_path)
        self.assertFalse(os.path.exists(played_path), '.played marker was not cleaned up')

    def _capture_spawn_branch_ps(self) -> str:
        """PowerShell branch handling the stubbed inner python launch.

        Writes the configured synthetic captures to the redirected stdout/
        stderr paths — or, for ``existing-log`` mode, copies the fixture to the
        merged ``.txt`` path so cleanup sees a pre-existing log with no captures
        — and creates the replay snapshot dir (plus the optional grouped-write
        blocker). Shared by the pwsh harness stub and the Windows PowerShell
        5.1 wrapper so both exercise identical logic.

        :return: PowerShell source for the ``$FilePath -match 'python'`` branch.
        """
        return f"""
        if ($FilePath -match 'python') {{
            if ($null -ne $RedirectStandardOutput) {{
                if ($global:CaptureStdoutMode -eq 'copy') {{
                    [IO.File]::Copy($global:CaptureStdoutSource, $RedirectStandardOutput, $true)
                }} elseif ($global:CaptureStdoutMode -eq 'empty') {{
                    [IO.File]::WriteAllText($RedirectStandardOutput, '')
                }} elseif ($global:CaptureStdoutMode -eq 'existing-log') {{
                    $staleLogPath = $RedirectStandardOutput -replace '\\.stdout$', ''
                    [IO.File]::Copy($global:CaptureStdoutSource, $staleLogPath, $true)
                }}
            }}
            if ($null -ne $RedirectStandardError) {{
                if ($global:CaptureStderrMode -eq 'copy') {{
                    [IO.File]::Copy($global:CaptureStderrSource, $RedirectStandardError, $true)
                }} elseif ($global:CaptureStderrMode -eq 'empty') {{
                    [IO.File]::WriteAllText($RedirectStandardError, '')
                }}
            }}
            if ($null -ne $global:ReplayDirId) {{
                $replaySnapshotDir = Join-Path {_ps_literal(self.log_dir)} ("LauncherTestBot-replay-" + $global:ReplayDirId)
                $null = New-Item -ItemType Directory -Force -Path $replaySnapshotDir
                if ($global:CreateGroupedWriteBlocker) {{
                    $mergedLogPath = $RedirectStandardOutput -replace '\\.stdout$', ''
                    $blockerDir = Join-Path $replaySnapshotDir ("_" + (Split-Path $mergedLogPath -Leaf))
                    $null = New-Item -ItemType Directory -Force -Path $blockerDir
                }}
            }}
            return $null
        }}
"""

    def _write_cleanup_wrapper(
        self,
        *,
        stdout_mode: str,
        stdout_source: str | None,
        stderr_mode: str,
        stderr_source: str | None,
        replay_dir_id: str | None,
        create_grouped_write_blocker: bool,
        stub_move_item_error: bool,
        inner_marker_path: str,
    ) -> str:
        """Writes a Windows PowerShell 5.1 wrapper that stubs the inner bot launch.

        The generated cleanup script then runs under the same powershell.exe the
        real launcher spawns on Windows, so perf evidence matches production
        (pwsh enumerates ``[IO.File]::ReadLines`` ~10x slower than PS 5.1).
        Stub markers are appended to ``inner_marker_path`` for the pwsh harness
        to merge into its own marker stream. The wrapper deliberately starts at
        ``Continue`` like a real ``powershell.exe -File`` invocation so the
        generated child's own ``ErrorActionPreference = 'Stop'`` is what governs.

        :return: Absolute wrapper script path.
        """
        wrapper_path = os.path.join(self.fixture_root, 'cleanup-wrapper.ps1')
        content = f"""$ErrorActionPreference = 'Continue'
$global:CaptureStdoutMode = {_ps_literal(stdout_mode)}
$global:CaptureStdoutSource = {self._ps_nullable_literal(stdout_source)}
$global:CaptureStderrMode = {_ps_literal(stderr_mode)}
$global:CaptureStderrSource = {self._ps_nullable_literal(stderr_source)}
$global:ReplayDirId = {self._ps_nullable_literal(replay_dir_id)}
$global:CreateGroupedWriteBlocker = {'$true' if create_grouped_write_blocker else '$false'}
$global:StubMoveItemError = {'$true' if stub_move_item_error else '$false'}
$global:InnerMarkerPath = {_ps_literal(inner_marker_path)}
[IO.File]::WriteAllText($global:InnerMarkerPath, '')
if ($global:StubMoveItemError) {{
    function Move-Item {{
        param($Path, $LiteralPath, $Destination, [switch]$PassThru, [switch]$Force)
        Write-Error 'injected Move-Item failure for cleanup test'
    }}
}}
function Get-Random {{ param($Min, $Max, $Minimum, $Maximum) return 1 }}
function Start-Sleep {{ param($Seconds) [IO.File]::AppendAllText($global:InnerMarkerPath, "SLEEP|$Seconds`r`n") }}
function Start-Process {{
    param($FilePath, $ArgumentList, [switch]$Wait, [switch]$NoNewWindow, [switch]$PassThru,
          $RedirectStandardOutput, $RedirectStandardError)
    $argLine = ($ArgumentList -join ' ')
{self._capture_spawn_branch_ps()}
    [IO.File]::AppendAllText($global:InnerMarkerPath, "UNEXPECTED_SPAWN|$FilePath|$argLine`r`n")
    return $null
}}
try {{
    & $env:GENERALS_BOT_CLEANUP_TARGET_SCRIPT
    [IO.File]::AppendAllText($global:InnerMarkerPath, "SCRIPT_THREW|`r`n")
}} catch {{
    [IO.File]::AppendAllText($global:InnerMarkerPath, ("SCRIPT_THREW|" + $_.Exception.Message + "`r`n"))
}}
"""
        with open(wrapper_path, 'w', encoding='utf-8', newline='\n') as file_handle:
            file_handle.write(content)
        return wrapper_path

    def _run_cleanup_launch(
        self,
        *,
        stdout_mode: str = 'copy',
        stdout_source: str | None = None,
        stderr_mode: str = 'copy',
        stderr_source: str | None = None,
        bot_path: str | None = None,
        replay_dir_id: str | None = None,
        create_grouped_write_blocker: bool = False,
        stub_move_item_error: bool = False,
        use_windows_powershell: bool = False,
    ) -> tuple[dict[str, list[str]], str]:
        """Runs Run-BotOnce with the real generated cleanup script executed.

        The Start-Process stub covers both launch roles: the outer
        ``Powershell -File <guid>.ps1`` call executes the captured generated
        script with all streams merged into a string and wall time recorded —
        in-process under pwsh, or under ``powershell.exe`` via a stub wrapper
        when ``use_windows_powershell`` is set — and the inner python launch
        writes the configured synthetic captures to the redirected paths and
        returns ``$null`` so no bot process runs. ``Get-Random`` is pinned to 1
        so the 1% log-retention purge can never fire during tests.

        :param stdout_mode: 'copy' a fixture, 'empty' a zero-byte capture,
            'existing-log' to place the fixture at the merged ``.txt`` path
            instead of a ``.stdout`` capture, or 'absent' to leave the
            redirected file uncreated.
        :param stdout_source: Fixture path used when stdout_mode is 'copy'.
        :param stderr_mode: Same capture modes for stderr.
        :param stderr_source: Fixture path used when stderr_mode is 'copy'.
        :param bot_path: ``-path`` for Run-BotOnce (defaults to fake_bot_path).
        :param replay_dir_id: When set, the stub creates
            ``LauncherTestBot-replay-<id>`` inside the fixture log folder so
            replay grouping has a snapshot directory to move.
        :param create_grouped_write_blocker: Additionally create a directory
            named ``_<logFile>`` inside the replay dir so the grouped write
            fails deterministically.
        :param stub_move_item_error: Define a Move-Item stub that raises a
            non-terminating Write-Error, proving the generated child's own
            ErrorActionPreference=Stop aborts cleanup before sources are
            deleted.
        :param use_windows_powershell: When True the generated script runs under
            ``powershell.exe`` (Windows PowerShell 5.1) via a stub wrapper
            instead of in-process pwsh, matching the shell the real launcher
            spawns on Windows; the wrapper starts at Continue like a real
            ``powershell.exe -File`` invocation so the generated child's own
            error policy governs. Inner stub markers are merged back via a
            file.
        :return: Parsed ``KEY|value`` markers and the generated script's merged
            stream text.
        """
        effective_bot_path = self.fake_bot_path if bot_path is None else bot_path
        script_output_path = os.path.join(self.fixture_root, 'generated-script-output.txt')
        inner_marker_path = os.path.join(self.fixture_root, 'inner-cleanup-markers.txt')
        wrapper_path = ''
        if use_windows_powershell:
            wrapper_path = self._write_cleanup_wrapper(
                stdout_mode=stdout_mode,
                stdout_source=stdout_source,
                stderr_mode=stderr_mode,
                stderr_source=stderr_source,
                replay_dir_id=replay_dir_id,
                create_grouped_write_blocker=create_grouped_write_blocker,
                stub_move_item_error=stub_move_item_error,
                inner_marker_path=inner_marker_path)
        script = f"""
$env:TMP = {_ps_literal(self.temp_with_spaces)}
$env:TEMP = $env:TMP
{self._load_functions_prelude()}
$global:Markers = [System.Collections.ArrayList]::new()
function Get-BotUserIdForName {{ param($Name) return $null }}
function Get-Random {{ param($Min, $Max, $Minimum, $Maximum) return 1 }}
function Start-Sleep {{ param($Seconds) [void]$global:Markers.Add("SLEEP|$Seconds") }}
$global:CaptureStdoutMode = {_ps_literal(stdout_mode)}
$global:CaptureStdoutSource = {self._ps_nullable_literal(stdout_source)}
$global:CaptureStderrMode = {_ps_literal(stderr_mode)}
$global:CaptureStderrSource = {self._ps_nullable_literal(stderr_source)}
$global:ReplayDirId = {self._ps_nullable_literal(replay_dir_id)}
$global:CreateGroupedWriteBlocker = {'$true' if create_grouped_write_blocker else '$false'}
$global:StubMoveItemError = {'$true' if stub_move_item_error else '$false'}
$global:UseWindowsPowerShell = {'$true' if use_windows_powershell else '$false'}
$global:WrapperPath = {self._ps_nullable_literal(wrapper_path if wrapper_path else None)}
$global:InnerMarkerPath = {_ps_literal(inner_marker_path)}
if ($global:StubMoveItemError) {{
    function Move-Item {{
        param($Path, $LiteralPath, $Destination, [switch]$PassThru, [switch]$Force)
        Write-Error 'injected Move-Item failure for cleanup test'
    }}
}}
function Start-Process {{
    param($FilePath, $ArgumentList, [switch]$Wait, [switch]$NoNewWindow, [switch]$PassThru,
          $RedirectStandardOutput, $RedirectStandardError)
    $argLine = ($ArgumentList -join ' ')
    if ($argLine -match '-File\\s+"([^"]+\\.ps1)"') {{
        $scriptPath = $Matches[1]
        [void]$global:Markers.Add("SCRIPT_PATH|$scriptPath")
        $scriptContent = Get-Content -LiteralPath $scriptPath -Raw
        $parseTokens = $null
        $parseErrors = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$parseTokens, [ref]$parseErrors)
        [void]$global:Markers.Add("PARSE_ERRORS|$($parseErrors.Count)")
        [void]$global:Markers.Add("HAS_LOGCLEANUP_TIMING|$($scriptContent.Contains('LOGCLEANUP_TOTAL_MS'))")
        [void]$global:Markers.Add("HAS_FIXED_SLEEP|$($scriptContent.Contains('Start-Sleep -Seconds 1'))")
        [void]$global:Markers.Add("HAS_EAP_STOP|$($scriptContent.Contains("ErrorActionPreference = 'Stop'"))")
        $scriptStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
        try {{
            if ($global:UseWindowsPowerShell) {{
                $env:GENERALS_BOT_CLEANUP_TARGET_SCRIPT = $scriptPath
                & powershell.exe -NoProfile -File $global:WrapperPath *> {_ps_literal(script_output_path)}
                if (Test-Path -LiteralPath $global:InnerMarkerPath) {{
                    foreach ($innerMarker in [IO.File]::ReadAllLines($global:InnerMarkerPath)) {{
                        if (-not [string]::IsNullOrWhiteSpace($innerMarker)) {{
                            [void]$global:Markers.Add($innerMarker)
                        }}
                    }}
                }}
            }} else {{
                & $scriptPath *> {_ps_literal(script_output_path)}
                [void]$global:Markers.Add("SCRIPT_THREW|")
            }}
        }} catch {{
            [void]$global:Markers.Add("SCRIPT_THREW|$($_.Exception.Message)")
        }}
        [void]$global:Markers.Add("SCRIPT_MS|$($scriptStopwatch.ElapsedMilliseconds)")
        return $null
    }}
{self._capture_spawn_branch_ps()}
    [void]$global:Markers.Add("UNEXPECTED_SPAWN|$FilePath|$argLine")
    return $null
}}
$result = Run-BotOnce -name 'LauncherTestBot' -game 'ffa' -path {_ps_literal(effective_bot_path)} -noui
foreach ($marker in $global:Markers) {{ Write-Output $marker }}
Write-Output "RESULT|$result"
$scriptOutput = ''
if (Test-Path -LiteralPath {_ps_literal(script_output_path)}) {{
    $scriptOutput = [IO.File]::ReadAllText({_ps_literal(script_output_path)})
}}
Write-Output "SCRIPT_OUT_NOCRASH_WARN|$($scriptOutput.Contains('No crash/output log file found'))"
Write-Output "SCRIPT_OUT_NOCONTENT_WARN|$($scriptOutput.Contains('No content found'))"
Write-Output "SCRIPT_OUT_FILTER|$($scriptOutput.Contains('filter '))"
Write-Output "SCRIPT_OUT_GROUP_MS|$($scriptOutput.Contains('LOGCLEANUP_GROUP_MS='))"
Write-Output "SCRIPT_OUT_TOTAL_MS|$($scriptOutput.Contains('LOGCLEANUP_TOTAL_MS='))"
"""
        result = self._run_pwsh(script)
        markers = self._markers(result)
        script_output = ''
        if os.path.isfile(script_output_path):
            with open(script_output_path, 'r', encoding='utf-8', errors='replace') as file_handle:
                script_output = file_handle.read()
        return markers, script_output

    def test_run_botonce_cleanup_streams_merged_log_and_groups_replay(self) -> None:
        """Successful cleanup must stream-merge captures, mark the first replay id, and group the normalized log."""
        replay_id = 'cleanupReplay77'
        stdout_lines = [
            '',
            f'replay_id:[{replay_id}]',
            '',
            '',
            'stdout alpha line',
            '',
            '',
            '',
            'stdout beta line',
        ]
        stderr_lines = [
            'stderr gamma line',
            '',
            'replay_id:[decoySecondReplay]',
            'stderr delta line',
        ]
        stdout_fixture = self._write_capture_fixture('cleanup-stdout.txt', stdout_lines)
        stderr_fixture = self._write_capture_fixture('cleanup-stderr.txt', stderr_lines)
        markers, script_output = self._run_cleanup_launch(
            stdout_source=stdout_fixture,
            stderr_source=stderr_fixture,
            replay_dir_id=replay_id,
        )
        self._assert_cleanup_launch_succeeded(markers)
        self.assertEqual(markers.get('RESULT', [''])[0], 'True', 'played marker was not written for a replay log')
        self.assertEqual(markers.get('SCRIPT_OUT_FILTER', ['False'])[0], 'True', 'grouping filter line missing')
        self.assertEqual(markers.get('SCRIPT_OUT_NOCRASH_WARN', ['True'])[0], 'False')
        self.assertEqual(markers.get('SCRIPT_OUT_NOCONTENT_WARN', ['True'])[0], 'False')

        merged_lines = stdout_lines + stderr_lines
        expected_grouped = self._expected_grouped_log_bytes(merged_lines)

        grouped_entries = self._grouped_dir_entries()
        self.assertEqual(len(grouped_entries), 1, f'expected one grouped replay folder, got {grouped_entries}')
        folder_name = grouped_entries[0]
        self.assertTrue(folder_name.startswith('LauncherTestBot-ffa-'), folder_name)
        self.assertIn(f'---{replay_id}', folder_name)
        self.assertNotIn('decoySecondReplay', folder_name, 'a later replay id was used instead of the first')

        folder_path = os.path.join(self.grouped_dir, folder_name)
        grouped_files = [name for name in os.listdir(folder_path) if name.startswith('_') and name.endswith('.txt')]
        self.assertEqual(len(grouped_files), 1, f'expected one normalized log in {folder_path}: {os.listdir(folder_path)}')
        with open(os.path.join(folder_path, grouped_files[0]), 'rb') as file_handle:
            self.assertEqual(file_handle.read(), expected_grouped, 'grouped log differs from the blank-line transform')

        log_entries = self._log_dir_entries()
        self.assertFalse(
            any(name.endswith('.stdout') or name.endswith('.stderr') for name in log_entries),
            f'capture files were not removed: {log_entries}')
        self.assertFalse(
            any(name.startswith('LauncherTestBot-ffa-') and name.endswith('.txt') for name in log_entries),
            f'merged log was not removed after grouping: {log_entries}')
        self.assertFalse(
            any(name.startswith('LauncherTestBot-replay-') for name in log_entries),
            f'replay snapshot folder was not moved into grouped logs: {log_entries}')

    def test_run_botonce_cleanup_utf8_bom_unicode(self) -> None:
        """UTF-8-BOM captures with non-ASCII text must merge into clean BOM-less UTF-8."""
        stdout_lines = [
            'unicode stdout line: héllo wörld → end',
            'second stdout line',
        ]
        stderr_lines = ['unicode stderr line: naïve café ☕']
        stdout_fixture = self._write_capture_fixture('unicode-stdout.txt', stdout_lines, bom=True)
        stderr_fixture = self._write_capture_fixture('unicode-stderr.txt', stderr_lines)
        markers, script_output = self._run_cleanup_launch(
            stdout_source=stdout_fixture,
            stderr_source=stderr_fixture,
        )
        self._assert_cleanup_launch_succeeded(markers)
        self.assertEqual(markers.get('RESULT', [''])[0], 'False', 'no replay id means no played marker')

        merged_lines = stdout_lines + stderr_lines
        expected = self._expected_merged_log_bytes(merged_lines)
        txt_files = [name for name in self._log_dir_entries()
                     if name.startswith('LauncherTestBot-ffa-') and name.endswith('.txt')]
        self.assertEqual(len(txt_files), 1, f'expected one merged fallback log, got {self._log_dir_entries()}')
        with open(os.path.join(self.log_dir, txt_files[0]), 'rb') as file_handle:
            actual = file_handle.read()
        self.assertFalse(actual.startswith(b'\xef\xbb\xbf'), 'merged log still carries a UTF-8 BOM')
        self.assertEqual(actual, expected, 'merged log content differs from stdout-then-stderr order')
        self.assertEqual(self._grouped_dir_entries(), [], 'ungrouped run must not create replay folders')
        self.assertFalse(
            any(name.endswith('.stdout') or name.endswith('.stderr') for name in self._log_dir_entries()),
            'capture files were not removed')

    def test_run_botonce_cleanup_missing_replay_keeps_merged_fallback(self) -> None:
        """Without a replay id the raw merged .txt must preserve every line verbatim."""
        stdout_lines = ['first line', '', '', '', 'second line', '', 'third line']
        stderr_lines = ['stderr only line', '', '']
        stdout_fixture = self._write_capture_fixture('noreplay-stdout.txt', stdout_lines)
        stderr_fixture = self._write_capture_fixture('noreplay-stderr.txt', stderr_lines)
        markers, script_output = self._run_cleanup_launch(
            stdout_source=stdout_fixture,
            stderr_source=stderr_fixture,
        )
        self._assert_cleanup_launch_succeeded(markers)
        self.assertEqual(markers.get('RESULT', [''])[0], 'False')

        merged_lines = stdout_lines + stderr_lines
        expected = self._expected_merged_log_bytes(merged_lines)
        # The fallback must keep the blank runs verbatim; the grouped transform
        # would collapse 'first line' + 3 blanks + 'second line' differently.
        self.assertIn(b'first line\r\n\r\n\r\n\r\nsecond line', expected)
        txt_files = [name for name in self._log_dir_entries()
                     if name.startswith('LauncherTestBot-ffa-') and name.endswith('.txt')]
        self.assertEqual(len(txt_files), 1, f'expected one merged fallback log, got {self._log_dir_entries()}')
        with open(os.path.join(self.log_dir, txt_files[0]), 'rb') as file_handle:
            self.assertEqual(file_handle.read(), expected, 'fallback log was normalized instead of kept raw')
        self.assertEqual(self._grouped_dir_entries(), [])
        self.assertFalse(
            any(name.endswith('.stdout') or name.endswith('.stderr') for name in self._log_dir_entries()))

    def test_run_botonce_cleanup_historical_keeps_raw_log_and_marker(self) -> None:
        """Historical bots still get the played marker but never replay grouping."""
        replay_id = 'histReplay42'
        hist_bot = os.path.join(self.hist_root, 'generals-bot-2023-08-26', 'BotHost.py')
        stdout_lines = [f'replay_id:[{replay_id}]', 'historical stdout line']
        stderr_lines = ['historical stderr line']
        stdout_fixture = self._write_capture_fixture('hist-stdout.txt', stdout_lines)
        stderr_fixture = self._write_capture_fixture('hist-stderr.txt', stderr_lines)
        markers, script_output = self._run_cleanup_launch(
            stdout_source=stdout_fixture,
            stderr_source=stderr_fixture,
            bot_path=hist_bot,
            replay_dir_id=replay_id,
        )
        self._assert_cleanup_launch_succeeded(markers)
        self.assertEqual(markers.get('RESULT', [''])[0], 'True', 'historical replay must still write the played marker')
        self.assertEqual(markers.get('SCRIPT_OUT_FILTER', ['True'])[0], 'False', 'historical path must not group')

        merged_lines = stdout_lines + stderr_lines
        expected = self._expected_merged_log_bytes(merged_lines)
        txt_files = [name for name in self._log_dir_entries()
                     if name.startswith('LauncherTestBot-ffa-') and name.endswith('.txt')]
        self.assertEqual(len(txt_files), 1, f'expected the raw merged log to remain, got {self._log_dir_entries()}')
        with open(os.path.join(self.log_dir, txt_files[0]), 'rb') as file_handle:
            self.assertEqual(file_handle.read(), expected)
        self.assertTrue(
            f'LauncherTestBot-replay-{replay_id}' in self._log_dir_entries(),
            f'replay snapshot folder should stay put for historical bots: {self._log_dir_entries()}')
        self.assertFalse(
            any(replay_id in name for name in self._grouped_dir_entries()),
            f'historical run must not create a grouped folder: {self._grouped_dir_entries()}')
        self.assertFalse(
            any(name.endswith('.stdout') or name.endswith('.stderr') for name in self._log_dir_entries()))

    def test_run_botonce_cleanup_empty_captures(self) -> None:
        """Zero-byte/absent captures must not create a merged log and must still clean up."""
        markers, script_output = self._run_cleanup_launch(
            stdout_mode='empty',
            stderr_mode='absent',
        )
        self._assert_cleanup_launch_succeeded(markers)
        self.assertEqual(markers.get('RESULT', [''])[0], 'False')
        self.assertEqual(
            markers.get('SCRIPT_OUT_NOCRASH_WARN', ['False'])[0], 'True',
            'missing merged log warning was not emitted')
        log_entries = self._log_dir_entries()
        self.assertFalse(
            any(name.endswith('.txt') or name.endswith('.stdout') or name.endswith('.stderr')
                for name in log_entries),
            f'empty captures must leave no log artifacts: {log_entries}')
        self.assertEqual(self._grouped_dir_entries(), [])

    def test_run_botonce_cleanup_write_error_preserves_captures(self) -> None:
        """A grouped-write failure must propagate and leave captures plus the raw merged log."""
        replay_id = 'boomReplay9'
        stdout_lines = [f'replay_id:[{replay_id}]', 'line before failure', '', 'another line']
        stderr_lines = ['stderr line']
        stdout_fixture = self._write_capture_fixture('boom-stdout.txt', stdout_lines)
        stderr_fixture = self._write_capture_fixture('boom-stderr.txt', stderr_lines)
        markers, script_output = self._run_cleanup_launch(
            stdout_source=stdout_fixture,
            stderr_source=stderr_fixture,
            replay_dir_id=replay_id,
            create_grouped_write_blocker=True,
        )
        self.assertEqual(markers.get('PARSE_ERRORS', ['1'])[0], '0')
        self.assertNotIn('UNEXPECTED_SPAWN', markers)
        self.assertNotIn('SLEEP', markers)
        self.assertEqual(markers.get('HAS_LOGCLEANUP_TIMING', ['False'])[0], 'True')
        threw = markers.get('SCRIPT_THREW', ['MISSING'])[0]
        self.assertNotIn(threw, ('', 'MISSING'), 'grouped-write failure did not propagate')
        # The played marker is written during the merge pass, before grouping.
        self.assertEqual(markers.get('RESULT', [''])[0], 'True')

        log_entries = self._log_dir_entries()
        self.assertTrue(
            any(name.endswith('.stdout') for name in log_entries),
            f'stdout capture must survive a grouping failure: {log_entries}')
        self.assertTrue(
            any(name.endswith('.stderr') for name in log_entries),
            f'stderr capture must survive a grouping failure: {log_entries}')
        merged_lines = stdout_lines + stderr_lines
        expected = self._expected_merged_log_bytes(merged_lines)
        txt_files = [name for name in log_entries
                     if name.startswith('LauncherTestBot-ffa-') and name.endswith('.txt')]
        self.assertEqual(len(txt_files), 1, f'raw merged log must survive a grouping failure: {log_entries}')
        with open(os.path.join(self.log_dir, txt_files[0]), 'rb') as file_handle:
            self.assertEqual(file_handle.read(), expected)
        self.assertTrue(
            f'LauncherTestBot-replay-{replay_id}' in log_entries,
            f'replay snapshot folder must not be moved on failure: {log_entries}')
        self.assertFalse(
            any(replay_id in name for name in self._grouped_dir_entries()),
            f'failed grouping must not leave a moved folder: {self._grouped_dir_entries()}')

    def test_run_botonce_cleanup_cp1252_captures_decode_under_windows_powershell(self) -> None:
        """ANSI/cp1252 captures must decode via the shell default encoding, then write UTF-8."""
        stdout_lines = ['cp1252 stdout: café naïve crème brûlée']
        stderr_lines = ['cp1252 stderr: voilà']
        stdout_fixture = self._write_capture_fixture(
            'cp1252-stdout.txt', stdout_lines, encoding='cp1252')
        stderr_fixture = self._write_capture_fixture(
            'cp1252-stderr.txt', stderr_lines, encoding='cp1252')
        markers, script_output = self._run_cleanup_launch(
            stdout_source=stdout_fixture,
            stderr_source=stderr_fixture,
            use_windows_powershell=True,
        )
        self._assert_cleanup_launch_succeeded(markers)
        self.assertEqual(markers.get('RESULT', [''])[0], 'False', 'no replay id means no played marker')

        merged_lines = stdout_lines + stderr_lines
        expected = self._expected_merged_log_bytes(merged_lines)
        txt_files = [name for name in self._log_dir_entries()
                     if name.startswith('LauncherTestBot-ffa-') and name.endswith('.txt')]
        self.assertEqual(len(txt_files), 1, f'expected one merged fallback log, got {self._log_dir_entries()}')
        with open(os.path.join(self.log_dir, txt_files[0]), 'rb') as file_handle:
            actual = file_handle.read()
        self.assertFalse(actual.startswith(b'\xef\xbb\xbf'), 'merged log still carries a UTF-8 BOM')
        self.assertEqual(actual, expected, 'cp1252 captures were not transcoded to UTF-8 correctly')
        self.assertIn(
            'café'.encode('utf-8'), actual,
            'cp1252 high-byte was not decoded before the UTF-8 write')
        self.assertEqual(self._grouped_dir_entries(), [])
        self.assertFalse(
            any(name.endswith('.stdout') or name.endswith('.stderr') for name in self._log_dir_entries()),
            'capture files were not removed')

    def test_run_botonce_cleanup_cp1252_captures_group_utf8(self) -> None:
        """cp1252 captures that reach replay grouping must emit a UTF-8 normalized log."""
        replay_id = 'cp1252Group3'
        stdout_lines = [f'replay_id:[{replay_id}]', 'cp1252 grouped stdout: café']
        stderr_lines = ['cp1252 grouped stderr: voilà', '', '']
        stdout_fixture = self._write_capture_fixture(
            'cp1252-group-stdout.txt', stdout_lines, encoding='cp1252')
        stderr_fixture = self._write_capture_fixture(
            'cp1252-group-stderr.txt', stderr_lines, encoding='cp1252')
        markers, script_output = self._run_cleanup_launch(
            stdout_source=stdout_fixture,
            stderr_source=stderr_fixture,
            replay_dir_id=replay_id,
            use_windows_powershell=True,
        )
        self._assert_cleanup_launch_succeeded(markers)
        self.assertEqual(markers.get('RESULT', [''])[0], 'True')

        expected = self._expected_grouped_log_bytes(stdout_lines + stderr_lines)
        grouped_entries = self._grouped_dir_entries()
        self.assertEqual(len(grouped_entries), 1, f'expected one grouped replay folder, got {grouped_entries}')
        folder_path = os.path.join(self.grouped_dir, grouped_entries[0])
        grouped_files = [name for name in os.listdir(folder_path) if name.startswith('_') and name.endswith('.txt')]
        self.assertEqual(len(grouped_files), 1, f'expected one normalized log in {folder_path}')
        with open(os.path.join(folder_path, grouped_files[0]), 'rb') as file_handle:
            actual = file_handle.read()
        self.assertEqual(actual, expected, 'grouped log differs from the UTF-8 blank-line transform')
        self.assertIn('café'.encode('utf-8'), actual)
        self.assertFalse(
            any(name.endswith('.stdout') or name.endswith('.stderr') for name in self._log_dir_entries()))
        self.assertFalse(
            any(name.startswith('LauncherTestBot-ffa-') and name.endswith('.txt') for name in self._log_dir_entries()),
            'merged log was not removed after successful grouping')

    def test_run_botonce_cleanup_stale_cp1252_log_groups_utf8(self) -> None:
        """A pre-existing ANSI log with no captures must group through the default encoding into UTF-8."""
        replay_id = 'staleCp1252'
        stale_lines = [
            f'replay_id:[{replay_id}]',
            'stale cp1252 line: café naïve',
            '',
            '',
            'stale tail: crème brûlée',
        ]
        stale_fixture = self._write_capture_fixture(
            'stale-log.txt', stale_lines, encoding='cp1252')
        markers, script_output = self._run_cleanup_launch(
            stdout_mode='existing-log',
            stdout_source=stale_fixture,
            stderr_mode='absent',
            replay_dir_id=replay_id,
            use_windows_powershell=True,
        )
        self._assert_cleanup_launch_succeeded(markers)
        self.assertEqual(
            markers.get('RESULT', [''])[0], 'True',
            'stale log replay id was not marked played')

        expected = self._expected_grouped_log_bytes(stale_lines)
        grouped_entries = self._grouped_dir_entries()
        self.assertEqual(len(grouped_entries), 1, f'expected one grouped replay folder, got {grouped_entries}')
        self.assertIn(f'---{replay_id}', grouped_entries[0])
        folder_path = os.path.join(self.grouped_dir, grouped_entries[0])
        grouped_files = [name for name in os.listdir(folder_path) if name.startswith('_') and name.endswith('.txt')]
        self.assertEqual(len(grouped_files), 1, f'expected one normalized log in {folder_path}')
        with open(os.path.join(folder_path, grouped_files[0]), 'rb') as file_handle:
            actual = file_handle.read()
        self.assertEqual(actual, expected, 'stale ANSI log was not transcoded to UTF-8 during grouping')
        self.assertIn(
            'café'.encode('utf-8'), actual,
            'stale cp1252 high-byte was not decoded before the UTF-8 write')

        log_entries = self._log_dir_entries()
        self.assertFalse(
            any(name.endswith('.stdout') or name.endswith('.stderr') for name in log_entries),
            f'no captures should exist in existing-log mode: {log_entries}')
        self.assertFalse(
            any(name.startswith('LauncherTestBot-ffa-') and name.endswith('.txt') for name in log_entries),
            f'stale merged log was not removed after successful grouping: {log_entries}')
        self.assertFalse(
            any(name.startswith('LauncherTestBot-replay-') for name in log_entries),
            f'replay snapshot folder was not moved into grouped logs: {log_entries}')

    def test_run_botonce_cleanup_utf8_bom_unicode_windows_powershell(self) -> None:
        """BOM-marked UTF-8 captures must decode correctly under Windows PowerShell 5.1 as well."""
        stdout_lines = [
            'unicode stdout line: héllo wörld → end',
            'second stdout line',
        ]
        stderr_lines = ['unicode stderr line: naïve café ☕']
        stdout_fixture = self._write_capture_fixture('unicode-stdout.txt', stdout_lines, bom=True)
        stderr_fixture = self._write_capture_fixture('unicode-stderr.txt', stderr_lines, bom=True)
        markers, script_output = self._run_cleanup_launch(
            stdout_source=stdout_fixture,
            stderr_source=stderr_fixture,
            use_windows_powershell=True,
        )
        self._assert_cleanup_launch_succeeded(markers)
        self.assertEqual(markers.get('RESULT', [''])[0], 'False', 'no replay id means no played marker')

        merged_lines = stdout_lines + stderr_lines
        expected = self._expected_merged_log_bytes(merged_lines)
        txt_files = [name for name in self._log_dir_entries()
                     if name.startswith('LauncherTestBot-ffa-') and name.endswith('.txt')]
        self.assertEqual(len(txt_files), 1, f'expected one merged fallback log, got {self._log_dir_entries()}')
        with open(os.path.join(self.log_dir, txt_files[0]), 'rb') as file_handle:
            actual = file_handle.read()
        self.assertFalse(actual.startswith(b'\xef\xbb\xbf'), 'merged log still carries a UTF-8 BOM')
        self.assertEqual(actual, expected, 'BOM-marked UTF-8 captures were not decoded under PS 5.1')
        self.assertEqual(self._grouped_dir_entries(), [])
        self.assertFalse(
            any(name.endswith('.stdout') or name.endswith('.stderr') for name in self._log_dir_entries()),
            'capture files were not removed')

    def test_run_botonce_cleanup_move_error_preserves_captures(self) -> None:
        """A non-terminating Move-Item failure must abort cleanup via the child's own EAP=Stop."""
        replay_id = 'moveBoom5'
        stdout_lines = [f'replay_id:[{replay_id}]', 'line before move failure', '', 'tail line']
        stderr_lines = ['stderr line']
        stdout_fixture = self._write_capture_fixture('move-stdout.txt', stdout_lines)
        stderr_fixture = self._write_capture_fixture('move-stderr.txt', stderr_lines)
        markers, script_output = self._run_cleanup_launch(
            stdout_source=stdout_fixture,
            stderr_source=stderr_fixture,
            replay_dir_id=replay_id,
            stub_move_item_error=True,
            use_windows_powershell=True,
        )
        self.assertEqual(markers.get('PARSE_ERRORS', ['1'])[0], '0')
        self.assertNotIn('UNEXPECTED_SPAWN', markers)
        self.assertNotIn('SLEEP', markers)
        self.assertEqual(markers.get('HAS_LOGCLEANUP_TIMING', ['False'])[0], 'True')
        self.assertEqual(markers.get('HAS_EAP_STOP', ['False'])[0], 'True')
        threw = markers.get('SCRIPT_THREW', ['MISSING'])[0]
        self.assertNotIn(
            threw, ('', 'MISSING'),
            'Move-Item failure did not propagate out of the generated script')
        # The played marker is written during the merge pass, before grouping.
        self.assertEqual(markers.get('RESULT', [''])[0], 'True')

        log_entries = self._log_dir_entries()
        self.assertTrue(
            any(name.endswith('.stdout') for name in log_entries),
            f'stdout capture must survive a move failure: {log_entries}')
        self.assertTrue(
            any(name.endswith('.stderr') for name in log_entries),
            f'stderr capture must survive a move failure: {log_entries}')
        merged_lines = stdout_lines + stderr_lines
        expected = self._expected_merged_log_bytes(merged_lines)
        txt_files = [name for name in log_entries
                     if name.startswith('LauncherTestBot-ffa-') and name.endswith('.txt')]
        self.assertEqual(len(txt_files), 1, f'raw merged log must survive a move failure: {log_entries}')
        with open(os.path.join(self.log_dir, txt_files[0]), 'rb') as file_handle:
            self.assertEqual(file_handle.read(), expected)
        self.assertTrue(
            f'LauncherTestBot-replay-{replay_id}' in log_entries,
            f'replay snapshot folder must not move on failure: {log_entries}')
        # The normalized grouped file is written inside the replay dir before
        # Move-Item runs, so it remains there when the move fails.
        replay_dir_path = os.path.join(self.log_dir, f'LauncherTestBot-replay-{replay_id}')
        self.assertTrue(
            any(name.startswith('_') and name.endswith('.txt') for name in os.listdir(replay_dir_path)),
            f'normalized log should remain inside the unmoved replay dir: {os.listdir(replay_dir_path)}')
        self.assertFalse(
            any(replay_id in name for name in self._grouped_dir_entries()),
            f'failed move must not leave a moved folder: {self._grouped_dir_entries()}')

    def test_run_botonce_cleanup_perf_streaming_under_threshold(self) -> None:
        """~42MB captures must stream-clean far below the old multi-pass seconds plus sleep."""
        replay_id = 'perfReplay123'
        log_line = ('[2026-11-16 20:00:00.000000] INFO: bot: Complete t300: (0.001 seconds) '
                    'Search operation details army=150 tile=(12, 15)')
        lines: list[str] = [f'replay_id:[{replay_id}]']
        for index in range(350000):
            lines.append(log_line)
            if index % 10 == 0:
                lines.append('')
        stderr_lines = ['perf stderr line']
        stdout_fixture = self._write_capture_fixture('perf-stdout.txt', lines)
        stderr_fixture = self._write_capture_fixture('perf-stderr.txt', stderr_lines)
        fixture_size = os.path.getsize(stdout_fixture)
        self.assertGreater(fixture_size, 40_000_000, 'perf fixture is too small to be representative')

        # Pre-create the replay snapshot dir with payload files so Move-Item has
        # real directory content, mirroring a live game folder.
        replay_dir = os.path.join(self.log_dir, f'LauncherTestBot-replay-{replay_id}')
        os.makedirs(replay_dir, exist_ok=True)
        for file_index in range(50):
            with open(os.path.join(replay_dir, f'snap_{file_index}.txt'), 'w', encoding='utf-8') as file_handle:
                file_handle.write('snapshot fixture\n')

        markers, script_output = self._run_cleanup_launch(
            stdout_source=stdout_fixture,
            stderr_source=stderr_fixture,
            replay_dir_id=replay_id,
            use_windows_powershell=True,
        )
        self._assert_cleanup_launch_succeeded(markers)
        self.assertEqual(markers.get('RESULT', [''])[0], 'True')
        # LOGCLEANUP_TOTAL_MS is the generated script's own stopwatch around the
        # whole cleanup block, excluding fixture creation and shell startup.
        total_match = re.search(r'LOGCLEANUP_TOTAL_MS=(\d+)', script_output)
        self.assertIsNotNone(total_match, 'cleanup phase timing missing from generated script output')
        cleanup_ms = int(total_match.group(1)) if total_match else 0
        self.assertLess(
            cleanup_ms, 3000,
            f'generated cleanup took {cleanup_ms}ms; the old pipeline path measured >12s plus a fixed 1s sleep')
        script_ms = int(markers.get('SCRIPT_MS', ['0'])[0])
        self.assertLess(
            script_ms, 3000,
            f'generated script wall time took {script_ms}ms including powershell.exe startup')

        merged_lines = lines + stderr_lines
        expected = self._expected_grouped_log_bytes(merged_lines)
        grouped_entries = self._grouped_dir_entries()
        self.assertEqual(len(grouped_entries), 1, f'expected one grouped replay folder, got {grouped_entries}')
        folder_path = os.path.join(self.grouped_dir, grouped_entries[0])
        grouped_files = [name for name in os.listdir(folder_path) if name.startswith('_') and name.endswith('.txt')]
        self.assertEqual(len(grouped_files), 1, f'expected one normalized log in {folder_path}')
        grouped_log_path = os.path.join(folder_path, grouped_files[0])
        self.assertEqual(os.path.getsize(grouped_log_path), len(expected), 'grouped log size mismatch')
        # Spot-check completeness at both ends rather than loading 40MB twice.
        with open(grouped_log_path, 'rb') as file_handle:
            head = file_handle.read(4096)
            file_handle.seek(-4096, os.SEEK_END)
            tail = file_handle.read(4096)
        self.assertTrue(expected.startswith(head), 'grouped log head differs')
        self.assertTrue(expected.endswith(tail), 'grouped log tail differs')
        snapshot_files = [name for name in os.listdir(folder_path) if name.startswith('snap_')]
        self.assertEqual(len(snapshot_files), 50, 'replay snapshot files did not move with the folder')

        log_entries = self._log_dir_entries()
        self.assertFalse(
            any(name.endswith('.stdout') or name.endswith('.stderr') for name in log_entries))
        self.assertFalse(
            any(name.startswith('LauncherTestBot-ffa-') and name.endswith('.txt') for name in log_entries))

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
