#! /usr/bin/env python

import re

from lab.parser import Parser

parser = Parser()
parser.add_pattern('generator_count_lifted', 'Number of lifted generators: (\d+)', required=False, type=int)
parser.add_pattern('generator_count_lifted_mapping_objects_predicates', 'Number of lifted generators mapping predicates or objects: (\d+)', required=False, type=int)
parser.add_pattern('generator_order_lifted_2', 'Lifted generator order 2: (\d+)', required=False, type=int)
parser.add_pattern('generator_order_lifted_3', 'Lifted generator order 3: (\d+)', required=False, type=int)
parser.add_pattern('generator_order_lifted_4', 'Lifted generator order 4: (\d+)', required=False, type=int)
parser.add_pattern('generator_order_lifted_5', 'Lifted generator order 5: (\d+)', required=False, type=int)
parser.add_pattern('generator_order_lifted_6', 'Lifted generator order 6: (\d+)', required=False, type=int)
parser.add_pattern('generator_order_lifted_7', 'Lifted generator order 7: (\d+)', required=False, type=int)
parser.add_pattern('generator_order_lifted_8', 'Lifted generator order 8: (\d+)', required=False, type=int)
parser.add_pattern('generator_order_lifted_9', 'Lifted generator order 9: (\d+)', required=False, type=int)
parser.add_pattern('generator_order_lifted_max', 'Maximum generator order: (\d+)', required=False, type=int)
parser.add_pattern('generator_count_grounded_1_after_grounding', '(\d+) out of \d+ generators left after grounding them', required=False, type=int)
parser.add_pattern('generator_count_grounded_2_after_sas_task', '(\d+) out of \d+ generators left after the sas task has been created', required=False, type=int)
parser.add_pattern('generator_count_grounded_3_after_filtering_props', '(\d+) out of \d+ generators left after filtering unreachable propositions', required=False, type=int)
parser.add_pattern('generator_count_grounded_4_after_reordering_filtering_vars', '(\d+) out of \d+ generators left after reordering and filtering variables', required=False, type=int)
parser.add_pattern('generator_count_grounded', 'Number of remaining grounded generators: (\d+)', required=False, type=int)
parser.add_pattern('generator_count_removed', 'Number of removed generators: (\d+)', required=False, type=int)
parser.add_pattern('time_symmetries1_symmetry_graph', 'Done creating symmetry graph: (.+)s', required=False, type=float)
parser.add_pattern('time_symmetries2_bliss', 'Done searching for automorphisms: (.+)s', required=False, type=float)
parser.add_pattern('time_symmetries3_translate_automorphisms', 'Done translating automorphisms: (.+)s', required=False, type=float)
parser.add_pattern('generator_order_grounded_2', 'Grounded generator order 2: (\d+)', required=False, type=int)
parser.add_pattern('generator_order_grounded_3', 'Grounded generator order 3: (\d+)', required=False, type=int)
parser.add_pattern('generator_order_grounded_4', 'Grounded generator order 4: (\d+)', required=False, type=int)
parser.add_pattern('generator_order_grounded_5', 'Grounded generator order 5: (\d+)', required=False, type=int)
parser.add_pattern('generator_order_grounded_6', 'Grounded generator order 6: (\d+)', required=False, type=int)
parser.add_pattern('generator_order_grounded_7', 'Grounded generator order 7: (\d+)', required=False, type=int)
parser.add_pattern('generator_order_grounded_8', 'Grounded generator order 8: (\d+)', required=False, type=int)
parser.add_pattern('generator_order_grounded_9', 'Grounded generator order 9: (\d+)', required=False, type=int)

def add_composed_attributes(content, props):
    generator_count_lifted = props.get('generator_count_lifted', 0)
    generator_count_grounded = props.get('generator_count_grounded', 0)
    props['generator_count_lifted_grounded'] = "{}/{}".format(generator_count_lifted, generator_count_grounded)

    translator_time_done = props.get('translator_time_done', None)
    translator_completed = False
    if translator_time_done is not None:
        translator_completed = True
    props['translator_completed'] = translator_completed

