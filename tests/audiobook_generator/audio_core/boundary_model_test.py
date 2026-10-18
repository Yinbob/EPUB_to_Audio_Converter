import copy
import unittest

from audiobook_generator.audio_core.boundary_model import FEATURES, LABELS, predict_model, train_boundary


class BoundaryModelTest(unittest.TestCase):
    def rows(self):
        rows = []
        for split in ("train", "dev", "test"):
            for i in range(16):
                labels = [label for k, label in enumerate(LABELS) if i & (1 << k)]
                features = dict.fromkeys(FEATURES, 0.)
                for k, name in enumerate(FEATURES[:4]):
                    features[name] = float(bool(i & (1 << k)))
                rows.append({"group_id": f"{split}-{i}", "split": split, "features": features, "labels": labels})
        return rows

    def test_training_uses_separate_development_and_reports_heldout(self):
        model = train_boundary(self.rows(), steps=300)
        self.assertEqual(model["heldout_metrics"]["rows"], 16)
        self.assertEqual(model["confidence_kind"], "uncalibrated_scores")
        self.assertEqual(model["threshold_kind"], "dev_selected")
        self.assertTrue(model["thresholds_ready"])
        prediction = predict_model(model, self.rows()[15]["features"])
        self.assertEqual(set(prediction["labels"]), set(LABELS))

    def test_source_group_leakage_is_rejected(self):
        rows = self.rows()
        rows[-1]["group_id"] = rows[0]["group_id"]
        with self.assertRaisesRegex(ValueError, "不能跨"):
            train_boundary(rows)

    def test_missing_label_examples_cannot_claim_full_calibration(self):
        rows = self.rows()
        for row in rows:
            row["labels"] = [label for label in row["labels"] if label != LABELS[0]]
        model = train_boundary(rows, steps=20)
        self.assertEqual(model["threshold_kind"], "partially_dev_selected")
        self.assertFalse(model["thresholds_ready"])
        self.assertEqual(model["label_support"]["train"][LABELS[0]], {"positive": 0, "negative": 16})
        self.assertEqual(model["thresholds"][0], 1.1)

    def test_no_class_with_both_outcomes_is_rejected(self):
        for labels in ([], list(LABELS)):
            with self.subTest(labels=labels):
                rows = self.rows()
                for row in rows:
                    row["labels"] = labels[:]
                with self.assertRaisesRegex(ValueError, "没有可训练类别"):
                    train_boundary(rows, steps=1)

    def test_class_support_must_exist_in_both_training_and_development(self):
        rows = self.rows()
        for row in rows:
            # 两个划分各自有一个可比较类别，但不是同一类。
            keep = LABELS[0] if row["split"] == "train" else LABELS[1]
            row["labels"] = [label for label in row["labels"] if label == keep]
        with self.assertRaisesRegex(ValueError, "没有可训练类别"):
            train_boundary(rows, steps=1)

    def test_heldout_labels_only_change_metrics_and_support(self):
        rows = self.rows()
        original = copy.deepcopy(rows)
        model = train_boundary(rows, steps=20)
        self.assertEqual(rows, original)
        for row in rows:
            if row["split"] == "test":
                row["labels"] = []
        changed = train_boundary(rows, steps=20)
        for key in ("weights", "mean", "scale", "thresholds", "threshold_ready_labels"):
            self.assertEqual(model[key], changed[key])
        self.assertEqual(model["source_group_counts"], {"train":16, "dev":16, "test":16})
        self.assertEqual(model["label_support"]["test"][LABELS[0]], {"positive":8, "negative":8})
        self.assertEqual(changed["label_support"]["test"][LABELS[0]], {"positive":0, "negative":16})


if __name__ == "__main__":
    unittest.main()
