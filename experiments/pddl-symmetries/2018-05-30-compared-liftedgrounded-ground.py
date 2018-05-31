#! /usr/bin/env python
# -*- coding: utf-8 -*-

import os
import suites

from lab.environments import LocalEnvironment, BaselSlurmEnvironment
from lab.reports import Attribute, geometric_mean
from downward.reports.absolute import AbsoluteReport
from downward.reports.compare import ComparativeReport

from common_setup import IssueConfig, IssueExperiment, DEFAULT_OPTIMAL_SUITE, is_test_run
try:
    from relativescatter import RelativeScatterPlotReport
    matplotlib = True
except ImportError:
    print 'matplotlib not availabe, scatter plots not available'
    matplotlib = False

REVISION = 'e028b93170de'

def main(revisions=None):
    benchmarks_dir=os.path.expanduser('~/repos/downward/benchmarks')
    # optimal union satisficing, strips only
    suite = ['airport', 'barman-opt11-strips', 'barman-opt14-strips', 'blocks', 'childsnack-opt14-strips', 'depot', 'driverlog', 'elevators-opt08-strips', 'elevators-opt11-strips', 'floortile-opt11-strips', 'floortile-opt14-strips', 'freecell', 'ged-opt14-strips', 'grid', 'gripper', 'hiking-opt14-strips', 'logistics00', 'logistics98', 'miconic', 'movie', 'mprime', 'mystery', 'nomystery-opt11-strips', 'openstacks-opt08-strips', 'openstacks-opt11-strips', 'openstacks-opt14-strips', 'openstacks-strips', 'parcprinter-08-strips', 'parcprinter-opt11-strips', 'parking-opt11-strips', 'parking-opt14-strips', 'pathways-noneg', 'pegsol-08-strips', 'pegsol-opt11-strips', 'pipesworld-notankage', 'pipesworld-tankage', 'psr-small', 'rovers', 'satellite', 'scanalyzer-08-strips', 'scanalyzer-opt11-strips', 'sokoban-opt08-strips', 'sokoban-opt11-strips', 'storage', 'tetris-opt14-strips', 'tidybot-opt11-strips', 'tidybot-opt14-strips', 'tpp', 'transport-opt08-strips', 'transport-opt11-strips', 'transport-opt14-strips', 'trucks-strips', 'visitall-opt11-strips', 'visitall-opt14-strips', 'woodworking-opt08-strips', 'woodworking-opt11-strips', 'zenotravel', 'barman-sat11-strips', 'barman-sat14-strips', 'childsnack-sat14-strips', 'elevators-sat08-strips', 'elevators-sat11-strips', 'floortile-sat11-strips', 'floortile-sat14-strips', 'ged-sat14-strips', 'hiking-sat14-strips', 'nomystery-sat11-strips', 'openstacks-sat08-strips', 'openstacks-sat11-strips', 'openstacks-sat14-strips', 'parcprinter-sat11-strips', 'parking-sat11-strips', 'parking-sat14-strips', 'pegsol-sat11-strips', 'scanalyzer-sat11-strips', 'sokoban-sat08-strips', 'sokoban-sat11-strips', 'tetris-sat14-strips', 'thoughtful-sat14-strips', 'tidybot-sat11-strips', 'transport-sat08-strips', 'transport-sat11-strips', 'transport-sat14-strips', 'visitall-sat11-strips', 'visitall-sat14-strips', 'woodworking-sat08-strips', 'woodworking-sat11-strips']

    duplicates = [ 'barman-opt11-strips', 'barman-sat11-strips',
    'elevators-opt08-strips', 'elevators-sat08-strips',
    'floortile-opt11-strips', 'floortile-sat11-strips', 'openstacks',
    'openstacks-opt08-strips', 'openstacks-opt11-strips',
    'openstacks-sat08-strips', 'openstacks-sat11-strips', 'openstacks-strips',
    'parcprinter-08-strips', 'parking-opt11-strips', 'parking-sat11-strips',
    'pegsol-08-strips', 'scanalyzer-08-strips', 'sokoban-opt08-strips',
    'sokoban-sat08-strips', 'tidybot-opt11-strips', 'transport-opt08-strips',
    'transport-opt11-strips', 'transport-sat08-strips',
    'transport-sat11-strips', 'visitall-opt11-strips', 'visitall-sat11-strips',
    'woodworking-opt08-strips', 'woodworking-sat08-strips', ]

    suite_without_duplicates = [domain for domain in suite if domain not in duplicates]

    configs = {
    }

    exp = IssueExperiment(
        revisions=revisions,
    )

    generators_count = Attribute('generators_count', absolute=True, min_wins=False)
    generators_identity_count = Attribute('generators_identity_count', absolute=True, min_wins=False)
    generators_orders = Attribute('generators_orders', absolute=True, min_wins=False)
    symmetry_graph_size = Attribute('symmetry_graph_size', absolute=True, min_wins=True)
    time_symmetries = Attribute('time_symmetries', absolute=False, min_wins=True, functions=[geometric_mean])

    extra_attributes = [
        generators_count,
        generators_identity_count,
        generators_orders,
        symmetry_graph_size,
        time_symmetries,
    ]
    attributes = exp.DEFAULT_TABLE_ATTRIBUTES
    attributes.extend(extra_attributes)

    exp.add_fetcher('data/2018-05-30-lifted-stabinit-grounded-dks', filter_algorithm=['{}-lmcut-dks-liftedsymmetries-stabinit-noneofthose'.format(REVISION)])
    exp.add_fetcher('data/2018-05-30-ground-symmetries-dks-eval', filter_algorithm=['{}-lmcut-dks'.format(REVISION)])

    def duplicate_attribute(props):
        props['time_symmetries'] = props.get('translator_time_symmetries0_computing_symmetries', None)
        return props

    exp.add_absolute_report_step(attributes=attributes,filter_domain=suite,filter=[duplicate_attribute])

    exp.add_report(AbsoluteReport(attributes=attributes,filter_domain=suite_without_duplicates,filter=[duplicate_attribute]),outfile='{}-noduplicates.html'.format(exp.name))

    exp.run_steps()

main(revisions=[])
