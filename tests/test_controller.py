from __future__ import annotations
import io, json, os, runpy, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'codex'))
sys.path.insert(0, str(ROOT / 'codex' / 'hooks'))

from hooks.redteam_state import RedTeamState, default_state
from hooks.core.state_manager import update_mode

HOOK = ROOT / 'codex' / 'hooks' / 'hook-security-context-hook.py'
SESSION = ROOT / 'codex' / 'hooks' / 'session-start-context.py'


class FakeIn:
    def __init__(self, b):
        self.buffer = io.BytesIO(b)


def run_script(path, payload=None):
    old_stdin, old_stdout = sys.stdin, sys.stdout
    old_env = os.environ.copy()
    temp_sessions = None
    if not os.environ.get('CODEX_REDTEAM_SESSION_DIR'):
        temp_sessions = tempfile.TemporaryDirectory()
        os.environ['CODEX_REDTEAM_SESSION_DIR'] = temp_sessions.name
    buf = io.StringIO()
    sys.stdout = buf
    data = b'' if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    sys.stdin = FakeIn(data)
    try:
        runpy.run_path(str(path), run_name='__main__')
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout
        os.environ.clear(); os.environ.update(old_env)
        if temp_sessions is not None:
            temp_sessions.cleanup()
    return buf.getvalue().strip()


