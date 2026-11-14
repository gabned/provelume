"""Known Instance/control/backup boundaries after native local-parent admission."""

from pathlib import Path

from .mirror_contract import require


def exclude_known_data_directories(selected, store):
    # Parent handles/locality have already been admitted by the transport.
    # Read only fixed marker metadata, never a foreign Instance's document bytes.
    for parent in selected.parents:
        require(
            not (parent.name.startswith(".") and parent.name.casefold().endswith(".provelume")),
            "unsafe_git_target",
        )
        for name in ("provelume.yml", "instance-manifest.json", "backup-manifest.json"):
            marker = parent / name
            try:
                marker.lstat()
            except FileNotFoundError:
                continue
            require(False, "unsafe_git_target")

    from .maintenance_targets import LocalTargetRegistry

    # An explicit action may read its existing private registry. This does not
    # create/enrol a registry, resolve an offline locator or open any archive.
    for row in LocalTargetRegistry(store)._load()["targets"].values():
        if row["public"]["purpose"] != "backup_read":
            continue
        archive = Path(row["locator"])
        require(archive.is_absolute(), "unsafe_git_target")
        require(
            not selected.is_relative_to(archive.parent)
            and not archive.parent.is_relative_to(selected),
            "unsafe_git_target",
        )