parser.add_function(add_composed_attributes)

def parse_generator_orders(content, props):
    lifted_generator_orders = re.findall(r'Lifted generator orders: \[(.*)\]', content)
    props['generator_orders_lifted'] = lifted_generator_orders
    lifted_generator_orders_list = re.findall(r'Lifted generator orders list: \[(.*)\]', content)
    props['generator_orders_lifted_list'] = lifted_generator_orders_list
    grounded_generator_orders = re.findall(r'Grounded generator orders: \[(.*)\]', content)
    props['generator_orders_grounded'] = grounded_generator_orders
    grounded_generator_orders_list = re.findall(r'Grounded generator orders list: \[(.*)\]', content)
    props['generator_orders_grounded_list'] = grounded_generator_orders_list

parser.add_function(parse_generator_orders)

def parse_boolean_flags(content, props):
    bliss_memory_out = False
    bliss_timeout = False
    generator_lifted_affecting_actions_axioms = False
    generator_lifted_mapping_actions_axioms = False
    generator_not_well_defined_for_search = False
    ignore_none_of_those_mapping = False
    simplify_var_removed = False
    simplify_val_removed = False
    reorder_var_removed = False
    lines = content.split('\n')
    for line in lines:
        if 'Bliss memory out' in line:
            bliss_memory_out = True

        if 'Bliss timeout' in line:
            bliss_timeout = True

        if 'Generator affects operator or axiom' in line:
            generator_lifted_affecting_actions_axioms = True

        if 'Generator entirely maps operator or axioms' in line:
            generator_lifted_mapping_actions_axioms = True

        if 'Transformed generator contains -1' in line:
            generator_not_well_defined_for_search = True

        if 'Invalid mapping can be ignored because it affects none-of-those-values' in line:
            ignore_none_of_those_mapping = True

        if 'simplify: only one of from_var and to_var are removed, invalid generator' in line:
            simplify_var_removed = True

        if 'simplify: only one of from_val and to_val are mapped always_false, invalid generator' in line:
            simplify_val_removed = True

        if 'reorder: only one of from_var and to_var are removed, invalid generator' in line:
            reorder_var_removed = True

    props['bliss_out_of_memory'] = bliss_memory_out
    props['bliss_out_of_time'] = bliss_timeout
    props['generator_lifted_affecting_actions_axioms'] = generator_lifted_affecting_actions_axioms
    props['generator_lifted_mapping_actions_axioms'] = generator_lifted_mapping_actions_axioms
    props['generator_not_well_defined_for_search'] = generator_not_well_defined_for_search
    props['ignore_none_of_those_mapping'] = ignore_none_of_those_mapping
    props['simplify_var_removed'] = simplify_var_removed
    props['simplify_val_removed'] = simplify_val_removed
    props['reorder_var_removed'] = reorder_var_removed


parser.add_function(parse_boolean_flags)

def parse_errors(content, props):
    if 'error' in props:
        return

    exitcode = props['fast-downward_returncode']
    props['translate_out_of_time'] = False
    if exitcode == 0:
        props['error'] = 'none'
    elif exitcode == 232: # -24 means timeout
        props['translate_out_of_time'] = True
        props['error'] = 'timeout'
    elif exitcode == 1 and props['translate_out_of_memory'] == True:
        # we observed exit code 1 if python threw a MemoryError
        props['error'] = 'out-of-memory'
    else:
        props['error'] = 'unexplained-exitcode-%d' % exitcode

parser.add_function(parse_errors)

def parse_memory_error(content, props):
    translate_out_of_memory = False
    lines = content.split('\n')
    for line in lines:
        if line == 'MemoryError':
            translate_out_of_memory = true
    props['translate_out_of_memory'] = translate_out_of_memory

parser.add_function(parse_memory_error, file='run.err')

parser.parse()