class IntentTests(unittest.TestCase):
    def test_detect_chinese_revise_intent(self):
        from hooks.core.intent_engine import detect_intent
        state = default_state('intent-cn-revise')
        state.objective = '旧目标'
        result = detect_intent('新的目标：只测试支付回调伪造。', state)
        self.assertEqual(result.intent_type, 'revise')
        self.assertIn('支付回调伪造', result.objective_delta)

    def test_detect_chinese_verify_intent(self):
        from hooks.core.intent_engine import detect_intent
        state = default_state('intent-cn-verify')
        state.objective = '验证 jwt 重放'
        result = detect_intent('请验证这是不是有效漏洞，并确认需要什么证据。', state)
        self.assertEqual(result.intent_type, 'verify')
        self.assertTrue(result.should_verify_now)

    def test_detect_new_intent_from_empty_objective(self):
        from hooks.core.intent_engine import detect_intent
        state = default_state('intent-new')
        result = detect_intent('Analyze JWT login flow and validate reuse risk', state)
        self.assertEqual(result.intent_type, 'new')
        self.assertTrue(result.should_refresh_taskbook)

    def test_detect_verify_intent(self):
        from hooks.core.intent_engine import detect_intent
        state = default_state('intent-verify')
        state.objective = 'validate jwt reuse'
        result = detect_intent('Please verify and confirm whether this is a valid vulnerability.', state)
        self.assertEqual(result.intent_type, 'verify')
        self.assertTrue(result.should_verify_now)

    def test_generic_confirm_does_not_misfire_into_verify(self):
        from hooks.core.intent_engine import detect_intent
        state = default_state('intent-confirm-misfire')
        state.objective = 'trace payment callback'
        result = detect_intent('Confirm the callback path and continue tracing the code path.', state)
        self.assertEqual(result.intent_type, 'continue')

    def test_detect_revise_intent(self):
        from hooks.core.intent_engine import detect_intent
        state = default_state('intent-revise')
        state.objective = 'old objective'
        result = detect_intent('New objective: only test payment callback forgery.', state)
        self.assertEqual(result.intent_type, 'revise')
        self.assertTrue(result.objective_delta)

    def test_parse_mode_command_supports_chinese_triggers(self):
        from hooks.core.prompt_parser import parse_mode_command
        self.assertEqual(parse_mode_command('开启红队模式'), 'redteam-light')
        self.assertEqual(parse_mode_command('进入红队模式'), 'redteam-light')
        self.assertEqual(parse_mode_command('关闭红队模式'), 'normal')
        self.assertEqual(parse_mode_command('退出红队模式'), 'normal')

    def test_extract_prompt_ignores_explicit_non_user_messages(self):
        from hooks.core.prompt_parser import extract_prompt

        payload = {
            'messages': [
                {'role': 'assistant', 'content': '/redteam on'},
                {'role': 'system', 'content': 'system prompt'},
            ],
        }

        self.assertEqual(extract_prompt(payload), '')

    def test_extract_prompt_keeps_legacy_roleless_messages(self):
        from hooks.core.prompt_parser import extract_prompt

        payload = {'messages': [{'content': 'legacy prompt'}]}

        self.assertEqual(extract_prompt(payload), 'legacy prompt')

    def test_process_turn_includes_automation_tool_selection_summary(self):
        from hooks.core.controller import process_turn
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tool_config = Path(td) / 'mcp_tools.json'
            tool_config.write_text(
                json.dumps(
                    {
                        'mcp_tools': [
                            {
                                'name': 'browser-use',
                                'capabilities': ['browser_automation', 'page_fetch'],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding='utf-8',
            )
            old = os.environ.get('CODEX_REDTEAM_MCP_TOOLS')
            os.environ['CODEX_REDTEAM_MCP_TOOLS'] = str(tool_config)
            try:
                state = default_state('automation-summary')
                state.mode = 'redteam-light'
                result = process_turn(
                    prompt='请分析页面并用浏览器验证登录流程',
                    state=state,
                    codex_dir=ROOT / 'codex',
                    assistant_summary='',
                )
            finally:
                if old is None:
                    os.environ.pop('CODEX_REDTEAM_MCP_TOOLS', None)
                else:
                    os.environ['CODEX_REDTEAM_MCP_TOOLS'] = old

        self.assertIn('[tool:page_fetch]', result.brief)
        self.assertIn('selected=browser-use', result.brief)
        self.assertIn('fallback=preferred_tool_unavailable', result.brief)


class TaskbookTests(unittest.TestCase):
    def test_refresh_taskbook_creates_todos(self):
        from hooks.core.taskbook import refresh_taskbook
        taskbook = refresh_taskbook(
            objective='validate jwt reuse path',
            phase='strategy',
            selected_path='jwt-oauth-token-attacks',
            previous=None,
            intent_type='new',
        )
        self.assertEqual(taskbook.objective, 'validate jwt reuse path')
        self.assertGreaterEqual(len(taskbook.todo_items), 1)
        self.assertGreaterEqual(len(taskbook.acceptance_checks), 1)

    def test_current_task_is_selected_without_mutating_source(self):
        from hooks.core.taskbook import refresh_taskbook, select_current_task
        taskbook = refresh_taskbook(
            objective='validate jwt reuse path',
            phase='strategy',
            selected_path='jwt-oauth-token-attacks',
            previous=None,
            intent_type='new',
        )
        selection = select_current_task(taskbook)
        self.assertIsNotNone(selection.current_task)
        self.assertEqual(selection.current_task.status, 'running')
        self.assertEqual(taskbook.todo_items[1].status, 'pending')
        self.assertEqual(selection.taskbook.todo_items[1].status, 'pending')


class MemoryStoreTests(unittest.TestCase):
    def test_session_memory_roundtrip(self):
        from hooks.core.memory_store import load_session_memory, save_session_memory
        data = {
            'taskbook': {'objective': 'x'},
            'facts_confirmed': ['a'],
            'assumptions_active': [],
            'recent_artifacts': [],
            'ruled_out_paths': [],
            'coverage_tags_seen': [],
            'coverage_tags_pending': [],
            'acceptance_checks': [],
            'reflection_log': [],
            'boundary_events': [],
            'boundary': {'in_scope': [], 'out_of_scope': [], 'allow_cross_system': False},
        }
        save_session_memory('memory-roundtrip', data)
        loaded = load_session_memory('memory-roundtrip')
        self.assertEqual(loaded['taskbook']['objective'], 'x')
        self.assertEqual(loaded['facts_confirmed'], ['a'])

    def test_save_session_memory_preserves_unknown_keys_and_nested_boundary_fields(self):
        from hooks.core.memory_store import load_session_memory, save_session_memory
        save_session_memory('memory-merge', {
            'taskbook': {'objective': 'x'},
            'facts_confirmed': ['a'],
            'custom_extra': {'keep': True},
            'boundary': {'notes': 'old', 'custom_flag': 'keep-me'},
        })
        save_session_memory('memory-merge', {
            'boundary': {'notes': 'new'},
            'facts_confirmed': ['b'],
        })
        loaded = load_session_memory('memory-merge')
        self.assertEqual(loaded['facts_confirmed'], ['b'])
        self.assertEqual(loaded['custom_extra'], {'keep': True})
        self.assertEqual(loaded['boundary']['notes'], 'new')
        self.assertEqual(loaded['boundary']['custom_flag'], 'keep-me')


class VerifyTests(unittest.TestCase):
    def test_verify_detects_pseudo_complete_when_no_evidence(self):
        from hooks.core.verify_engine import verify_progress
        state = default_state('verify')
        result = verify_progress(
            objective='validate jwt reuse',
            acceptance_checks=['need replay evidence'],
            evidence_level='unknown',
            gate_ok=False,
            assistant_summary='Confirmed vulnerability and task complete',
        )
        self.assertTrue(result.pseudo_complete)
        self.assertFalse(result.passed)

    def test_verify_does_not_flag_unconfirmed_summary_as_pseudo_complete(self):
        from hooks.core.verify_engine import verify_progress
        result = verify_progress(
            objective='validate jwt reuse',
            acceptance_checks=['need replay evidence'],
            evidence_level='unknown',
            gate_ok=False,
            assistant_summary='This is not confirmed yet; need more evidence before we can close it.',
        )
        self.assertFalse(result.pseudo_complete)
        self.assertEqual(result.reason_code, 'missing_evidence')


class ControllerTests(unittest.TestCase):
    def test_token_keyword_alone_does_not_imply_partial_evidence(self):
        from hooks.core.controller import process_turn
        state = default_state('controller-token-generic')
        state.mode = 'redteam-full'
        result = process_turn(
            prompt='Analyze token reuse risk in this login flow.',
            state=state,
            codex_dir=ROOT / 'codex',
            assistant_summary='',
        )
        self.assertIn('[evidence:unknown]', result.brief)

    def test_process_turn_produces_v4_brief(self):
        from hooks.core.controller import process_turn
        state = default_state('controller-brief')
        state.mode = 'redteam-full'
        result = process_turn(
            prompt='Analyze JWT login flow and validate token reuse risk',
            state=state,
            codex_dir=ROOT / 'codex',
            assistant_summary='',
        )
        self.assertIn('[mode:redteam-full]', result.brief)
        self.assertIn('[intent:', result.brief)
        self.assertIn('[objective:', result.brief)
        self.assertIn('[stage:', result.brief)
        self.assertIn('[task:', result.brief)
        self.assertIn('[check]', result.brief)

    def test_process_turn_sets_intent_and_task(self):
        from hooks.core.controller import process_turn
        state = default_state('controller-task')
        state.mode = 'redteam-full'
        result = process_turn(
            prompt='Analyze AWS IAM role assumption and metadata credential abuse paths',
            state=state,
            codex_dir=ROOT / 'codex',
            assistant_summary='',
        )
        self.assertIn(result.state.intent_type, {'new', 'continue', 'revise', 'verify', 'summarize'})
        self.assertTrue(result.state.objective)
        self.assertTrue(result.state.current_task_id)

    def test_process_turn_creates_artifact_and_advances_stage_with_concrete_recon_evidence(self):
        from hooks.core.controller import process_turn
        state = default_state('controller-stage')
        state.mode = 'redteam-full'
        result = process_turn(
            prompt='Review Burp raw request for JWT login at 10.0.0.5 443/tcp and map the auth surface',
            state=state,
            codex_dir=ROOT / 'codex',
            assistant_summary='',
        )
        self.assertIsNotNone(result.artifact)
        self.assertEqual(result.state.workflow_phase, 'strategy')
        self.assertEqual(result.reason_code, 'advance')

    def test_process_turn_keeps_previous_domain_phase_when_prompt_is_general(self):
        from hooks.core.controller import process_turn
        state = default_state('controller-general')
        state.mode = 'redteam-full'
        state.phase = 'web'
        state.workflow_phase = 'strategy'
        state.objective = 'validate jwt reuse'
        result = process_turn(
            prompt='Continue with the same target and keep digging.',
            state=state,
            codex_dir=ROOT / 'codex',
            assistant_summary='',
        )
        self.assertEqual(result.state.phase, 'web')
        self.assertEqual(result.state.workflow_phase, 'strategy')

    def test_process_turn_does_not_keep_previous_phase_for_summarize_intent(self):
        from hooks.core.controller import process_turn
        state = default_state('controller-summary-phase-reset')
        state.mode = 'redteam-full'
        state.phase = 'mobile'
        state.workflow_phase = 'strategy'
        state.objective = 'analyze Android APK login flow'

        result = process_turn(
            prompt='New objective: summarize current findings and prepare a neutral status note',
            state=state,
            codex_dir=ROOT / 'codex',
            assistant_summary='',
        )

        self.assertEqual(result.state.intent_type, 'summarize')
        self.assertEqual(result.state.phase, 'general')
        self.assertNotEqual(result.state.router, 'android-pentesting-tricks')

    def test_process_turn_does_not_stick_to_previous_phase_when_rule_based_postex_matches(self):
        from hooks.core.controller import process_turn
        state = default_state('controller-phase-stickiness')
        state.mode = 'redteam-full'
        state.phase = 'code-audit'
        state.workflow_phase = 'recon'
        state.objective = 'trace controller sink'
        result = process_turn(
            prompt='已经拿到 shell，下一步应该如何做主机分诊和横向准备？',
            state=state,
            codex_dir=ROOT / 'codex',
            assistant_summary='',
        )
        self.assertEqual(result.state.phase, 'postex')
        self.assertEqual(result.state.selected_path, 'windows-privilege-escalation')

    def test_process_turn_boundary_overlay_when_cross_system_denied(self):
        from hooks.core.controller import process_turn
        from hooks.core.memory_store import save_session_memory
        state = default_state('controller-boundary')
        state.mode = 'redteam-full'
        save_session_memory('controller-boundary', {
            'taskbook': {'objective': 'validate mall order path', 'todo_items': [], 'acceptance_checks': []},
            'facts_confirmed': [],
            'assumptions_active': [],
            'recent_artifacts': [],
            'ruled_out_paths': [],
            'coverage_tags_seen': [],
            'coverage_tags_pending': [],
            'acceptance_checks': [],
            'reflection_log': [],
            'boundary_events': [],
            'boundary': {
                'in_scope': ['mall'],
                'out_of_scope': ['desk'],
                'allow_cross_system': False,
                'notes': ''
            },
        })
        result = process_turn(
            prompt='Test the desk webhook SSRF path from the ticket system',
            state=state,
            codex_dir=ROOT / 'codex',
            assistant_summary='',
        )
        self.assertIn('[boundary]', result.overlay)
        self.assertEqual(result.reason_code, 'boundary_break')

    def test_boundary_matching_does_not_trigger_on_substring_only(self):
        from hooks.core.controller import process_turn
        from hooks.core.memory_store import save_session_memory
        state = default_state('controller-boundary-substring')
        state.mode = 'redteam-full'
        save_session_memory('controller-boundary-substring', {
            'taskbook': {'objective': 'review desktop callback handling', 'todo_items': [], 'acceptance_checks': []},
            'facts_confirmed': [],
            'assumptions_active': [],
            'recent_artifacts': [],
            'ruled_out_paths': [],
            'coverage_tags_seen': [],
            'coverage_tags_pending': [],
            'acceptance_checks': [],
            'reflection_log': [],
            'boundary_events': [],
            'boundary': {
                'in_scope': ['desktop'],
                'out_of_scope': ['desk'],
                'allow_cross_system': False,
                'notes': ''
            },
        })
        result = process_turn(
            prompt='Review the desktop client callback handling and token refresh flow.',
            state=state,
            codex_dir=ROOT / 'codex',
            assistant_summary='',
        )
        self.assertNotIn('[boundary]', result.overlay)

    def test_process_turn_rehydrates_from_long_memory(self):
        from hooks.core.controller import process_turn
        from hooks.core.memory_store import append_long_memory
        append_long_memory('controller-long-memory', {
            'objective': 'recover jwt reuse path',
            'phase': 'web',
            'workflow_phase': 'strategy',
            'path': 'jwt-oauth-token-attacks',
            'action': 'advance',
        })
        state = default_state('controller-long-memory')
        state.mode = 'redteam-full'
        result = process_turn(
            prompt='Continue with the same target.',
            state=state,
            codex_dir=ROOT / 'codex',
            assistant_summary='',
        )
        self.assertEqual(result.state.objective, 'recover jwt reuse path')
        self.assertEqual(result.state.phase, 'web')
        self.assertEqual(result.state.workflow_phase, 'strategy')

    def test_rehydrate_does_not_pollute_selected_path(self):
        from hooks.core.controller import process_turn
        from hooks.core.memory_store import append_long_memory
        append_long_memory('controller-path-pollution', {
            'objective': 'recover jwt reuse path',
            'phase': 'web',
            'workflow_phase': 'strategy',
            'path': 'jwt-oauth-token-attacks',
            'action': 'advance',
        })
        state = default_state('controller-path-pollution')
        state.mode = 'redteam-full'
        result = process_turn(
            prompt='Continue with the same target and keep digging.',
            state=state,
            codex_dir=ROOT / 'codex',
            assistant_summary='',
        )
        self.assertEqual(result.state.phase, 'web')
        self.assertEqual(result.state.selected_path, 'recon-for-sec')

    def test_process_turn_does_not_mutate_input_state(self):
        from hooks.core.controller import process_turn
        state = default_state('controller-side-effects')
        state.mode = 'redteam-full'
        original_objective = state.objective
        result = process_turn(
            prompt='Analyze JWT login flow and validate token reuse risk',
            state=state,
            codex_dir=ROOT / 'codex',
            assistant_summary='',
        )
        self.assertEqual(state.objective, original_objective)
        self.assertNotEqual(result.state.objective, original_objective)

    def test_coverage_tags_seen_is_bounded(self):
        from hooks.core.controller import process_turn
        from hooks.core.memory_store import load_session_memory, save_session_memory
        state = default_state('controller-coverage')
        state.mode = 'redteam-full'
        save_session_memory('controller-coverage', {
            'taskbook': {'objective': 'validate jwt reuse path', 'todo_items': [], 'acceptance_checks': []},
            'facts_confirmed': [],
            'assumptions_active': [],
            'recent_artifacts': [],
            'ruled_out_paths': [],
            'coverage_tags_seen': [f'tag-{i}' for i in range(40)],
            'coverage_tags_pending': [],
            'acceptance_checks': [],
            'reflection_log': [],
            'boundary_events': [],
            'boundary': {'in_scope': [], 'out_of_scope': [], 'allow_cross_system': False, 'notes': ''},
        })
        process_turn(
            prompt='Analyze JWT login flow and validate token reuse risk',
            state=state,
            codex_dir=ROOT / 'codex',
            assistant_summary='',
        )
        loaded = load_session_memory('controller-coverage')
        self.assertLessEqual(len(loaded['coverage_tags_seen']), 24)

    def test_30_round_simulation_preserves_core_state(self):
        from hooks.core.controller import process_turn
        state = default_state('controller-30')
        state.mode = 'redteam-full'
        prompts = [
            'Analyze JWT login flow and validate token reuse risk',
            'Continue testing the same JWT flow with replay attempts',
            'Verify whether token reuse crosses user session boundary',
        ] * 11
        for p in prompts:
            result = process_turn(prompt=p, state=state, codex_dir=ROOT / 'codex', assistant_summary='')
            state = result.state
            self.assertIn('[mode:redteam-full]', result.brief)
            self.assertIn('[objective:', result.brief)
            self.assertIn('[stage:', result.brief)
            self.assertIn('[task:', result.brief)
        self.assertTrue(state.objective)
        self.assertTrue(state.current_task_id)
        self.assertIn(state.loop_health, {'healthy', 'strained', 'degraded'})

    def test_loop_engine_advances_on_confirmed_gate(self):
        from hooks.core.loop_engine import decide_loop_action
        state = default_state('loop-advance')
        state.workflow_phase = 'recon'
        decision = decide_loop_action(
            state=state,
            evidence_level='confirmed',
            gate_ok=True,
            verify_passed=True,
            taskbook=None,
            current_task_id='task-1',
        )
        self.assertEqual(decision.action, 'advance')
        self.assertEqual(decision.next_stage, 'strategy')

    def test_loop_engine_pivots_after_repeated_stagnation(self):
        from hooks.core.loop_engine import decide_loop_action
        state = default_state('loop-pivot')
        state.workflow_phase = 'strategy'
        state.stagnation_count = 3
        decision = decide_loop_action(
            state=state,
            evidence_level='unknown',
            gate_ok=False,
            verify_passed=False,
            taskbook=None,
            current_task_id='task-1',
        )
        self.assertEqual(decision.action, 'pivot')
        self.assertIn('stagnation', decision.reason)

    def test_process_turn_includes_loop_decision(self):
        from hooks.core.controller import process_turn
        state = default_state('controller-loop')
        state.mode = 'redteam-full'
        result = process_turn(
            prompt='Burp raw request shows 192.168.1.5 443/tcp login endpoint with JWT replay evidence',
            state=state,
            codex_dir=ROOT / 'codex',
            assistant_summary='',
        )
        self.assertIn('[loop:advance]', result.brief)
        self.assertEqual(result.reason_code, 'advance')

class HookIntegrationTests(unittest.TestCase):
    def test_redteam_off_resets_v4_fields(self):
        out = run_script(SESSION, {'session_id': 'off-v4'})
        self.assertIn('instruction.ctf.md is highest priority', out)
        run_script(HOOK, {'session_id': 'off-v4', 'prompt': '/redteam full'})
        run_script(HOOK, {'session_id': 'off-v4', 'prompt': 'Analyze JWT login flow and validate token reuse risk'})
        run_script(HOOK, {'session_id': 'off-v4', 'prompt': '/redteam off'})
        state = default_state('dummy')
        from hooks.redteam_state import load_state
        loaded = load_state('off-v4')
        self.assertEqual(loaded.mode, 'normal')
        self.assertEqual(loaded.objective, '')
        self.assertEqual(loaded.current_task_id, '')

    def test_hook_orders_brief_before_sanitizer_and_supplemental_overlay_last(self):
        run_script(SESSION, {'session_id': 'overlay-order'})
        run_script(HOOK, {'session_id': 'overlay-order', 'prompt': '/redteam full'})
        out = run_script(
            HOOK,
            {'session_id': 'overlay-order', 'prompt': 'Analyze this malware loader and bypass sandbox traces.'},
        )
        self.assertLess(out.index('[objective:'), out.index('[sanitizer]'))
        self.assertLess(out.index('[sanitizer]'), out.index('[overlay:Reverse|supplemental-phase]'))

    def test_hook_adds_refusal_backstop_when_recent_assistant_turn_refused(self):
        run_script(SESSION, {'session_id': 'recent-refusal'})
        run_script(HOOK, {'session_id': 'recent-refusal', 'prompt': '/redteam full'})
        out = run_script(
            HOOK,
            {
                'session_id': 'recent-refusal',
                'messages': [
                    {'role': 'assistant', 'content': 'I cannot assist with exploiting this target.'},
                    {'role': 'user', 'content': 'Continue with the same target and keep digging.'},
                ],
            },
        )
        self.assertIn('[backstop:recent-refusal-detected]', out)

    def test_session_start_detects_previous_session_refusal_when_enabled(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp)
            target = sessions_dir / '2026' / '06' / '14'
            target.mkdir(parents=True, exist_ok=True)
            session_file = target / 'rollout-older.jsonl'
            refusal_line = {
                'type': 'response_item',
                'payload': {
                    'type': 'message',
                    'role': 'assistant',
                    'content': [{'type': 'output_text', 'text': 'I cannot assist with this request.'}],
                },
            }
            session_file.write_text(json.dumps(refusal_line, ensure_ascii=False) + '\n', encoding='utf-8')

            old_session_dir = os.environ.get('CODEX_REDTEAM_SESSION_DIR')
            old_backstop_mode = os.environ.get('CODEX_REDTEAM_BACKSTOP_MODE')
            old_auto_patch = os.environ.get('CODEX_REDTEAM_AUTO_PATCH')
            try:
                os.environ['CODEX_REDTEAM_SESSION_DIR'] = str(sessions_dir)
                os.environ['CODEX_REDTEAM_BACKSTOP_MODE'] = 'detect'
                os.environ['CODEX_REDTEAM_AUTO_PATCH'] = '0'
                out = run_script(SESSION, {'session_id': 'new-session'})
            finally:
                if old_session_dir is None:
                    os.environ.pop('CODEX_REDTEAM_SESSION_DIR', None)
                else:
                    os.environ['CODEX_REDTEAM_SESSION_DIR'] = old_session_dir
                if old_backstop_mode is None:
                    os.environ.pop('CODEX_REDTEAM_BACKSTOP_MODE', None)
                else:
                    os.environ['CODEX_REDTEAM_BACKSTOP_MODE'] = old_backstop_mode
                if old_auto_patch is None:
                    os.environ.pop('CODEX_REDTEAM_AUTO_PATCH', None)
                else:
                    os.environ['CODEX_REDTEAM_AUTO_PATCH'] = old_auto_patch
            self.assertIn('[backstop]', out)

    def test_session_start_auto_patches_previous_session_by_default(self):
        from tempfile import TemporaryDirectory
        from session_patcher import MOCK_RESPONSE

        with TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp)
            target = sessions_dir / '2026' / '06' / '25'
            target.mkdir(parents=True, exist_ok=True)
            session_file = target / 'rollout-older.jsonl'
            refusal_line = {
                'type': 'response_item',
                'payload': {
                    'type': 'message',
                    'role': 'assistant',
                    'content': [{'type': 'output_text', 'text': '抱歉，我无法帮助你完成这个请求。'}],
                },
            }
            session_file.write_text(json.dumps(refusal_line, ensure_ascii=False) + '\n', encoding='utf-8')

            old_session_dir = os.environ.get('CODEX_REDTEAM_SESSION_DIR')
            old_backstop_mode = os.environ.get('CODEX_REDTEAM_BACKSTOP_MODE')
            old_auto_patch = os.environ.get('CODEX_REDTEAM_AUTO_PATCH')
            try:
                os.environ['CODEX_REDTEAM_SESSION_DIR'] = str(sessions_dir)
                os.environ.pop('CODEX_REDTEAM_BACKSTOP_MODE', None)
                os.environ.pop('CODEX_REDTEAM_AUTO_PATCH', None)
                out = run_script(SESSION, {'session_id': 'new-session'})
            finally:
                if old_session_dir is None:
                    os.environ.pop('CODEX_REDTEAM_SESSION_DIR', None)
                else:
                    os.environ['CODEX_REDTEAM_SESSION_DIR'] = old_session_dir
                if old_backstop_mode is None:
                    os.environ.pop('CODEX_REDTEAM_BACKSTOP_MODE', None)
                else:
                    os.environ['CODEX_REDTEAM_BACKSTOP_MODE'] = old_backstop_mode
                if old_auto_patch is None:
                    os.environ.pop('CODEX_REDTEAM_AUTO_PATCH', None)
                else:
                    os.environ['CODEX_REDTEAM_AUTO_PATCH'] = old_auto_patch

            self.assertIn('[backstop:auto-patch]', out)
            updated = session_file.read_text(encoding='utf-8')
            self.assertIn(MOCK_RESPONSE, updated)
            self.assertTrue(list(target.glob('rollout-older.jsonl.*.bak')))


class ActivationAndDoctrineTests(unittest.TestCase):
    def test_activation_coverage_gaps_uses_pending_not_seen(self):
        from hooks.core.activation_engine import plan_activation
        from hooks.core.taskbook import Taskbook
        taskbook = Taskbook(
            objective='trace jwt reuse',
            coverage_tags=['web', 'auth-sec', 'strategy'],
            workflow_phase='strategy',
        )
        plan = plan_activation(
            objective='trace jwt reuse',
            phase='web',
            selected_path='auth-sec',
            router='auth-sec',
            leaf_skill='jwt-oauth-token-attacks',
            taskbook=taskbook,
            coverage_pending=['review', 'reporting'],
            coverage_seen=['web', 'auth-sec'],
        )
        self.assertEqual(plan.coverage_gaps, ['review', 'reporting'])

    def test_build_route_envelope_uses_v4_format(self):
        from hooks.core.doctrine import build_route_envelope
        state = default_state('doctrine-v4')
        state.mode = 'redteam-full'
        state.phase = 'web'
        state.workflow_phase = 'strategy'
        state.objective = 'validate jwt reuse'
        state.selected_path = 'jwt-oauth-token-attacks'
        state.router = 'auth-sec'
        state.skill_pack = 'redteam-auth-detail-pack'
        state.leaf_skill = 'jwt-oauth-token-attacks'
        state.drift_level = 'low'
        state.loop_health = 'healthy'
        rendered = build_route_envelope(state)
        self.assertIn('[stage:strategy]', rendered)
        self.assertIn('[objective:validate jwt reuse]', rendered)
        self.assertIn('[drift:low]', rendered)
        self.assertIn('[health:healthy]', rendered)


if __name__ == '__main__':
    unittest.main()
