import unittest
import json
import tempfile
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace

from audiobook_generator.audio_core.casting import apply_casting, interaction_graph, locked_voices_from_script, optimize_casting, validate_casting_file


class CastingCoreTest(unittest.TestCase):
    def bank(self):
        return {"provider": "openai", "voices": {
            "冰糖": {"verified": True, "embeddings": {"a": [1, 0], "b": [1, .01]}},
            "茉莉": {"verified": True, "embeddings": {"a": [0, 1], "b": [.01, 1]}},
            "苏打": {"verified": True, "embeddings": {"a": [.99, .01], "b": [.99, .02]}}}}

    def complete_fit(self, roles):
        return {role: {voice: 0 for voice in self.bank()['voices']} for role in roles}

    def test_frequent_pair_gets_distinct_voice_and_lock_is_hard(self):
        result = optimize_casting(["a", "b", "c"], {("a", "b"): 10, ("b", "c"): 1},
                                  self.bank(), locked={"a": "冰糖"})
        self.assertEqual(result["roles"]["a"], "冰糖")
        self.assertEqual(result["roles"]["b"], "茉莉")

    def test_scarce_voices_are_reported_and_unverified_probes_rejected(self):
        bank = self.bank()
        bank["voices"].pop("茉莉")
        bank["voices"].pop("苏打")
        result = optimize_casting(["a", "b"], {("a", "b"): 1}, bank)
        self.assertEqual(set(result["shared_voices"]["冰糖"]), {"a", "b"})
        bank["voices"]["冰糖"]["verified"] = False
        with self.assertRaises(ValueError):
            optimize_casting(["a"], {}, bank)

    def test_narration_breaks_adjacency(self):
        chapter = SimpleNamespace(segments=[SimpleNamespace(role_id=r, pause_after_ms=0)
                                            for r in ("a", "b", "narrator", "a")])
        roles, graph = interaction_graph([chapter])
        self.assertEqual(graph, {("a", "b"): 1})
        self.assertEqual(roles, ["a", "b", "narrator"])

    def test_v2_entity_lock_uses_role_id_instead_of_profile_metadata(self):
        from tests.audiobook_generator.role_script.v2_io_test import _script
        from tests.audiobook_generator.audio_core.pipeline_test import plan_for
        from dataclasses import replace
        script, _ = _script()
        locks = locked_voices_from_script(script)
        self.assertEqual(locks, {"char_1": "茉莉"})
        plan = plan_for(("你好。",))
        unit = replace(plan.units[0], role_id="char_1")
        plan = replace(plan, units=(unit,))
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "casting.json"
            path.write_text(json.dumps({"schema_version": "mimo-casting-v1", "provider": "openai",
                                        "roles": {"char_1": "冰糖"}}))
            with self.assertRaisesRegex(ValueError, "锁定"):
                apply_casting(plan, path, locked=locks)

    def test_baselines_are_deterministic_and_still_preserve_locks(self):
        for strategy in ("random", "global", "fit"):
            fit = self.complete_fit(['a', 'b'])
            fit['b']['苏打'] = 1
            options = dict(locked={"a": "冰糖"}, strategy=strategy, seed=7,
                           fit_penalties=fit)
            first = optimize_casting(["a", "b"], {("a", "b"): 4}, self.bank(), **options)
            second = optimize_casting(["a", "b"], {("a", "b"): 4}, self.bank(), **options)
            self.assertEqual(first, second)
            self.assertEqual(first["roles"]["a"], "冰糖")

    def test_exclusive_narrator_is_preserved_by_all_strategies_and_local_search(self):
        roles = ['narrator', 'a', 'b', 'c']
        for strategy in ('interaction', 'global', 'fit', 'random'):
            with self.subTest(strategy=strategy):
                fit = self.complete_fit(roles)
                fit['b']['苏打'] = 1
                options = dict(narrator_exclusive=True, locked={'a': '冰糖'}, initial={'narrator': '冰糖'},
                    strategy=strategy, seed=7, fit_penalties=fit)
                result = optimize_casting(roles, {('a', 'b'): 10, ('b', 'c'): 3}, self.bank(), **options)
                self.assertEqual(result, optimize_casting(roles, {('a', 'b'): 10, ('b', 'c'): 3}, self.bank(), **options))
                self.assertEqual(result['roles']['a'], '冰糖')
                narrator = result['roles']['narrator']
                self.assertNotIn(narrator, [voice for role, voice in result['roles'].items() if role != 'narrator'])
                self.assertNotIn(narrator, result['shared_voices'])
                self.assertEqual(result['constraint_status']['narrator_exclusive'], 'satisfied')

    def test_infeasible_exclusive_narrator_reports_capacity_or_lock_conflict(self):
        bank = self.bank()
        bank['voices'] = {'冰糖': bank['voices']['冰糖']}
        with self.assertRaisesRegex(ValueError, '至少需要两个'):
            optimize_casting(['narrator', 'a'], {}, bank, narrator_exclusive=True)
        with self.assertRaisesRegex(ValueError, '锁定角色冲突：a'):
            optimize_casting(['narrator', 'a'], {}, self.bank(), narrator_exclusive=True,
                             locked={'narrator': '冰糖', 'a': '冰糖'})
        with self.assertRaisesRegex(ValueError, '均被其他角色锁定'):
            optimize_casting(['narrator', 'a', 'b', 'c'], {}, self.bank(), narrator_exclusive=True,
                             locked={'a': '冰糖', 'b': '茉莉', 'c': '苏打'})

    def test_scarce_character_voices_can_share_but_narration_remains_independent(self):
        bank = self.bank()
        bank['voices'].pop('苏打')
        roles = ['narrator'] + [f'character{i}' for i in range(6)]
        result = optimize_casting(roles, {}, bank, locked={'narrator': '冰糖'}, narrator_exclusive=True)
        self.assertEqual(result['roles']['narrator'], '冰糖')
        self.assertEqual(len(result['shared_voices']['茉莉']), 6)
        self.assertNotIn('冰糖', result['shared_voices'])
        bank['voices'].pop('茉莉')
        self.assertEqual(optimize_casting(['narrator'], {}, bank, narrator_exclusive=True)['roles'], {'narrator': '冰糖'})
        legacy = optimize_casting(['narrator', 'a'], {}, bank)
        self.assertEqual(legacy['constraint_status']['narrator_exclusive'], 'disabled')
        absent = optimize_casting(['a'], {}, bank, narrator_exclusive=True)
        self.assertEqual(absent['constraint_status']['narrator_exclusive'], 'not_applicable')

    def test_casting_file_rejects_tampered_exclusive_assignment_and_nonboolean_constraint(self):
        result = optimize_casting(['narrator', 'a'], {}, self.bank(), narrator_exclusive=True)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'casting.json'
            path.write_text(json.dumps(result))
            self.assertEqual(validate_casting_file(path)['roles'], result['roles'])
            result['roles']['a'] = result['roles']['narrator']
            path.write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, '违反旁白独占'):
                validate_casting_file(path)
            result['constraints']['narrator_exclusive'] = 'true'
            path.write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, '必须是布尔值'):
                validate_casting_file(path)

    def test_partial_casting_cannot_bypass_exclusivity_and_application_preserves_speed_and_text(self):
        from dataclasses import replace
        from tests.audiobook_generator.audio_core.pipeline_test import plan_for
        plan = plan_for(('开场。', '你好。'))
        unit = replace(plan.units[1], role_id='a', profile=replace(plan.units[1].profile,
                       provider_params={'voice': '冰糖', 'speed': 1.15}))
        plan = replace(plan, units=(plan.units[0], unit))
        value = {'schema_version': 'mimo-casting-v1', 'provider': 'openai',
                 'constraints': {'narrator_exclusive': True}, 'roles': {'narrator': '冰糖'}}
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'partial.json'
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, '应用选角后无法满足旁白独占'):
                apply_casting(plan, path)
            # 没有旁白台词的章节也必须保留全局预留音色。
            with self.assertRaisesRegex(ValueError, '应用选角后无法满足旁白独占'):
                apply_casting(replace(plan, units=(unit,)), path)
            value['roles'] = {'a': '茉莉'}
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, '必须包含旁白'):
                apply_casting(plan, path)
            value['roles']['narrator'] = '冰糖'
            path.write_text(json.dumps(value))
            applied = apply_casting(plan, path)
            self.assertEqual(applied.units[1].profile.provider_params, {'voice': '茉莉', 'speed': 1.15})
            self.assertEqual([u.text for u in applied.units], [u.text for u in plan.units])
            self.assertEqual(plan.units[1].profile.provider_params['voice'], '冰糖')

    def test_cli_exclusive_flag_preserves_v2_lock_and_writes_usable_casting_file(self):
        from audiobook_generator.audio_core.__main__ import main
        from audiobook_generator.role_script.deepseek_splitter import role_script_to_dict
        from tests.audiobook_generator.role_script.v2_io_test import _script
        script, _ = _script()
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / 'script.json').write_text(json.dumps(role_script_to_dict(script)))
            (root / 'bank.json').write_text(json.dumps({**self.bank(), 'languages': ['zh']}))
            output = root / 'casting.json'
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = main(['cast', '--script', str(root / 'script.json'), '--bank', str(root / 'bank.json'),
                             '--narrator-exclusive', '--language', 'zh', '--output', str(output)])
            self.assertEqual(code, 0)
            result = json.loads(stdout.getvalue())
            self.assertEqual(result['roles']['char_1'], '茉莉')
            self.assertNotEqual(result['roles']['narrator'], '茉莉')
            self.assertTrue(validate_casting_file(output)['constraints']['narrator_exclusive'])

    def test_verified_requires_actual_boolean_and_exclusive_option_is_typed(self):
        bank = self.bank()
        bank['voices']['冰糖']['verified'] = 'false'
        with self.assertRaisesRegex(ValueError, '先核验'):
            optimize_casting(['narrator'], {}, bank)
        with self.assertRaisesRegex(ValueError, '必须是布尔值'):
            optimize_casting(['narrator'], {}, self.bank(), narrator_exclusive='true')

    def test_small_lock_combinations_match_exhaustive_exclusivity_feasibility(self):
        import itertools
        bank = self.bank()
        bank['voices'].pop('苏打')
        voices = sorted(bank['voices'])
        roles = ['narrator', 'a', 'b']
        for choices in itertools.product([None, *voices], repeat=len(roles)):
            locked = {role: voice for role, voice in zip(roles, choices) if voice is not None}
            has_solution = any(all(values[roles.index(role)] == voice for role, voice in locked.items())
                               and values[0] != values[1] and values[0] != values[2]
                               for values in itertools.product(voices, repeat=len(roles)))
            with self.subTest(locked=locked):
                if not has_solution:
                    with self.assertRaises(ValueError):
                        optimize_casting(roles, {('a', 'b'): 3}, bank, locked=locked, narrator_exclusive=True)
                else:
                    result = optimize_casting(roles, {('a', 'b'): 3}, bank, locked=locked, narrator_exclusive=True)
                    self.assertTrue(all(result['roles'][role] == voice for role, voice in locked.items()))
                    self.assertNotEqual(result['roles']['narrator'], result['roles']['a'])
                    self.assertNotEqual(result['roles']['narrator'], result['roles']['b'])

    def test_unrated_voice_or_role_is_never_treated_as_zero_penalty(self):
        incomplete = {'a': {'冰糖': 2, '茉莉': 1}, 'b': {'冰糖': 1, '茉莉': 2}}
        missing_role = {'a': self.complete_fit(['a'])['a']}
        for strategy in ('interaction', 'global', 'random', 'fit'):
            for table in (incomplete, missing_role, {}):
                with self.subTest(strategy=strategy, table=table):
                    with self.assertRaisesRegex(ValueError, '完整覆盖'):
                        optimize_casting(['a', 'b'], {('a', 'b'): 1}, self.bank(),
                                         strategy=strategy, fit_penalties=table)
        # 不启用适配评分仍可使用原有三种策略，但 fit 不允许缺少表格。
        self.assertEqual(optimize_casting(['a'], {}, self.bank())['fit_penalty_status'], 'disabled')
        with self.assertRaisesRegex(ValueError, '需要人工审查'):
            optimize_casting(['a'], {}, self.bank(), strategy='fit')

    def test_fit_rejects_invalid_cells_and_unknown_candidates(self):
        for bad in (None, True, '0', -1, float('nan'), float('inf')):
            fit = self.complete_fit(['a'])
            fit['a']['苏打'] = bad
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, '有限非负数'):
                optimize_casting(['a'], {}, self.bank(), strategy='fit', fit_penalties=fit)
        for table in ([], {'a': []}, {'a': {**self.complete_fit(['a'])['a'], '未知声音': 0}},
                      {**self.complete_fit(['a']), '未知角色': {}}):
            with self.subTest(table=table), self.assertRaisesRegex(ValueError, '完整覆盖'):
                optimize_casting(['a'], {}, self.bank(), strategy='fit', fit_penalties=table)

    def test_complete_fit_scores_drive_assignment_without_changing_locks_or_input(self):
        import copy
        fit = self.complete_fit(['a', 'b'])
        fit['b'].update({'冰糖': 2, '苏打': 1, '茉莉': 0})
        original = copy.deepcopy(fit)
        result = optimize_casting(['a', 'b'], {('a', 'b'): 10}, self.bank(), strategy='fit',
                                  fit_penalties=fit, locked={'a': '冰糖'})
        self.assertEqual(result['roles'], {'a': '冰糖', 'b': '茉莉'})
        self.assertEqual(result['fit_penalties'], original)
        self.assertEqual(result['fit_penalty_status'], 'complete')
        self.assertEqual(fit, original)
        # 明确填零代表人工声明没有适配偏好，不能与缺项混淆。
        zero = self.complete_fit(['a', 'b'])
        result = optimize_casting(['a', 'b'], {}, self.bank(), strategy='fit', fit_penalties=zero)
        self.assertEqual(result['objective'], 0)

    def test_cli_rejects_partial_fit_before_writing_and_accepts_complete_table(self):
        from unittest.mock import patch
        from audiobook_generator.audio_core.__main__ import main
        from audiobook_generator.role_script.deepseek_splitter import role_script_to_dict
        from tests.audiobook_generator.role_script.v2_io_test import _script
        script, _ = _script()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'script.json').write_text(json.dumps(role_script_to_dict(script)))
            (root / 'bank.json').write_text(json.dumps({**self.bank(), 'languages': ['zh']}))
            fit_path, output = root / 'fit.json', root / 'casting.json'
            args = ['cast', '--script', str(root / 'script.json'), '--bank', str(root / 'bank.json'),
                    '--language', 'zh', '--strategy', 'fit', '--fit-penalties', str(fit_path),
                    '--output', str(output)]
            fit_path.write_text(json.dumps({'narrator': {'冰糖': 0}}))
            with patch('openai.OpenAI') as remote:
                for existing in (False, True):
                    if existing:
                        output.write_text('existing casting stays intact')
                    with contextlib.redirect_stderr(io.StringIO()) as stderr:
                        self.assertEqual(main(args), 2)
                    self.assertIn('完整覆盖', stderr.getvalue())
                    if existing:
                        self.assertEqual(output.read_text(), 'existing casting stays intact')
                    else:
                        self.assertFalse(output.exists())
                fit_path.write_text(json.dumps(self.complete_fit(['narrator', 'char_1'])))
                with contextlib.redirect_stdout(io.StringIO()) as stdout:
                    self.assertEqual(main(args), 0)
                remote.assert_not_called()
            result = json.loads(stdout.getvalue())
            self.assertEqual(result['fit_penalty_status'], 'complete')
            self.assertEqual(result['roles']['char_1'], '茉莉')
            self.assertEqual(validate_casting_file(output)['fit_penalties'], result['fit_penalties'])

    def test_small_exact_search_escapes_initial_voice_local_minimum(self):
        import itertools
        import math
        from audiobook_generator.audio_core.casting import voice_distance
        bank = self.bank()
        bank['voices'].pop('苏打')
        roles = ['alex', 'blair', 'casey']
        edges = {('alex', 'blair'): 6, ('alex', 'casey'): 1, ('blair', 'casey'): 2}
        initial = dict.fromkeys(roles, '冰糖')
        result = optimize_casting(roles, edges, bank, initial=initial)
        def score(assignment):
            return sum(w * math.exp(-voice_distance(bank['voices'][assignment[a]],
                       bank['voices'][assignment[b]]) / .25) for (a, b), w in edges.items()) + \
                   .05 * sum(assignment[r] != initial[r] for r in roles)
        all_assignments = [dict(zip(roles, values)) for values in itertools.product(bank['voices'], repeat=3)]
        self.assertAlmostEqual(result['objective'], min(score(a) for a in all_assignments))
        self.assertEqual(result['roles'], {'alex': '冰糖', 'blair': '茉莉', 'casey': '冰糖'})
        self.assertEqual(result['search']['method'], 'exact_enumeration')
        self.assertEqual(result['search']['candidate_assignments'], 8)
        self.assertEqual(result['search']['optimality'], 'global_for_current_proxy_objective')

    def test_exact_search_matches_independent_exhaustive_objectives_with_hard_constraints(self):
        import itertools
        import math
        from audiobook_generator.audio_core.casting import voice_distance
        bank = self.bank()
        roles = ['narrator', 'a', 'b', 'c']
        interaction = {('a', 'b'): 6, ('b', 'c'): 2}
        fit = self.complete_fit(roles)
        fit['b']['冰糖'] = 2
        fit['c']['茉莉'] = 3
        initial = dict.fromkeys(roles, '冰糖')
        for strategy in ('interaction', 'global', 'fit'):
            for locked in ({}, {'a': '冰糖'}, {'narrator': '苏打', 'b': '冰糖'}):
                with self.subTest(strategy=strategy, locked=locked):
                    result = optimize_casting(roles, interaction, bank, initial=initial,
                        fit_penalties=fit, locked=locked, narrator_exclusive=True, strategy=strategy)
                    if strategy == 'global':
                        edges = {pair: 1 for pair in itertools.combinations(sorted(roles), 2)}
                    else:
                        edges = {} if strategy == 'fit' else interaction
                    scores = []
                    feasible = 0
                    for values in itertools.product(bank['voices'], repeat=len(roles)):
                        a = dict(zip(roles, values))
                        if any(a[r] != voice for r, voice in locked.items()):
                            continue
                        if any(a[r] == a['narrator'] for r in roles if r != 'narrator'):
                            continue
                        feasible += 1
                        scores.append(sum(w * math.exp(-voice_distance(bank['voices'][a[x]],
                            bank['voices'][a[y]]) / .25) for (x, y), w in edges.items()) +
                            .1 * sum(fit[r][a[r]] for r in roles) +
                            .05 * sum(a[r] != initial[r] for r in roles))
                    self.assertAlmostEqual(result['objective'], min(scores))
                    self.assertEqual(result['search']['candidate_assignments'], feasible)
                    self.assertEqual(result['search']['method'], 'exact_enumeration')

    def test_search_limit_accounts_for_locks_and_preserves_random_baseline(self):
        from unittest.mock import patch
        from audiobook_generator.audio_core import casting
        bank = self.bank()
        bank['voices'].pop('苏打')
        roles = ['a', 'b', 'c']
        with patch.object(casting, 'EXACT_SEARCH_LIMIT', 4):
            heuristic = optimize_casting(roles, {}, bank)
            exact = optimize_casting(roles, {}, bank, locked={'a': '冰糖'})
            self.assertEqual(heuristic['search']['method'], 'greedy_local_search')
            self.assertTrue(heuristic['search']['exceeds_exact_limit'])
            self.assertEqual(heuristic['search']['optimality'], 'not_proven')
            self.assertEqual(exact['search']['method'], 'exact_enumeration')
            self.assertEqual(exact['search']['candidate_assignments'], 4)
        random = optimize_casting(roles, {}, bank, strategy='random', seed=42)
        self.assertEqual(random, optimize_casting(roles, {}, bank, strategy='random', seed=42))
        self.assertEqual(random['search']['method'], 'random')
        self.assertEqual(random['search']['optimality'], 'not_optimized')


if __name__ == "__main__":
    unittest.main()
