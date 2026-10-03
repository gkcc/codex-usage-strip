from control import Controller, PREFIX
from tests.helpers import IsolatedTestCase


class FakeKernel:
    def __init__(self):
        self.mutexes, self.events, self.closed, self.signaled = {}, {}, [], []
        self.fail_event = False

    def create_mutex(self, name):
        if name in self.mutexes:
            return ("duplicate", name), True
        self.mutexes[name] = ("mutex", name)
        return self.mutexes[name], False

    def open_mutex(self, name):
        return ("query", name) if name in self.mutexes else None

    def create_event(self, name):
        if self.fail_event:
            return None
        self.events[name] = ("event", name)
        return self.events[name]

    def open_event(self, name):
        return ("signal", name) if name in self.events else None

    def reset_event(self, handle):
        return True

    def set_event(self, handle):
        self.signaled.append(handle[1])
        self.mutexes.pop(handle[1].replace("-Stop", "-Instance"), None)
        return True

    def close(self, handle):
        if handle:
            self.closed.append(handle)
            if handle[0] == "mutex":
                self.mutexes.pop(handle[1], None)
            if handle[0] == "event":
                self.events.pop(handle[1], None)


class ScopedControlTests(IsolatedTestCase):
    def test_claim_closes_its_event_and_mutex_on_failure(self):
        kernel = FakeKernel()
        controller = Controller("fixture", kernel)
        with self.assertRaises(ValueError):
            with controller.claim() as event:
                self.assertIsNotNone(event)
                self.assertTrue(controller.running())
                raise ValueError("fixture interruption")
        self.assertFalse(controller.running())
        self.assertEqual(kernel.events, {})

    def test_duplicate_claim_does_not_close_the_original_instance(self):
        kernel = FakeKernel()
        controller = Controller("fixture", kernel)
        with controller.claim():
            with controller.claim() as duplicate:
                self.assertIsNone(duplicate)
            self.assertTrue(controller.running())

    def test_failed_event_creation_closes_the_mutex(self):
        kernel = FakeKernel()
        kernel.fail_event = True
        controller = Controller("fixture", kernel)
        with self.assertRaises(OSError):
            with controller.claim():
                self.fail("must not yield")
        self.assertFalse(controller.running())

    def test_stop_signals_only_its_installation_and_uses_a_public_namespace(self):
        kernel = FakeKernel()
        first, other = Controller("first", kernel), Controller("other", kernel)
        with first.claim(), other.claim():
            result = first.stop(timeout=0)
            self.assertFalse(result["running"])
            self.assertTrue(other.running())
            self.assertEqual(kernel.signaled, [first.event_name])
            self.assertIn("Public", PREFIX)

    def test_absent_instance_is_already_stopped_without_a_signal(self):
        kernel = FakeKernel()
        self.assertEqual(Controller("absent", kernel).stop(), {"stop_requested": False, "running": False})
        self.assertEqual(kernel.signaled, [])
