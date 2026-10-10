"""Linux worker lifetime bound to an inherited, identity-stable parent pidfd."""

import os
import select
import threading

from .ai_runtime_limits import check


def watch_parent(descriptor):
    # Called only AFTER contain(): the guard inherits the same seccomp restrictions.
    # A creator thread exiting is not parent-process death; no PDEATHSIG/PID polling.
    check(type(descriptor) is int and descriptor >= 3, "compatibility")
    check(os.readlink(f"/proc/self/fd/{descriptor}") == "anon_inode:[pidfd]", "compatibility")
    observer = select.poll()
    observer.register(descriptor, select.POLLIN | select.POLLHUP | select.POLLERR)
    if observer.poll(0):
        os._exit(70)

    def guard():
        try:
            observer.poll()
        finally:
            # End every native/Python thread even if the main thread is in a C call.
            os._exit(70)

    threading.Thread(target=guard, name="provelume-parent-lifetime", daemon=True).start()
