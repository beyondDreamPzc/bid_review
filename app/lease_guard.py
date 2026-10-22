from contextlib import contextmanager
from threading import Event,Thread
from app.jobs import heartbeat,StaleLease


@contextmanager
def keep_lease(factory,attempt,settings):
    stop=Event();lost=Event()
    def renew():
        while not stop.wait(max(1,min(20,settings.lease_seconds/3))):
            try:heartbeat(factory,attempt,settings)
            except Exception:lost.set();return
    heartbeat(factory,attempt,settings)
    thread=Thread(target=renew,daemon=True);thread.start()
    try:
        yield
        if lost.is_set():raise StaleLease("Lease renewal failed")
        heartbeat(factory,attempt,settings)
    finally:
        stop.set();thread.join(timeout=2)
