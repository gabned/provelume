"""Fresh automatic local feed qualification, runnable from the frozen executable."""

from pathlib import Path

from .build_info import current_build_info
from .google_credentials import GoogleCredentialVault
from .icalendar_feeds import IcalendarFeeds
from .productivity_contract import require
from .productivity_intake import ProductivityIntake
from .productivity_jobs import ProductivityJobs
from .service import ProvelumeInstance

RAW = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Provelume//Synthetic//EN\r\n"
       b"BEGIN:VEVENT\r\nUID:synthetic-calendar-qualification\r\nSUMMARY:Synthetic all-day\r\n"
       b"DTSTART;VALUE=DATE:20261107\r\nDTEND;VALUE=DATE:20261108\r\n"
       b"RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")


def qualify_icalendar(root, *, vault=None):
    root = Path(root).absolute()
    require(not root.exists() and not root.is_symlink(), "target_not_fresh")
    root.mkdir(parents=True)
    path = root / "Synthetic Calendar.ics"
    path.write_bytes(RAW)
    instance = ProvelumeInstance.initialise(root / "Synthetic Space")
    manager = IcalendarFeeds(instance.store, vault=vault or GoogleCredentialVault(
        windows_root=root / "Device Credentials", forbidden_root=instance.root,
        namespace="productivity"))
    sources = [manager.add(name=name, kind="local", location=path, confirmed=True)["source_id"]
               for name in ("Synthetic first", "Synthetic second")]
    jobs = ProductivityJobs(instance.store, feeds=manager)
    instance.scheduler._productivity_manager_factory = lambda _store: jobs
    try:
        for source in sources:
            queued = jobs.queue(source)
            result = instance.scheduler.run_one(job_id=queued["job"]["id"])
            require(result is not None and result["status"] == "succeeded", "qualification")
        rows = ProductivityIntake(instance.store).records(sources[0])
        require(len(rows) == 1 and instance.document_original(rows[0]["document_id"])["data"]
                == RAW, "qualification")
        require(manager.refresh(sources[0])["results"][0]["status"] == "unchanged", "qualification")
        objects = instance.store.list_canonical("objects")
        require(len(objects) == 2 and all(value["body"]["starts_on"] == "2026-11-07"
                                          for value in objects), "qualification")
        require(len(manager.duplicates()) == 1, "qualification")
        archive = root / "Synthetic Portable.zip"
        instance.export_portable(archive, derived_state="rebuild")
        restored = ProvelumeInstance.initialise(root / "Restored Space")
        restored.import_portable(archive)
        require(restored.validate_instance()["status"] == "valid"
                and restored.store.list_canonical("objects") == objects, "qualification")
        require(not instance.store.read_config()["network"]["external_access"], "qualification")
        return {"schema": "provelume-icalendar-qualification/v1", "result": "PASS",
                "build": current_build_info(), "network_used": False,
                "source_count": 2, "exact_original": "PASS", "replay": "PASS",
                "duplicates_kept_separate": "PASS", "portable_rebuild": "PASS",
                "parser_process": "REAL_ISOLATED_WORKER", "real_https": "NOT_RUN",
                "rendered_browser": "NOT_RUN", "windows_11_pro_25h2_manual":
                "DEFERRED_BY_MAINTAINER / NOT_RUN"}
    finally:
        for source in sources:
            manager.vault.delete(manager.slot(source))
