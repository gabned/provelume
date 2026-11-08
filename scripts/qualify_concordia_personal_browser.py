"""Real Chromium S09 journey over disposable local data; no manual claims.

Run with a Python containing Playwright. --runtime selects the candidate's Python
for fixture preparation and the actual application server. No browser download,
credential, installed user profile or external URL is selected by this driver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

PREPARE = """
import json, sys
from pathlib import Path
from provelume.personal_qualification import qualify_personal
from provelume.service import ProvelumeInstance
root=Path(sys.argv[1])
report=qualify_personal(root, retention='keep')
instance=ProvelumeInstance(root/'Synthetic Space')
fixture={'native':report,'document_id':instance.list_documents()[0]['id']}
if sys.argv[2]=='yes':
    from provelume.productivity_contract import ReadPage
    from provelume.productivity_intake import ProductivityIntake
    connectors=instance.connectors
    definition=connectors.register_definition({
        'adapter_key':'synthetic-calendar-ui','adapter_version':'1.0.0',
        'display_name':'Synthetic calendar','provider':'synthetic',
        'conformance_profile':'provelume.connector.v1','adapter_protocol_version':1,
        'capabilities':['manual_read','source_selection','calendar_read'],
        'authorization_modes':['none'],'source_kinds':['calendar'],
        'data_categories':['source.content'],'multi_instance':True,'network_access':'none'})
    identity=connectors.create_instance(definition['id'],name='Synthetic calendar',
        provider_identity='synthetic')
    source=connectors.add_source(identity['id'],name='Synthetic calendar',
        source_kind='calendar',external_id='synthetic-calendar')['id']
    host=instance.productivity_connectors()
    host.consent(source,capabilities=['calendar_read'],mode='manual',expected_revision=0,confirmed=True)
    mapped={'remote_id':'synthetic-event','revision':'version-1','revision_kind':'version',
        'kind':'calendar_event','title':'Synthetic calendar example',
        'description':'SOURCE CALENDAR',
        'state':'confirmed','due':None,
        'starts':{'kind':'date','value':'2026-11-07','time_zone':None},
        'ends':{'kind':'date','value':'2026-11-08','time_zone':None},
        'provenance':{'container_ids':['synthetic-calendar'],'parent_id':None,'assignees':[],
            'links':[],'comments':[],'uid':'synthetic-uid','recurrence_id':None,'recurrence':[]}}
    class Adapter:
        def read_page(self,**request):
            raw=json.dumps(mapped).encode()
            return ReadPage((mapped,),originals=(raw,),response=raw)
    preview=host.preview(source,'calendar_read',Adapter(),
        expected_authority=host.authority(source,'calendar_read')['sha256'])
    ProductivityIntake(instance.store).accept(preview)
    fixture['provider_object_id']=instance.store.list_canonical('objects')[0]['id']
    from provelume.asana_qualification import seed_asana
    _,_,asana_source=seed_asana(instance)
    fixture['task_object_id']=next(row['id'] for row in instance.store.list_canonical('objects')
        if row['origin'].get('source_id')==asana_source)
    from provelume.tududi_qualification import seed_tududi
    _,_,tududi_source=seed_tududi(instance)
    fixture['tududi_object_id']=next(row['id'] for row in instance.store.list_canonical('objects')
        if row['origin'].get('source_id')==tududi_source)
    from provelume.task_writeback_qualification import SyntheticWriteBackFixture
    write_fixture=SyntheticWriteBackFixture(instance)
    write_fixture.consent()
    write_plan=write_fixture.prepare({'completed':True,'due':{
        'kind':'date','value':'2026-11-08','time_zone':None}})
    fixture['writeback_object_id']=write_fixture.object_id
    fixture['writeback_plan_id']=write_plan['id']
    from provelume.mirrors import Mirrors
    from provelume.mirror_jobs import local_preview
    from provelume.tududi_qualification import SyntheticVault
    mirror_input=root/'Synthetic mirror input'
    mirror_input.mkdir()
    (mirror_input/'mirror-browser.md').write_text(
        '# Synthetic mirror browser proof\\n',encoding='utf-8')
    instance.ingest_run(mirror_input)
    mirror_document=next(row for row in instance.store.list_canonical('documents')
                         if row['title']=='mirror-browser.md')
    mirror_area=instance.create_hierarchy_node('area','Synthetic mirror browser Area')
    instance.classify_document(mirror_document['id'],mirror_area['id'])
    mirrors=Mirrors(instance.store,vault=SyntheticVault())
    mirrors.set_access(enabled=True,github=False,rsync=False,expected_revision=0,confirmed=True)
    mirror_identity=mirrors.create_identity(name='Synthetic mirror identity',profile='folder',
        credential={'reference':''},confirmed=True)
    mirror_target=mirrors.configure(
        identity_id=mirror_identity['id'],name='Synthetic mirror destination',
        target={'path':str(root/'Synthetic absent destination')},
        scope={'kind':'area','id':mirror_area['id']},
        include_rules={'originals':[],'attachments':[],'ai_receipts':[]},mode='manual',confirmed=True)
    mirror_plan=local_preview(mirrors,mirror_target['id'],expected_revision=1)
    fixture['mirror_plan_id']=mirror_plan['id']
    from provelume.mirror_git import GitMirrors
    git_identity=mirrors.create_identity(name='Synthetic local Git',profile='git',
        credential={'reference':''},confirmed=True)
    git_target=mirrors.configure(identity_id=git_identity['id'],name='Synthetic Git destination',
        target={'transport':'local','repository':str(root/'Synthetic Git.git'),
                'branch':'concordia','path':'knowledge',
                'commit_name':'Synthetic Browser','commit_email':'browser@example.invalid'},
        scope={'kind':'area','id':mirror_area['id']},include_rules={'originals':[],'attachments':[],'ai_receipts':[]},mode='manual',confirmed=True)
    git=GitMirrors(instance.store,mirrors=mirrors)
    git.initialize_local(git_target['id'],expected_destination_sha256=git_target['destination_sha256'],confirmed=True)
    fixture['mirror_git_plan_id']=git.prepare(git_target['id'],expected_revision=1,confirmed=True)['id']
    from provelume.mirror_github_credentials import GitHubCredentials
    from provelume.mirror_github_qualification import SyntheticApi,SyntheticNativeGitHub,target
    from provelume.mirror_git import git_work
    mirrors.set_access(enabled=True,github=True,rsync=False,expected_revision=1,confirmed=True)
    gh=SyntheticNativeGitHub(instance.store,mirrors=mirrors,
        credentials=GitHubCredentials(mirrors,vault=mirrors.vault,http=SyntheticApi()))
    gh_identity=gh.connect(name='Synthetic GitHub browser',target=target(),
        token='synthetic-browser',
        mode='user',confirmed=True,probe_confirmed=True)['identity']
    gh.synthetic_remote=root/'Synthetic hosted file Git.git'
    with git_work() as session:
        session.run(['init','--bare','--object-format=sha1',str(gh.synthetic_remote)])
    gh_target=mirrors.configure(identity_id=gh_identity['id'],name='Synthetic GitHub destination',
        target=target(),scope={'kind':'area','id':mirror_area['id']},
        include_rules={'originals':[],'attachments':[],'ai_receipts':[]},mode='manual',confirmed=True)
    fixture['mirror_github_plan_id']=gh.prepare(gh_target['id'],expected_revision=1,confirmed=True)['id']
    from provelume.mirror_gitlab_credentials import GitLabCredentials
    from provelume.mirror_gitlab_qualification import (SyntheticApi as GitLabApi,
        SyntheticNativeGitLab, target as gitlab_contract_target)
    gl=SyntheticNativeGitLab(instance.store,mirrors=mirrors,
        credentials=GitLabCredentials(mirrors,vault=mirrors.vault,http=GitLabApi()))
    gl_identity=gl.connect(name='Synthetic GitLab browser',target=gitlab_contract_target(),
        token='synthetic-gitlab-browser',mode='classic-pat',confirmed=True)['identity']
    gl.synthetic_remote=root/'Synthetic GitLab hosted file Git.git'
    with git_work() as session:
        session.run(['init','--bare','--object-format=sha1',str(gl.synthetic_remote)])
    gl_target=mirrors.configure(identity_id=gl_identity['id'],name='Synthetic GitLab destination',
        target=gitlab_contract_target(),scope={'kind':'area','id':mirror_area['id']},
        include_rules={'originals':[],'attachments':[],'ai_receipts':[]},mode='manual',confirmed=True)
    fixture['mirror_gitlab_plan_id']=gl.prepare(gl_target['id'],expected_revision=1,confirmed=True)['id']
    from provelume.mirror_gitea_credentials import GiteaCredentials
    from provelume.mirror_gitea_qualification import (SyntheticApi as GiteaApi,
        SyntheticNativeGitea, target as gitea_contract_target)
    gt=SyntheticNativeGitea(instance.store,mirrors=mirrors,
        credentials=GiteaCredentials(mirrors,vault=mirrors.vault,http=GiteaApi()))
    gt_identity=gt.connect(name='Synthetic Gitea browser',target=gitea_contract_target(),
        token='synthetic-gitea-browser',mode='current-token',confirmed=True)['identity']
    gt.synthetic_remote=root/'Synthetic Gitea hosted file Git.git'
    with git_work() as session:
        session.run(['init','--bare','--object-format=sha1',str(gt.synthetic_remote)])
    gt_target=mirrors.configure(identity_id=gt_identity['id'],name='Synthetic Gitea destination',
        target=gitea_contract_target(),scope={'kind':'area','id':mirror_area['id']},
        include_rules={'originals':[],'attachments':[],'ai_receipts':[]},mode='manual',confirmed=True)
    fixture['mirror_gitea_plan_id']=gt.prepare(gt_target['id'],expected_revision=1,confirmed=True)['id']
