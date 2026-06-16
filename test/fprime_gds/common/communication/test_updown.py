from unittest import TestCase, mock

from fprime_gds.common.communication import updown


class TestDownlinker(TestCase):

    def make_downlinker(self, queue_maxsize=updown.DEFAULT_GROUND_QUEUE_MAXSIZE):
        return updown.Downlinker(
            adapter=mock.Mock(),
            ground=mock.Mock(),
            deframer=mock.Mock(),
            queue_maxsize=queue_maxsize,
        )

    def test_outgoing_queue_is_bounded_by_default(self):
        downlinker = self.make_downlinker()

        self.assertEqual(
            downlinker.outgoing.maxsize,
            updown.DEFAULT_GROUND_QUEUE_MAXSIZE,
        )

    def test_add_loopback_frame_logs_when_queue_is_full(self):
        downlinker = self.make_downlinker(queue_maxsize=2)

        for index in range(2):
            downlinker.outgoing.put_nowait(index)

        with self.assertLogs("downlink", level="WARNING") as captured:
            downlinker.add_loopback_frame(b"frame")

        self.assertIn(
            "GDS ground queue full, dropping loopback frame",
            captured.output[0],
        )

    def test_deframing_logs_when_queue_is_full(self):
        downlinker = self.make_downlinker(queue_maxsize=2)
        downlinker.running = True
        downlinker.adapter.read.side_effect = [b"", KeyboardInterrupt()]
        downlinker.deframer.deframe_all.return_value = (
            [b"first", b"second", b"third"],
            b"",
            b"",
        )

        for index in range(1):
            downlinker.outgoing.put_nowait(index)

        with self.assertLogs("downlink", level="WARNING") as captured:
            with self.assertRaises(KeyboardInterrupt):
                downlinker.deframing()

        self.assertIn(
            "GDS ground queue full, dropping frame",
            captured.output[0],
        )
        self.assertEqual(len(captured.output), 2)
        self.assertEqual(
            downlinker.outgoing.qsize(),
            2,
        )
        self.assertEqual(downlinker.outgoing.get_nowait(), 0)
        self.assertEqual(downlinker.outgoing.get_nowait(), b"first")
