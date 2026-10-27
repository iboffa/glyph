"""Run the existing test corpus against native checking and native C emission.

The reference frontend supplies typed Python ASTs for test compatibility, but
acceptance and diagnostics are cross-checked and every Emitter call uses glyphc.
No Python frontend/code generator is invoked by the native executable itself.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from glyph import syntax, checker, backend


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('compiler', type=Path)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/selfhost-corpus')
    args = parser.parse_args()
    executable = args.compiler.resolve()
    os.environ['GLYPH_SELFHOST'] = str(executable)
    scratch = args.output_dir.resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    original_parse, original_check = syntax.parse, checker.check
    cache = {}
    counters = {'native_checks': 0, 'native_emissions': 0, 'parser_rejections': 0}

    def invoke(source, command):
        key = (source, command)
        if key not in cache:
            digest = hashlib.sha256(source.encode()).hexdigest()
            path = scratch / (digest + '.gly')
            path.write_text(source, encoding='utf-8')
            output = path.with_suffix('.c')
            proc = subprocess.run([str(executable), command, str(path), '-o', str(output),
                                   '--runtime-dir', str(ROOT / 'glyph'), '--json'],
                                  capture_output=True, text=True, timeout=30)
            if proc.returncode not in (0, 1):
                raise AssertionError(f'native compiler crashed/trapped ({proc.returncode}) for {path}: {proc.stderr}')
            cache[key] = (proc, output)
            counters['native_checks' if command == 'check' else 'native_emissions'] += 1
        return cache[key]

    class SourceDeclarations(list):
        def __init__(self, declarations, source):
            super().__init__(declarations)
            self.source = source

    def parse(source):
        try:
            declarations = original_parse(source)
        except syntax.Diagnostic:
            proc, _ = invoke(source, 'check')
            if proc.returncode == 0:
                raise AssertionError('native parser accepted a source rejected by the reference parser')
            # Random malformed strings can encounter a different first error;
            # the explicit checker fixtures below require matching error codes.
            diagnostic = json.loads(proc.stderr)
            if not diagnostic['code'].startswith('G'):
                raise AssertionError(proc.stderr)
            counters['parser_rejections'] += 1
            raise
        return SourceDeclarations(declarations, source)

    def check(declarations):
        proc, _ = invoke_declarations(declarations, 'check')
        reference_error = None
        try:
            result = original_check(declarations)
        except syntax.Diagnostic as error:
            reference_error = error
        if proc.returncode == 0:
            if reference_error is not None:
                raise AssertionError(f'native checker accepted {reference_error.code}: {getattr(declarations, "source", declarations)}')
            return result
        native_error = json.loads(proc.stderr)
        if reference_error is None:
            raise AssertionError(f'native checker rejected valid source: {proc.stderr}')
        if native_error['code'] != reference_error.code:
            raise AssertionError(f'diagnostic disagreement: native={native_error}, reference={reference_error.code}')
        pos = native_error['span']['start']
        end = native_error['span']['end']['column']
        raise syntax.Diagnostic(native_error['code'], native_error['message'],
                                syntax.Token('', pos['line'], pos['column'], end))

    def invoke_declarations(declarations, command):
        if hasattr(declarations, 'source'):
            return invoke(declarations.source, command)
        # A resolved Program carries its original entry path. Keep its graph
        # in place so relative imports are checked by the native loader too.
        path = declarations.paths[0]
        output = scratch / (hashlib.sha256(str(path).encode()).hexdigest() + '.c')
        proc = subprocess.run([str(executable), command, str(path), '-o', str(output),
                               '--runtime-dir', str(ROOT / 'glyph'), '--json'],
                              capture_output=True, text=True, timeout=30)
        if proc.returncode not in (0, 1):
            raise AssertionError(f'native compiler crashed/trapped for {path}: {proc.stderr}')
        counters['native_checks' if command == 'check' else 'native_emissions'] += 1
        return proc, output

    def emit(self, declarations, filename='<source>'):
        proc, path = invoke_declarations(declarations, 'emit-c')
        if proc.returncode:
            raise AssertionError(proc.stderr)
        return path.read_text(encoding='utf-8')

    syntax.parse, checker.check, backend.Emitter.emit = parse, check, emit
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    for name in ('test_glyph', 'test_records', 'test_reductions', 'test_gui', 'test_systems', 'test_results', 'test_io_json', 'test_services', 'test_service_failures', 'test_selfhost', 'test_modules', 'test_gc', 'test_collections', 'test_abstractions', 'test_concurrency'):
        suite.addTests(loader.loadTestsFromName(name))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {**counters, 'tests': result.testsRun, 'skipped': len(result.skipped),
              'failures': len(result.failures), 'errors': len(result.errors),
              'success': result.wasSuccessful(), 'compiler': str(executable)}
    (scratch / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
