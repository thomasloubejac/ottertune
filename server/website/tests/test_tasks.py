#
# OtterTune - test_tasks.py
#
# Copyright (c) 2017-18, Carnegie Mellon University Database Group
#
import copy
import numpy as np
from django.test import TestCase, override_settings

from website.models import Workload, PipelineRun, PipelineData, Result
from website.tasks.periodic_tasks import (run_background_tasks,
                                          aggregate_data,
                                          run_workload_characterization,
                                          run_knob_identification)
from website.types import PipelineTaskType

CELERY_TEST_RUNNER = 'djcelery.contrib.test_runner.CeleryTestSuiteRunner'


@override_settings(CELERY_ALWAYS_EAGER=True, TEST_RUNNER=CELERY_TEST_RUNNER)
class BackgroundTestCase(TestCase):

    fixtures = ['test_website.json']

    def testNoError(self):
        result = run_background_tasks.delay()
        self.assertTrue(result.successful())

    def testNoWorkloads(self):
        # delete any existing workloads
        workloads = Workload.objects.all()
        workloads.delete()

        # background task should not fail
        result = run_background_tasks.delay()
        self.assertTrue(result.successful())

    def testNewPipelineRun(self):
        # this test currently relies on the fixture data so that
        # it actually tests anything
        workloads = Workload.objects.all()
        if len(workloads) > 0:
            runs_before = len(PipelineRun.objects.all())
            run_background_tasks.delay()
            runs_after = len(PipelineRun.objects.all())
            self.assertEqual(runs_before + 1, runs_after)

    def checkNewTask(self, task_type):
        workloads = Workload.objects.all()
        pruned_before = [len(PipelineData.objects.filter(
            workload=workload, task_type=task_type)) for workload in workloads]
        run_background_tasks.delay()
        pruned_after = [len(PipelineData.objects.filter(
            workload=workload, task_type=task_type)) for workload in workloads]
        for before, after in zip(pruned_before, pruned_after):
            self.assertEqual(before + 1, after)

    def testNewPrunedMetrics(self):
        self.checkNewTask(PipelineTaskType.PRUNED_METRICS)

    def testNewRankedKnobs(self):
        self.checkNewTask(PipelineTaskType.RANKED_KNOBS)


class AggregateTestCase(TestCase):

    fixtures = ['test_website.json']

    def testValidWorkload(self):
        workloads = Workload.objects.all()
        valid_workload = workloads[0]
        wkld_results = Result.objects.filter(workload=valid_workload)
        dicts = aggregate_data(wkld_results)
        keys = ['data', 'rowlabels', 'columnlabels']
        for d in dicts:
            for k in keys:
                self.assertIn(k, d)


class PrunedMetricTestCase(TestCase):

    fixtures = ['test_website.json']

    def testValidPrunedMetrics(self):
        workloads = Workload.objects.all()
        wkld_results = Result.objects.filter(workload=workloads[0])
        metric_data = aggregate_data(wkld_results)[1]
        pruned_metrics = run_workload_characterization(metric_data)
        for m in pruned_metrics:
            self.assertIn(m, metric_data['columnlabels'])


class RankedKnobTestCase(TestCase):

    fixtures = ['test_website.json']

    def testValidImportantKnobs(self):
        workloads = Workload.objects.all()
        wkld_results = Result.objects.filter(workload=workloads[0])
        knob_data, metric_data = aggregate_data(wkld_results)

        # instead of doing actual metric pruning by factor analysis / clustering,
        # just randomly select 5 nonconstant metrics
        nonconst_metric_columnlabels = []
        for col, cl in zip(metric_data['data'].T, metric_data['columnlabels']):
            if np.any(col != col[0]):
                nonconst_metric_columnlabels.append(cl)

        num_metrics = min(5, len(nonconst_metric_columnlabels))
        selected_columnlabels = np.random.choice(nonconst_metric_columnlabels,
                                                 num_metrics, replace=False)
        pruned_metric_idxs = [i for i, metric_name in
                              enumerate(metric_data['columnlabels'])
                              if metric_name in selected_columnlabels]
        pruned_metric_data = {
            'data': metric_data['data'][:, pruned_metric_idxs],
            'rowlabels': copy.deepcopy(metric_data['rowlabels']),
            'columnlabels': [metric_data['columnlabels'][i] for i in pruned_metric_idxs]
        }

        # run knob_identification using knob_data and fake pruned metrics
        ranked_knobs = run_knob_identification(knob_data, pruned_metric_data,
                                               workloads[0].dbms)
        for k in ranked_knobs:
            self.assertIn(k, knob_data['columnlabels'])
