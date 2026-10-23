"""Coordinate selection and retirement of media between producer and broadcaster."""

from contextlib import contextmanager
import fcntl

from news_orchestrator import config


@contextmanager
def locked():
    with (config.DATA / "media-lifetime.lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
