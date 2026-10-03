import math
import unittest

from quota import Quota, countdown, epoch, stamp


def response(*, used=4, duration=10080, bank_count=3, credits=None):
    if credits is None:
        credits = [
            dict(id="a", status="available", expiresAt=1791173978),
            dict(id="b", status="available", expiresAt=1792702069),
            dict(id="c", status="available", expiresAt=1793301362),
        ]
    return dict(
        rateLimitsByLimitId={"codex": dict(primary=dict(
            usedPercent=used, windowDurationMins=duration, resetsAt=1791658299), secondary=None, planType="pro")},
        rateLimitResetCredits=dict(availableCount=bank_count, credits=credits),
    )


class PresentationTests(unittest.TestCase):
    def test_pro_weekly_window_is_not_mislabeled_as_five_hour(self):
        quota = Quota.parse(response(), 1791080000)
        self.assertEqual(quota.windows[0].name, "本周")
        self.assertEqual(quota.windows[0].remaining, 96)
        self.assertEqual(len(quota.windows), 1)
        self.assertNotIn("5小时", quota.text(1791080000))

    def test_earliest_of_unsorted_available_bank_credits(self):
        value = response()
        value["rateLimitResetCredits"]["credits"].reverse()
        quota = Quota.parse(value, 1791080000)
        self.assertEqual(quota.bank_expiry, 1791173978)
        self.assertTrue(quota.bank_expiry_exact)
        self.assertEqual(quota.bank_count, 3)

    def test_count_only_is_not_zero_or_guessed_expiry(self):
        value = response()
        value["rateLimitResetCredits"]["credits"] = None
        quota = Quota.parse(value, 1791080000)
        self.assertEqual(quota.bank_count, 3)
        self.assertIsNone(quota.bank_expiry)
        self.assertIn("到期时间未知", quota.text(1791080000))

    def test_capped_rows_only_establish_known_earliest(self):
        quota = Quota.parse(response(bank_count=8), 1791080000)
        self.assertEqual(quota.bank_count, 8)
        self.assertFalse(quota.bank_expiry_exact)
        self.assertIn("已知最早", quota.text(1791080000))

    def test_unknown_expiry_in_complete_list_is_not_overstated(self):
        value = response()
        value["rateLimitResetCredits"]["credits"][1]["expiresAt"] = None
        quota = Quota.parse(value, 1791080000)
        self.assertFalse(quota.bank_expiry_exact)

    def test_consumed_rows_are_not_available_bank_expiry(self):
        value = response(bank_count=2)
        value["rateLimitResetCredits"]["credits"][0]["status"] = "consumed"
        quota = Quota.parse(value, 1791080000)
        self.assertEqual(quota.bank_expiry, 1792702069)
        self.assertTrue(quota.bank_expiry_exact)

    def test_duplicate_rows_do_not_claim_complete_bank(self):
        value = response()
        value["rateLimitResetCredits"]["credits"][1]["id"] = "a"
        self.assertFalse(Quota.parse(value, 1791080000).bank_expiry_exact)

    def test_missing_data_remains_unknown(self):
        quota = Quota.parse({}, 1791080000)
        self.assertEqual(quota.windows, ())
        self.assertIsNone(quota.bank_count)
        self.assertIn("次数未知", quota.text(1791080000))

    def test_invalid_percent_and_date_do_not_fabricate_capacity(self):
        for used in (None, True, "4", float("nan"), -1):
            quota = Quota.parse(response(used=used), 1791080000)
            self.assertIsNone(quota.windows[0].remaining)
        for value in (None, True, -1, float("inf"), 1e100):
            self.assertIsNone(epoch(value))

    def test_multi_bucket_never_uses_an_unrelated_allowance(self):
        value = response()
        value["rateLimitsByLimitId"]["other_model"] = value["rateLimitsByLimitId"].pop("codex")
        self.assertEqual(Quota.parse(value, 1791080000).windows, ())

    def test_legacy_and_secondary_windows(self):
        value = response(duration=300)
        value["rateLimits"] = value.pop("rateLimitsByLimitId")["codex"]
        value["rateLimits"]["secondary"] = dict(usedPercent=20, windowDurationMins=10080, resetsAt=1791658299)
        quota = Quota.parse(value, 1791080000)
        self.assertEqual([w.name for w in quota.windows], ["5小时", "本周"])
        self.assertEqual([w.remaining for w in quota.windows], [96, 80])

    def test_zero_bank_is_distinct_from_unknown(self):
        value = response(bank_count=0, credits=[])
        quota = Quota.parse(value, 1791080000)
        self.assertIsNone(quota.bank_expiry)
        self.assertIn("银行 0次", quota.text(1791080000))
        self.assertNotIn("到期", quota.text(1791080000))

    def test_beijing_time_does_not_depend_on_host_timezone(self):
        self.assertEqual(stamp(1791173978, True), "2026-10-05 12:19:38")
        self.assertEqual(stamp(1791658299, True), "2026-10-11 02:51:39")

    def test_failure_or_stale_snapshot_is_marked(self):
        quota = Quota.parse(response(), 1791080000)
        self.assertTrue(quota.text(1791080001, failed=True).startswith("旧数据"))
        self.assertTrue(quota.text(1791080181).startswith("旧数据"))

    def test_deadline_triggers_read_but_never_infers_new_balance(self):
        quota = Quota.parse(response(), 1791173977)
        self.assertTrue(quota.due(1791173978))
        self.assertEqual(quota.bank_count, 3)
        self.assertEqual(countdown(quota.bank_expiry, 1791173978), "到点待刷新")
        refreshed = Quota.parse(response(), 1791173979)
        self.assertFalse(refreshed.due(1791173980))

    def test_multiline_compact_keeps_both_requested_dates(self):
        quota = Quota.parse(response(), 1791080000)
        text = quota.text(1791080000, compact=2)
        self.assertEqual(len(text.splitlines()), 2)
        self.assertIn("10/11 02:51重置", text)
        self.assertIn("10/05 12:19到期", text)
        self.assertIn("银行3次", text)

    def test_minimum_width_layout_splits_labels_from_complete_dates(self):
        quota = Quota.parse(response(), 1791080000)
        lines = quota.text(1791080000, compact=3).splitlines()
        self.assertEqual(lines, ["周96%重置", "10/11 02:51", "银行3次到期", "10/05 12:19"])


if __name__ == "__main__":
    unittest.main()