print(json.dumps(fixture))
"""
SERVE = """
import sys, uvicorn
from pathlib import Path
from provelume.web import create_app
root=Path(sys.argv[1])
uvicorn.run(create_app(root/'Synthetic Space', shell_settings_file=root/'launcher.json'),
            host='127.0.0.1', port=int(sys.argv[2]), log_level='warning')
"""
MODE = """
import sys
from pathlib import Path
from provelume.shell_settings import ShellSettingsManager, default_settings
manager=ShellSettingsManager(Path(sys.argv[1])/'launcher.json', default_settings())
manager.set_interface_mode(sys.argv[2], expected_revision=manager.load().settings.revision)
"""


def main():
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--chromium", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--include-productivity", action="store_true")
    options = parser.parse_args()
    # Resolving the venv interpreter symlink would silently drop its environment.
    runtime, work = options.runtime.absolute(), options.work.resolve()
    source = Path(__file__).absolute().parents[1]
    if Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                                   text=True).strip()).resolve() != source.resolve():
        raise RuntimeError("Browser driver and candidate checkout differ")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(source / "core")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if head != options.commit or subprocess.check_output(
            ["git", "status", "--porcelain"], text=True).strip():
        raise RuntimeError("Browser qualification requires the exact clean candidate")
    work.mkdir(parents=True, exist_ok=False)
    root = work / "personal"
    report = {"schema": "concordia-personal-browser/v1", "result": "UNKNOWN", "cells": [],
              "external_requests": [], "manual": "DEFERRED_BY_MAINTAINER / NOT_RUN",
              "commit": head, "host": platform.platform()}
    server = None
    try:
        prepared = subprocess.run([str(runtime), "-c", PREPARE, str(root),
                                   "yes" if options.include_productivity else "no"], check=False,
                                  capture_output=True, text=True, timeout=180, env=environment)
        (work / "native.json").write_text(prepared.stdout, encoding="utf-8")
        (work / "preparation.log").write_text(prepared.stderr, encoding="utf-8")
        prepared.check_returncode()
        fixture = json.loads(prepared.stdout)
        paths = [root / "Synthetic Space" / name
                 for name in ("provelume.yml", "instance-manifest.json")]
        for directory in ("knowledge", "originals"):
            paths.extend(path for path in (root / "Synthetic Space" / directory).rglob("*")
                         if path.is_file())
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        with socket.socket() as selected:
            selected.bind(("127.0.0.1", 0))
            port = selected.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        with (work / "server.log").open("x", encoding="utf-8") as log:
            server = subprocess.Popen([str(runtime), "-c", SERVE, str(root), str(port)],
                                      stdout=log, stderr=subprocess.STDOUT, env=environment)
            deadline = time.monotonic() + 20
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=.2):
                        break
                except OSError:
                    if server.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("Candidate server did not become available") from None
                    time.sleep(.1)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=str(options.chromium))
                report["browser"] = browser.version
                context = browser.new_context(service_workers="block")

                def route(request):
                    if urlsplit(request.request.url).netloc == f"127.0.0.1:{port}":
                        request.continue_()
                    else:
                        report["external_requests"].append(request.request.url)
                        request.abort()

                context.route("**/*", route)
                page = context.new_page()
                for mode in ("current", "preview"):
                    subprocess.run([str(runtime), "-c", MODE, str(root), mode], check=True,
                                   capture_output=True, timeout=15, env=environment)
                    for language in ("en", "it", "de", "es", "fr", "pt", "ro"):
                        for width in (1280, 320):
                            cell = {"mode": mode, "language": language, "width": width,
                                    "result": "UNKNOWN"}
                            report["cells"].append(cell)
                            try:
                                page.set_viewport_size({"width": width, "height": 900})
                                params = {"lang": language, "q": "PROVELUME",
                                          "media_type": "text/plain"}
                                response = page.goto(origin + "/search?" + urlencode(params))
                                assert response.status == 200
                                page.locator("#search-edit").click()
                                assert page.evaluate("document.activeElement.id") == "search-query"
                                page.locator("#search-remove-filters").click()
                                assert page.locator("#search-query").input_value() == "PROVELUME"
                                assert "media_type" not in urlsplit(page.url).query
                                assert page.locator("html").get_attribute("lang") == language
                                assert page.evaluate("document.documentElement.scrollWidth <= "
                                                     "document.documentElement.clientWidth")
                                response = page.goto(origin + "/search?" + urlencode({
                                    "lang": language, "q": "PROVELUME",
                                    "date_from": "2026-02-30"}))
                                assert response.status == 400
                                assert page.locator("#search-query").input_value() == "PROVELUME"
                                response = page.goto(origin + "/documents/" + fixture[
                                    "document_id"] + "?lang=" + language)
                                assert response.status == 200
                                page.go_back()
                                assert page.locator("#search-query").input_value() == "PROVELUME"
                                if "provider_object_id" in fixture:
                                    response = page.goto(
                                        origin + "/google/connect?lang=" + language)
                                    assert response.status == 200
                                    page.locator('select[name="capability"]').first.select_option(
                                        "calendar")
                                    assert page.locator('option[value="calendar"]').count() >= 1
                                    response = page.goto(origin + "/icalendar?lang=" + language)
                                    assert response.status == 200
                                    assert page.locator('form[action^="/icalendar"]').count() >= 1
                                    assert page.locator('select[name="kind"]').first.is_visible()
                                    page.locator('select[name="kind"]').first.select_option("https")
                                    assert "icalendar.title" not in page.content()
                                    assert page.evaluate("document.documentElement.scrollWidth <= "
                                                        "document.documentElement.clientWidth")
                                    cell["icalendar_controls"] = "AUTOMATIC_PASS"
                                    response = page.goto(origin + "/objects/" + fixture[
                                        "provider_object_id"] + "?lang=" + language)
                                    assert response.status == 200
                                    assert page.locator("#connector-readonly").is_visible()
                                    assert page.locator('a[href*="/edit?"]').count() == 0
                                    assert "2026-11-07" in page.locator("main").inner_text()
                                    assert "objects.field.starts_on" not in page.content()
                                    assert page.evaluate("document.documentElement.scrollWidth <= "
                                                        "document.documentElement.clientWidth")
                                    cell["source_surfaces"] = "AUTOMATIC_SYNTHETIC_PASS"
                                    response = page.goto(origin + "/asana/connect?lang=" + language)
                                    assert response.status == 200
                                    assert page.locator(
                                        'form[action^="/asana/connect"]').count() >= 1
                                    assert "asana.lead" not in page.content()
                                    assert "synthetic-client-secret" not in page.content()
                                    response = page.goto(origin + "/objects/" + fixture[
                                        "task_object_id"] + "?lang=" + language)
                                    assert response.status == 200
                                    assert page.locator("#connector-provenance").is_visible()
                                    assert "Synthetic retained comment" in page.locator(
                                        "main").inner_text()
                                    assert page.locator('a[href*="/edit?"]').count() == 0
                                    assert page.evaluate("document.documentElement.scrollWidth <= "
                                                        "document.documentElement.clientWidth")
                                    cell["asana_surfaces"] = "AUTOMATIC_SYNTHETIC_PASS"
                                    response = page.goto(
                                        origin + "/tududi/connect?lang=" + language)
                                    assert response.status == 200
                                    assert "tududi.lead" not in page.content()
                                    assert "tt_synthetic_token" not in page.content()
                                    response = page.goto(origin + "/objects/" + fixture[
                                        "tududi_object_id"] + "?lang=" + language)
                                    assert response.status == 200
                                    assert page.locator("#connector-provenance").is_visible()
                                    assert "Exact retained comment" in page.locator(
                                        "main").inner_text()
                                    assert page.locator('a[href*="/edit?"]').count() == 0
                                    assert page.evaluate("document.documentElement.scrollWidth <= "
                                                        "document.documentElement.clientWidth")
                                    cell["tududi_surfaces"] = "AUTOMATIC_SYNTHETIC_PASS"
                                    response = page.goto(origin + "/task-writeback/" + fixture[
                                        "tududi_object_id"] + "?lang=" + language)
                                    assert response.status == 200
                                    assert page.locator("#task-write-unavailable").is_visible()
                                    response = page.goto(origin + "/task-writeback/" + fixture[
                                        "writeback_object_id"] + "?" + urlencode({
                                            "lang": language,
                                            "plan": fixture["writeback_plan_id"]}))
                                    assert response.status == 200
                                    assert page.locator("#task-write-diff").is_visible()
                                    assert "2026-11-08" in page.locator("main").inner_text()
                                    assert page.evaluate("document.documentElement.scrollWidth <= "
                                                        "document.documentElement.clientWidth")
                                    cell["writeback_readonly_preview"] = "AUTOMATIC_SYNTHETIC_PASS"
                                    response=page.goto(origin+'/mirrors?'+urlencode({
                                        'lang':language,'plan':fixture['mirror_plan_id']}))
                                    assert response.status==200
                                    assert page.locator('#mirror-preview').is_visible()
                                    assert page.locator('#mirror-unavailable').is_visible()
                                    assert 'mirror.title' not in page.content()
                                    assert page.evaluate("document.documentElement.scrollWidth <= "
                                                        "document.documentElement.clientWidth")
                                    cell['mirror_local_preview']='AUTOMATIC_SYNTHETIC_PASS'
                                    response=page.goto(origin+'/mirrors?'+urlencode({
                                        'lang':language,'plan':fixture['mirror_git_plan_id']}))
                                    assert response.status==200
                                    assert page.locator('#mirror-git-plan').is_visible()
                                    assert 'browser@example.invalid' in page.locator(
                                        '#mirror-git-plan').inner_text()
                                    assert page.evaluate("document.documentElement.scrollWidth <= "
                                                        "document.documentElement.clientWidth")
                                    cell['mirror_git_bound_preview']='AUTOMATIC_NATIVE_LOCAL_PASS'
                                    response=page.goto(origin+'/mirrors?'+urlencode({
                                        'lang':language,'plan':fixture['mirror_github_plan_id']}))
                                    assert response.status==200
                                    assert page.locator('#mirror-github-transfer').is_visible()
                                    transfer=page.locator('#mirror-github-transfer').inner_text()
                                    assert 'namespace.json' in transfer
                                    assert 'manifest.json' in transfer
                                    assert 'active.json' in transfer and 'utf8_content' in transfer
                                    assert 'synthetic-browser' not in page.content()
                                    assert page.evaluate('document.documentElement.scrollWidth <= '
                                                         'document.documentElement.clientWidth')
                                    cell['mirror_github_preview']='AUTOMATIC_SYNTHETIC_NATIVE_FILE_PASS'
                                    response=page.goto(origin+'/mirrors?'+urlencode({
                                        'lang':language,'plan':fixture['mirror_gitlab_plan_id']}))
                                    assert response.status==200
                                    assert page.locator('#mirror-gitlab-transfer').is_visible()
                                    transfer=page.locator('#mirror-gitlab-transfer').inner_text()
                                    assert 'namespace.json' in transfer
                                    assert 'remote_mutation' in transfer
                                    assert 'synthetic-gitlab-browser' not in page.content()
                                    assert page.evaluate('document.documentElement.scrollWidth <= '
                                                         'document.documentElement.clientWidth')
                                    cell['mirror_gitlab_preview']='AUTOMATIC_SYNTHETIC_NATIVE_FILE_PASS'
                                    response=page.goto(origin+'/mirrors?'+urlencode({
                                        'lang':language,'plan':fixture['mirror_gitea_plan_id']}))
                                    assert response.status==200
                                    assert page.locator('#mirror-gitea-transfer').is_visible()
                                    transfer=page.locator('#mirror-gitea-transfer').inner_text()
                                    assert 'namespace.json' in transfer
                                    assert 'remote_mutation' in transfer
                                    assert 'https://127.0.0.1:30443' in page.locator(
                                        'main').inner_text()
                                    assert 'synthetic-gitea-browser' not in page.content()
                                    assert page.evaluate('document.documentElement.scrollWidth <= '
                                                         'document.documentElement.clientWidth')
                                    cell['mirror_gitea_preview']='AUTOMATIC_SYNTHETIC_NATIVE_FILE_PASS'
                                image = work / f"{mode}-{language}-{width}.png"
                                page.screenshot(path=str(image), full_page=True)
                                cell.update(result="PASS", screenshot=image.name,
                                            sha256=hashlib.sha256(image.read_bytes()).hexdigest())
                            except Exception as error:
                                cell.update(result="FAIL", error=type(error).__name__)
                browser.close()
        report["canonical_unchanged"] = all(
            path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == before[str(path)]
            for path in paths)
        report["result"] = ("PASS" if len(report["cells"]) == 28 and all(
            row["result"] == "PASS" for row in report["cells"])
            and not report["external_requests"] and report["canonical_unchanged"] else "FAIL")
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        (work / "browser.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
