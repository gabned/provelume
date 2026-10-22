"""Trusted stdlib-only byte audit and volume construction; run in the offline lab."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import re
import stat
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import unquote


def sha(data):
    return hashlib.sha256(data).hexdigest()


PATTERNS = {
    'GITHUB_CREDENTIAL': rb'gh[pousr]_[A-Za-z0-9]{24,}|github_pat_[A-Za-z0-9_]{35,}',
    'CREDENTIAL_HTTP_HEADER': rb'(?im)^[ \t]*(?:authorization|proxy-authorization|cookie|set-cookie):[ \t]*[^\r\n]+',
    'CREDENTIAL_ENV_ASSIGNMENT': rb'(?im)(?:GH_TOKEN|GITHUB_TOKEN|AWS_SECRET_ACCESS_KEY|OPENAI_API_KEY)[ \t]*=[ \t]*[^\s\x00]{12,}',
    'CREDENTIAL_JSON_VALUE': rb'(?i)["\x27](?:GH_TOKEN|GITHUB_TOKEN|AWS_SECRET_ACCESS_KEY|OPENAI_API_KEY)["\x27][ \t]*:[ \t]*["\x27][^"\x27\s]{12,}',
    'PRIVATE_KEY_PAYLOAD': rb'-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----[\r\n]+[A-Za-z0-9+/=\r\n]{80,}',
    'AWS_ACCESS_KEY': rb'AKIA[0-9A-Z]{16}',
    'URL_USERINFO': rb'https?://[^\s/"<>]{1,200}:[^\s/@"<>]{1,200}@',
}
URL = re.compile(rb'https?://[^\s"<>\\]{1,8192}', re.I)
SIGNED = re.compile(r'[?&](?:sig|signature|x-amz-signature|x-amz-credential|x-goog-signature|jwt|token|access_token|sas)=[^&#\s]{8,}', re.I)


class Audit:
    def __init__(self, package, fixture_input):
        self.package = package
        self.findings = []
        self.counts = {'files': 0, 'logical_bytes': 0, 'zip_members': 0, 'expanded_bytes': 0}
        self.fixtures = []
        for row in fixture_input['files']:
            data = checked_bytes(package, row)
            self.fixtures.append((row['provenance']['path'], data,
                                  row['provenance']['blob'], row['provenance']['commit']))

    def classify(self, data, name, kind, match):
        exact = [(path, value, blob, commit) for path, value, blob, commit in self.fixtures
                 if data == value]
        if exact:
            return {'classification': 'EXACT_IMMUTABLE_PUBLIC_SYNTHETIC_TEST_SOURCE',
                    'public_source_files': [{'path': path, 'sha256': sha(value),
                                             'git_blob': blob, 'commit': commit}
                                            for path, value, blob, commit in exact]}
        if kind == 'URL_USERINFO':
            references = [(path, value, blob, commit)
                          for path, value, blob, commit in self.fixtures
                          if match.group() in value]
            if not references:
                return None
            contexts = []
            if name.endswith('.json'):
                try:
                    def strings(value):
                        if isinstance(value, str):
                            return [value]
                        if isinstance(value, list):
                            return [text for row in value for text in strings(row)]
                        if isinstance(value, dict):
                            return [text for row in value.values() for text in strings(row)]
                        return []
                    contexts = [value for value in strings(json.loads(data))
                                if match.group().decode() in value]
                except (ValueError, UnicodeError):
                    return None
            else:
                first = data.rfind(b'\n', 0, match.start()) + 1
                last = data.find(b'\n', match.end())
                contexts = [data[first:last if last >= 0 else len(data)].decode(errors='replace')]
            if contexts and all('::test' in value
                                and any(path in value for path, *_ in references)
                                for value in contexts):
                return {'classification': 'PUBLIC_SYNTHETIC_TEST_NODE_IDENTIFIER',
                        'public_source_files': [{'path': path, 'sha256': sha(value),
                                                 'git_blob': blob, 'commit': commit}
                                                for path, value, blob, commit in references]}
        if kind == 'CREDENTIAL_HTTP_HEADER' and name.endswith('.py'):
            try:
                line = data.count(b'\n', 0, match.start()) + 1
                for node in ast.walk(ast.parse(data.decode())):
                    if getattr(node, 'lineno', None) != line:
                        continue
                    if isinstance(node, ast.arg) and node.annotation is not None:
                        target = node.arg
                    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                        target = node.target.id
                    else:
                        continue
                    if target.lower() in ('cookie', 'authorization'):
                        return {'classification': 'PYTHON_TYPE_ANNOTATION_NOT_HTTP_HEADER',
                                'member_sha256': sha(data), 'line': line,
                                'ast_kind': type(node).__name__}
            except (ValueError, UnicodeError, SyntaxError):
                return None
        return None

    def scan(self, data, name, depth=0):
        self.counts['files'] += 1
        self.counts['logical_bytes'] += len(data)
        for kind, expression in PATTERNS.items():
            for match in re.finditer(expression, data):
                row = {'path': name, 'category': kind, 'offset': match.start(),
                       'matched_bytes_sha256': sha(match.group())}
                proof = self.classify(data, name, kind, match)
                if proof:
                    row.update(proof)
                self.findings.append(row)
        for match in URL.finditer(data):
            decoded = unquote(match.group().decode(errors='replace').replace('&amp;', '&'))
            if SIGNED.search(decoded):
                row = {'path': name, 'category': 'SIGNED_OR_CREDENTIAL_URL',
                       'offset': match.start(), 'matched_bytes_sha256': sha(match.group())}
                # The first isolated audit retained two negative URL fixtures as
                # unresolved because this branch omitted exact-source provenance.
                # Keep the finding; classify only whole byte-pinned public source.
                proof = self.classify(data, name, 'SIGNED_OR_CREDENTIAL_URL', match)
                if proof and proof['classification'] == 'EXACT_IMMUTABLE_PUBLIC_SYNTHETIC_TEST_SOURCE':
                    line = data.count(b'\n', 0, match.start()) + 1
                    functions = [node.name for node in ast.walk(ast.parse(data.decode()))
                                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                                 and node.lineno <= line <= node.end_lineno]
                    row.update(proof, source_line=line, public_test_functions=functions)
                self.findings.append(row)
        if data[:4] != b'PK\x03\x04':
            return
        if depth >= 8:
            raise ValueError('Nested ZIP depth exceeds complete-audit bound')
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                if member.file_size > 512 * 1024**2:
                    raise ValueError('ZIP member exceeds complete-audit byte bound')
                if re.search(r'(^|/)(?:\.git/config|\.aws/credentials|\.ssh/id_[^/]*)$',
                             member.filename.replace('\\', '/')):
                    self.findings.append({'path': name + '::' + member.filename,
                                          'category': 'FORBIDDEN_NESTED_CREDENTIAL_MATERIAL'})
                value = archive.read(member)
                self.counts['zip_members'] += 1
                self.counts['expanded_bytes'] += len(value)
                self.scan(value, name + '::' + member.filename, depth + 1)


def safe_path(package, relative):
    parts = PurePosixPath(relative)
    if parts.is_absolute() or '..' in parts.parts or '\\' in relative:
        raise ValueError('Unsafe package relative path')
    path = package / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(package.resolve()):
        raise ValueError('Nonregular or escaped package input')
    return path


def checked_bytes(package, row):
    path = safe_path(package, row['path'])
    if path.name.endswith(('.connector.json', '.download.json', '.download.headers')):
        raise ValueError('Forbidden transport envelope in package')
    data = path.read_bytes()
    if len(data) != row['bytes'] or sha(data) != row['sha256']:
        raise ValueError('Package byte inventory mismatch')
    return data


def environment():
    forbidden = ('GH_TOKEN', 'GITHUB_TOKEN', 'OPENAI_API_KEY', 'AWS_ACCESS_KEY_ID',
                 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'SSH_AUTH_SOCK',
                 'CODEX_HOME', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')
    present = [name for name in forbidden if os.environ.get(name)]
    docker = Path('/var/run/docker.sock').exists()
    operator_home = any(Path(path).exists() for path in ('/root/.gitconfig', '/root/.ssh',
                                                        '/root/.aws', '/workspace/.git/config'))
    if present or docker or operator_home:
        raise ValueError('Required credential-free audit boundary absent')
    return {'observed_at': datetime.now(UTC).isoformat(),
            'credential_or_proxy_variable_names_present': present,
            'docker_socket_present': docker, 'operator_home_material_present': operator_home,
            'network_namespace': os.readlink('/proc/self/ns/net'),
            'network_routes': Path('/proc/net/route').read_text(),
            'python': sys.version, 'python_isolated': bool(sys.flags.isolated),
            'note': 'Host isolation receipt independently establishes mounts and offline namespace.'}


README = '''PRODUCT a29 PREMERGE evidence package. No publication or release signal.

Download every volume listed in package-index.json. Check each volume SHA-256
against that index, extract all outer volumes into one fresh directory, then run:
  python -I verify-package.py --package RESTORED_DIRECTORY --verify-only

Every original evidence file retains exact bytes. Inner original ZIPs are stored
as whole files and are not repacked. manifest.json lists payload bytes, SHA-256,
source paths and provenance. Original receipt-relative subdirectories are retained;
absolute historical workspace references describe where checks actually ran and
are not rewritten as new execution. No executable candidate or artifact code is
run by verification: it hashes bytes and reads ZIP members for CRC/audit only.

The final native source is a29ce258278bb76bb9f92c11131360a22cf18d5b. Diagnostic
source5af1bf5 remains NOT_QUALIFIED and cannot be reused as final qualification.
Original409CPU FAIL and408HTTP403 remain unchanged; the report links their ledgers.
PREMERGE observations do not establish POSTMERGE acceptance. No timestamp, status,
conclusion or historical cause is inferred from a completed step or available log.

Allowlist: immutable plan/source proofs, original ABBA ZIP/report/scalar analysis,
actual final native receipt and raw streams/environment, accepted CPU replay and
original CPU ZIPs, final Windows proof, original ready-fresh HTTP observations,
all final original logs/ZIPs and complete verification, actual final preflight and
preview acquisition metadata. Public synthetic fixture source is included only to
prove audit false positives by exact Git blob/hash and pytest-node provenance.

Exclusions: ALL connector/download envelopes and signed download URLs, credential
environment/home, .git/config, credential request headers, private reuse maps,
unrelated caches and private originals. Those private originals remain unchanged
outside this package. No original is sanitized or relabelled to enter this set.
The earlier operator-host scan is PRELIMINARY_UNISOLATED and is not the final audit.
The final complete byte/ZIP audit and outer volume construction run in the isolated
offline lab; review-report.json and its separate host receipt retain that boundary.
Audit findings expose fingerprints and public-source provenance, never token values.
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    package = args.package
    manifest = json.loads((package / 'manifest.json').read_text())
    rows = manifest['files']
    if len({row['path'] for row in rows}) != len(rows):
        raise ValueError('Duplicate package path')
    if args.verify_only:
        for row in rows:
            checked_bytes(package, row)
        print(json.dumps({'result': 'EXACT_BYTES_VERIFIED', 'files': len(rows),
                          'bytes': sum(row['bytes'] for row in rows)}))
        return
    if args.output is None:
        raise ValueError('Audit output required')
    started = datetime.now(UTC).isoformat()
    boundary = environment()
    fixtures = json.loads((package / 'fixture-audit-input.json').read_text())
    audit = Audit(package, fixtures)
    for row in rows:
        audit.scan(checked_bytes(package, row), row['path'])
    unresolved = [row for row in audit.findings if 'classification' not in row]
    report = {'schema': 'isolated-product-premerge-evidence-audit/v1',
              'scanner_revision': 'exact-public-url-provenance-v2',
              'started_at': started, 'completed_at': datetime.now(UTC).isoformat(),
              'state': 'REVIEW_ONLY_NOT_PUBLISHED', 'root_review_required': True,
              'result': 'BLOCKED_UNRESOLVED_FINDINGS' if unresolved else
                        'PASS_WITH_PROVEN_PUBLIC_FIXTURE_FINDINGS' if audit.findings else 'PASS',
              'boundary': boundary, 'candidate_head': manifest['candidate_head'],
              'payload_files': len(rows), 'payload_bytes': sum(row['bytes'] for row in rows),
              'complete_byte_and_recursive_zip_scan': audit.counts,
              'unresolved_findings': len(unresolved), 'findings': audit.findings,
              'originals_mutated': False, 'candidate_code_executed': False,
              'diagnostic_authority': 'NOT_QUALIFIED_NO_HISTORICAL_CAUSE',
              'preliminary_host_audit': 'UNISOLATED_NOT_FINAL_AND_NOT_REUSED',
              'prior_isolated_audit': 'BLOCKED_TWO_PUBLIC_SOURCE_URL_FINDINGS_PRESERVED_UNCHANGED',
              'exclusions': ['connector/download envelopes and signed URLs',
                             'credential environment/home and .git/config',
                             'credential request headers', 'private original reuse maps'],
              'preserved_failure_links': [
                  'https://github.com/gabned/provelume/pull/409#issuecomment-6349677582',
                  'https://github.com/gabned/provelume/actions/runs/39799577294/job/119896122376',
                  'https://github.com/gabned/provelume/pull/408#issuecomment-6343538919',
                  'https://github.com/gabned/provelume/actions/runs/39505179474/job/118912204986'],
              'limits': ['PREMERGE only; actual-main acceptance remains separate.',
                         'No raw transport envelope is reconstructed or sanitized.',
                         'Historical missing payloads and historical CPU cause remain unproven.',
                         'Manifest/digests grant no integration or publication authority.']}
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    (out / 'review-report.json').write_text(json.dumps(report, indent=2) + '\n')
    if unresolved:
        print(json.dumps({'result': report['result'], 'unresolved_findings': len(unresolved)}))
        raise SystemExit(2)
    final_manifest = dict(manifest, state='PREMERGE_ISOLATED_AUDIT_COMPLETE_REVIEW_REQUIRED')
    metadata = {
        'manifest.json': (json.dumps(final_manifest, indent=2) + '\n').encode(),
        'review-report.json': (json.dumps(report, indent=2) + '\n').encode(),
        'fixture-audit-input.json': (package / 'fixture-audit-input.json').read_bytes(),
        'README.txt': README.encode(),
        'verify-package.py': Path(__file__).read_bytes(),
    }
    for name, data in metadata.items():
        before = len(audit.findings)
        audit.scan(data, 'generated-metadata/' + name)
        if any('classification' not in row for row in audit.findings[before:]):
            raise ValueError('Generated metadata has an unresolved audit finding')
        (out / name).write_bytes(data)
    max_bytes = 40 * 1024**2
    payload_limit = 39 * 1024**2
    bins = []
    for row in sorted(rows, key=lambda item: (-item['bytes'], item['path'])):
        if row['bytes'] > payload_limit:
            raise ValueError('Original file exceeds declared intact-volume limit')
        for bucket in bins:
            if bucket['bytes'] + row['bytes'] <= payload_limit:
                bucket['files'].append(row)
                bucket['bytes'] += row['bytes']
                break
        else:
            bins.append({'bytes': row['bytes'], 'files': [row]})
    volumes = []
    metadata_volume = out / 'product-a29-premerge-00-metadata.zip'
    with zipfile.ZipFile(metadata_volume, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(metadata.items()):
            archive.writestr(name, data)
    volumes.append({'file': metadata_volume.name, 'bytes': metadata_volume.stat().st_size,
                    'sha256': sha(metadata_volume.read_bytes()), 'files': len(metadata)})
    verified = set()
    for index, bucket in enumerate(bins, 1):
        path = out / f'product-a29-premerge-{index:02d}-evidence.zip'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for row in bucket['files']:
                archive.writestr(row['path'], checked_bytes(package, row))
        if path.stat().st_size > max_bytes:
            raise ValueError('Outer volume exceeds40MiB after metadata overhead')
        with zipfile.ZipFile(path) as archive:
            for row in bucket['files']:
                data = archive.read(row['path'])
                if len(data) != row['bytes'] or sha(data) != row['sha256']:
                    raise ValueError('Outer-volume verification mismatch')
                verified.add(row['path'])
        volumes.append({'file': path.name, 'bytes': path.stat().st_size,
                        'sha256': sha(path.read_bytes()), 'files': len(bucket['files'])})
    if verified != {row['path'] for row in rows}:
        raise ValueError('Incomplete outer volume inventory')
    index = {'schema': 'product-premerge-evidence-volume-index/v1',
             'state': 'REVIEW_ONLY_NOT_PUBLISHED', 'candidate': manifest['candidate_head'],
             'payload_files': len(rows), 'payload_bytes': sum(row['bytes'] for row in rows),
             'all_originals_intact': True, 'inner_original_zips_repacked': False,
             'max_volume_bytes': max_bytes, 'volumes': volumes,
             'manifest_sha256': sha(metadata['manifest.json']),
             'review_report_sha256': sha(metadata['review-report.json']),
             'completed_at': datetime.now(UTC).isoformat()}
    (out / 'package-index.json').write_text(json.dumps(index, indent=2) + '\n')
    print(json.dumps({'result': 'ISOLATED_AUDIT_AND_VOLUMES_READY_FOR_ROOT_REVIEW',
                      'payload_files': len(rows), 'payload_bytes': index['payload_bytes'],
                      'volumes': len(volumes), 'volume_bytes': sum(v['bytes'] for v in volumes),
                      'unresolved_findings': 0}))


if __name__ == '__main__':
    main()
