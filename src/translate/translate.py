#! /usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function

import sys

def python_version_supported():
    major, minor = sys.version_info[:2]
    return (major == 2 and minor >= 7) or (major, minor) >= (3, 2)

if not python_version_supported():
    sys.exit("Error: Translator only supports Python >= 2.7 and Python >= 3.2.")


from collections import defaultdict
from copy import deepcopy
from itertools import product

import axiom_rules
import fact_groups
import instantiate
import normalize
import options
import pddl
import pddl_parser
import sas_tasks
import simplify
import symmetries_module
import timers
import tools
import variable_order

# TODO: The translator may generate trivial derived variables which are always
# true, for example if there ia a derived predicate in the input that only
# depends on (non-derived) variables which are detected as always true.
# Such a situation was encountered in the PSR-STRIPS-DerivedPredicates domain.
# Such "always-true" variables should best be compiled away, but it is
# not clear what the best place to do this should be. Similar
# simplifications might be possible elsewhere, for example if a
# derived variable is synonymous with another variable (derived or
# non-derived).

DEBUG = False
DUMP = False

simplified_effect_condition_counter = 0
added_implied_precondition_counter = 0


def strips_to_sas_dictionary(groups, assert_partial):
    dictionary = {}
    for var_no, group in enumerate(groups):
        for val_no, atom in enumerate(group):
            dictionary.setdefault(atom, []).append((var_no, val_no))
    if assert_partial:
        assert all(len(sas_pairs) == 1
                   for sas_pairs in dictionary.values())
    return [len(group) + 1 for group in groups], dictionary


def translate_strips_conditions_aux(conditions, dictionary, ranges):
    condition = {}
    for fact in conditions:
        if fact.negated:
            # we handle negative conditions later, because then we
            # can recognize when the negative condition is already
            # ensured by a positive condition
            continue
        for var, val in dictionary.get(fact, ()):
            # The default () here is a bit of a hack. For goals (but
            # only for goals!), we can get static facts here. They
            # cannot be statically false (that would have been
            # detected earlier), and hence they are statically true
            # and don't need to be translated.
            # TODO: This would not be necessary if we dealt with goals
            # in the same way we deal with operator preconditions etc.,
            # where static facts disappear during grounding. So change
            # this when the goal code is refactored (also below). (**)
            if (condition.get(var) is not None and
                    val not in condition.get(var)):
                # Conflicting conditions on this variable: Operator invalid.
                return None
            condition[var] = set([val])

    def number_of_values(var_vals_pair):
        var, vals = var_vals_pair
        return len(vals)

    for fact in conditions:
        if fact.negated:
           ## Note  Here we use a different solution than in Sec. 10.6.4
           ##       of the thesis. Compare the last sentences of the third
           ##       paragraph of the section.
           ##       We could do what is written there. As a test case,
           ##       consider Airport ADL tasks with only one airport, where
           ##       (occupied ?x) variables are encoded in a single variable,
           ##       and conditions like (not (occupied ?x)) do occur in
           ##       preconditions.
           ##       However, here we avoid introducing new derived predicates
           ##       by treat the negative precondition as a disjunctive
           ##       precondition and expanding it by "multiplying out" the
           ##       possibilities.  This can lead to an exponential blow-up so
           ##       it would be nice to choose the behaviour as an option.
            done = False
            new_condition = {}
            atom = pddl.Atom(fact.predicate, fact.args)  # force positive
            for var, val in dictionary.get(atom, ()):
                # see comment (**) above
                poss_vals = set(range(ranges[var]))
                poss_vals.remove(val)

                if condition.get(var) is None:
                    assert new_condition.get(var) is None
                    new_condition[var] = poss_vals
                else:
                    # constrain existing condition on var
                    prev_possible_vals = condition.get(var)
                    done = True
                    prev_possible_vals.intersection_update(poss_vals)
                    if len(prev_possible_vals) == 0:
                        # Conflicting conditions on this variable:
                        # Operator invalid.
                        return None

            if not done and len(new_condition) != 0:
                # we did not enforce the negative condition by constraining
                # an existing condition on one of the variables representing
                # this atom. So we need to introduce a new condition:
                # We can select any from new_condition and currently prefer the
                # smallest one.
                candidates = sorted(new_condition.items(), key=number_of_values)
                var, vals = candidates[0]
                condition[var] = vals

        def multiply_out(condition):  # destroys the input
            sorted_conds = sorted(condition.items(), key=number_of_values)
            flat_conds = [{}]
            for var, vals in sorted_conds:
                if len(vals) == 1:
                    for cond in flat_conds:
                        cond[var] = vals.pop()  # destroys the input here
                else:
                    new_conds = []
                    for cond in flat_conds:
                        for val in vals:
                            new_cond = deepcopy(cond)
                            new_cond[var] = val
                            new_conds.append(new_cond)
                    flat_conds = new_conds
            return flat_conds

    return multiply_out(condition)


def translate_strips_conditions(conditions, dictionary, ranges,
                                mutex_dict, mutex_ranges):
    if not conditions:
        return [{}]  # Quick exit for common case.

    # Check if the condition violates any mutexes.
    if translate_strips_conditions_aux(conditions, mutex_dict,
                                       mutex_ranges) is None:
        return None

    return translate_strips_conditions_aux(conditions, dictionary, ranges)


def translate_strips_operator(operator, dictionary, ranges, mutex_dict,
                              mutex_ranges, implied_facts):
    conditions = translate_strips_conditions(operator.precondition, dictionary,
                                             ranges, mutex_dict, mutex_ranges)
    if conditions is None:
        return []
    sas_operators = []
    for condition in conditions:
        op = translate_strips_operator_aux(operator, dictionary, ranges,
                                           mutex_dict, mutex_ranges,
                                           implied_facts, condition)
        if op is not None:
            sas_operators.append(op)
    return sas_operators


def negate_and_translate_condition(condition, dictionary, ranges, mutex_dict,
                                   mutex_ranges):
    # condition is a list of lists of literals (DNF)
    # the result is the negation of the condition in DNF in
    # finite-domain representation (a list of dictionaries that map
    # variables to values)
    negation = []
    if [] in condition:  # condition always satisfied
        return None  # negation unsatisfiable
    for combination in product(*condition):
        cond = [l.negate() for l in combination]
        cond = translate_strips_conditions(cond, dictionary, ranges,
                                           mutex_dict, mutex_ranges)
        if cond is not None:
            negation.extend(cond)
    return negation if negation else None


def translate_strips_operator_aux(operator, dictionary, ranges, mutex_dict,
                                  mutex_ranges, implied_facts, condition):

    # collect all add effects
    effects_by_variable = defaultdict(lambda: defaultdict(list))
    # effects_by_variables: var -> val -> list(FDR conditions)
    add_conds_by_variable = defaultdict(list)
    for conditions, fact in operator.add_effects:
        eff_condition_list = translate_strips_conditions(conditions, dictionary,
                                                         ranges, mutex_dict,
                                                         mutex_ranges)
        if eff_condition_list is None:  # Impossible condition for this effect.
            continue
        for var, val in dictionary[fact]:
            effects_by_variable[var][val].extend(eff_condition_list)
            add_conds_by_variable[var].append(conditions)

    # collect all del effects
    del_effects_by_variable = defaultdict(lambda: defaultdict(list))
    for conditions, fact in operator.del_effects:
        eff_condition_list = translate_strips_conditions(conditions, dictionary,
                                                         ranges, mutex_dict,
                                                         mutex_ranges)
        if eff_condition_list is None:  # Impossible condition for this effect.
            continue
        for var, val in dictionary[fact]:
            del_effects_by_variable[var][val].extend(eff_condition_list)

    # add effect var=none_of_those for all del effects with the additional
    # condition that the deleted value has been true and no add effect triggers
    for var in del_effects_by_variable:
        no_add_effect_condition = negate_and_translate_condition(
            add_conds_by_variable[var], dictionary, ranges, mutex_dict,
            mutex_ranges)
        if no_add_effect_condition is None:  # there is always an add effect
            continue
        none_of_those = ranges[var] - 1
        for val, conds in del_effects_by_variable[var].items():
            for cond in conds:
                # add guard
                if var in cond and cond[var] != val:
                    continue  # condition inconsistent with deleted atom
                cond[var] = val
                # add condition that no add effect triggers
                for no_add_cond in no_add_effect_condition:
                    new_cond = dict(cond)
                    # This is a rather expensive step. We try every no_add_cond
                    # with every condition of the delete effect and discard the
                    # overal combination if it is unsatisfiable. Since
                    # no_add_effect_condition is precomputed it can contain many
                    # no_add_conds in which a certain literal occurs. So if cond
                    # plus the literal is already unsatisfiable, we still try
                    # all these combinations. A possible optimization would be
                    # to re-compute no_add_effect_condition for every delete
                    # effect and to unfold the product(*condition) in
                    # negate_and_translate_condition to allow an early break.
                    for cvar, cval in no_add_cond.items():
                        if cvar in new_cond and new_cond[cvar] != cval:
                            # the del effect condition plus the deleted atom
                            # imply that some add effect on the variable
                            # triggers
                            break
                        new_cond[cvar] = cval
                    else:
                        effects_by_variable[var][none_of_those].append(new_cond)

    return build_sas_operator(operator.name, condition, effects_by_variable,
                              operator.cost, ranges, implied_facts)


def build_sas_operator(name, condition, effects_by_variable, cost, ranges,
                       implied_facts):
    if options.add_implied_preconditions:
        implied_precondition = set()
        for fact in condition.items():
            implied_precondition.update(implied_facts[fact])
    prevail_and_pre = dict(condition)
    pre_post = []
    for var in effects_by_variable:
        orig_pre = condition.get(var, -1)
        added_effect = False
        for post, eff_conditions in effects_by_variable[var].items():
            pre = orig_pre
            # if the effect does not change the variable value, we ignore it
            if pre == post:
                continue
            eff_condition_lists = [sorted(eff_cond.items())
                                   for eff_cond in eff_conditions]
            if ranges[var] == 2:
                # Apply simplifications for binary variables.
                if prune_stupid_effect_conditions(var, post,
                                                  eff_condition_lists):
                    global simplified_effect_condition_counter
                    simplified_effect_condition_counter += 1
                if (options.add_implied_preconditions and pre == -1 and
                        (var, 1 - post) in implied_precondition):
                    global added_implied_precondition_counter
                    added_implied_precondition_counter += 1
                    pre = 1 - post
            for eff_condition in eff_condition_lists:
                # we do not need to represent a precondition as effect condition
                # and we do not want to keep an effect whose condition contradicts
                # a pre- or prevail condition
                filtered_eff_condition = []
                eff_condition_contradicts_precondition = False
                for variable, value in eff_condition:
                    if variable in prevail_and_pre:
                        if prevail_and_pre[variable] != value:
                            eff_condition_contradicts_precondition = True
                            break
                    else:
                        filtered_eff_condition.append((variable, value))
                if eff_condition_contradicts_precondition:
                    continue
                pre_post.append((var, pre, post, filtered_eff_condition))
                added_effect = True
        if added_effect:
            # the condition on var is not a prevail condition but a
            # precondition, so we remove it from the prevail condition
            condition.pop(var, -1)
    if not pre_post:  # operator is noop
        return None
    prevail = list(condition.items())
    return sas_tasks.SASOperator(name, prevail, pre_post, cost)


def prune_stupid_effect_conditions(var, val, conditions):
    ## (IF <conditions> THEN <var> := <val>) is a conditional effect.
    ## <var> is guaranteed to be a binary variable.
    ## <conditions> is in DNF representation (list of lists).
    ##
    ## We simplify <conditions> by applying two rules:
    ## 1. Conditions of the form "var = dualval" where var is the
    ##    effect variable and dualval != val can be omitted.
    ##    (If var != dualval, then var == val because it is binary,
    ##    which means that in such situations the effect is a no-op.)
    ## 2. If conditions contains any empty list, it is equivalent
    ##    to True and we can remove all other disjuncts.
    ##
    ## returns True when anything was changed
    if conditions == [[]]:
        return False  # Quick exit for common case.
    assert val in [0, 1]
    dual_fact = (var, 1 - val)
    simplified = False
    for condition in conditions:
        # Apply rule 1.
        while dual_fact in condition:
            # print "*** Removing dual condition"
            simplified = True
            condition.remove(dual_fact)
        # Apply rule 2.
        if not condition:
            conditions[:] = [[]]
            simplified = True
            break
    return simplified


def translate_strips_axiom(axiom, dictionary, ranges, mutex_dict, mutex_ranges):
    conditions = translate_strips_conditions(axiom.condition, dictionary,
                                             ranges, mutex_dict, mutex_ranges)
    if conditions is None:
        return []
    if axiom.effect.negated:
        [(var, _)] = dictionary[axiom.effect.positive()]
        effect = (var, ranges[var] - 1)
    else:
        [effect] = dictionary[axiom.effect]
    axioms = []
    for condition in conditions:
        axioms.append(sas_tasks.SASAxiom(condition.items(), effect))
    return axioms


def translate_strips_operators(actions, strips_to_sas, ranges, mutex_dict,
                               mutex_ranges, implied_facts):
    result = []
    for action in actions:
        sas_ops = translate_strips_operator(action, strips_to_sas, ranges,
                                            mutex_dict, mutex_ranges,
                                            implied_facts)
        result.extend(sas_ops)
    return result


def translate_strips_axioms(axioms, strips_to_sas, ranges, mutex_dict,
                            mutex_ranges):
    result = []
    for axiom in axioms:
        sas_axioms = translate_strips_axiom(axiom, strips_to_sas, ranges,
                                            mutex_dict, mutex_ranges)
        result.extend(sas_axioms)
    return result


def dump_task(init, goals, actions, axioms, axiom_layer_dict):
    old_stdout = sys.stdout
    with open("output.dump", "w") as dump_file:
        sys.stdout = dump_file
        print("Initial state")
        for atom in init:
            print(atom)
        print()
        print("Goals")
        for goal in goals:
            print(goal)
        for action in actions:
            print()
            print("Action")
            action.dump()
        for axiom in axioms:
            print()
            print("Axiom")
            axiom.dump()
        print()
        print("Axiom layers")
        for atom, layer in axiom_layer_dict.items():
            print("%s: layer %d" % (atom, layer))
    sys.stdout = old_stdout


def translate_task(strips_to_sas, ranges, translation_key,
                   mutex_dict, mutex_ranges, mutex_key,
                   init, goals,
                   actions, axioms, metric, implied_facts):
    with timers.timing("Processing axioms", block=True):
        axioms, axiom_init, axiom_layer_dict = axiom_rules.handle_axioms(
            actions, axioms, goals)
    init = init + axiom_init
    #axioms.sort(key=lambda axiom: axiom.name)
    #for axiom in axioms:
    #  axiom.dump()

    if options.dump_task:
        # Remove init facts that don't occur in strips_to_sas: they're constant.
        nonconstant_init = filter(strips_to_sas.get, init)
        dump_task(nonconstant_init, goals, actions, axioms, axiom_layer_dict)

    init_values = [rang - 1 for rang in ranges]
    # Closed World Assumption: Initialize to "range - 1" == Nothing.
    for fact in init:
        pairs = strips_to_sas.get(fact, [])  # empty for static init facts
        for var, val in pairs:
            curr_val = init_values[var]
            if curr_val != ranges[var] - 1 and curr_val != val:
                assert False, "Inconsistent init facts! [fact = %s]" % fact
            init_values[var] = val
    init = sas_tasks.SASInit(init_values)

    goal_dict_list = translate_strips_conditions(goals, strips_to_sas, ranges,
                                                 mutex_dict, mutex_ranges)
    if goal_dict_list is None:
        # "None" is a signal that the goal is unreachable because it
        # violates a mutex.
        return unsolvable_sas_task("Goal violates a mutex")

    assert len(goal_dict_list) == 1, "Negative goal not supported"
    ## we could substitute the negative goal literal in
    ## normalize.substitute_complicated_goal, using an axiom. We currently
    ## don't do this, because we don't run into this assertion, if the
    ## negative goal is part of finite domain variable with only two
    ## values, which is most of the time the case, and hence refrain from
    ## introducing axioms (that are not supported by all heuristics)
    goal_pairs = list(goal_dict_list[0].items())
    if not goal_pairs:
        return solvable_sas_task("Empty goal")
    goal = sas_tasks.SASGoal(goal_pairs)

    operators = translate_strips_operators(actions, strips_to_sas, ranges,
                                           mutex_dict, mutex_ranges,
                                           implied_facts)
    axioms = translate_strips_axioms(axioms, strips_to_sas, ranges, mutex_dict,
                                     mutex_ranges)

    axiom_layers = [-1] * len(ranges)
    for atom, layer in axiom_layer_dict.items():
        assert layer >= 0
        [(var, val)] = strips_to_sas[atom]
        axiom_layers[var] = layer
    variables = sas_tasks.SASVariables(ranges, axiom_layers, translation_key)
    mutexes = [sas_tasks.SASMutexGroup(group) for group in mutex_key]
    return sas_tasks.SASTask(variables, mutexes, init, goal,
                             operators, axioms, metric)


def trivial_task(solvable):
    variables = sas_tasks.SASVariables(
        [2], [-1], [["Atom dummy(val1)", "Atom dummy(val2)"]])
    # We create no mutexes: the only possible mutex is between
    # dummy(val1) and dummy(val2), but the preprocessor would filter
    # it out anyway since it is trivial (only involves one
    # finite-domain variable).
    mutexes = []
    init = sas_tasks.SASInit([0])
    if solvable:
        goal_fact = (0, 0)
    else:
        goal_fact = (0, 1)
    goal = sas_tasks.SASGoal([goal_fact])
    operators = []
    axioms = []
    metric = True
    return sas_tasks.SASTask(variables, mutexes, init, goal,
                             operators, axioms, metric)

def solvable_sas_task(msg):
    print("%s! Generating solvable task..." % msg)
    return trivial_task(solvable=True)

def unsolvable_sas_task(msg):
    print("%s! Generating unsolvable task..." % msg)
    return trivial_task(solvable=False)


def is_permutation(sas_generator):
    # Caution! If the given sas_generator maps two keys to the same value,
    # this check may fail and loop forever.
    for start_key in sas_generator.keys():
        current_key = sas_generator[start_key]
        while current_key != start_key:
            if not current_key in sas_generator.keys():
                return False
            current_key = tuple(sas_generator[current_key])
    return True


def is_identity(sas_generator):
    for key in sas_generator.keys():
        if sas_generator[key] != key:
            return False
    return True


def filter_out_identities_or_nonpermutations(sas_generators):
    # Return an updated list of generators, containing only "valid" generators,
    # i.e. generators that are a permutation and not the identity.
    remaining_generators = []
    for sas_generator in sas_generators:
        if is_identity(sas_generator) or not is_permutation(sas_generator):
            if DUMP:
                print(sas_generator)
                print("is not a permutation or is the identiy!")
        else:
            remaining_generators.append(sas_generator)
    return remaining_generators


def gcd(a, b):
    """Return greatest common divisor using Euclid's Algorithm."""
    while b:
        a, b = b, a % b
    return a


def lcm(a, b):
    """Return lowest common multiple."""
    return a * b // gcd(a, b)


def compute_order(sas_generator):
    visited_keys = set()
    order = 1
    for start_key in sas_generator.keys():
        if not start_key in visited_keys:
            cycle_size = 1
            visited_keys.add(start_key)
            current_key = sas_generator[start_key]
            while current_key != start_key:
                current_key = tuple(sas_generator[current_key])
                visited_keys.add(current_key)
                cycle_size += 1
            order = lcm(order, cycle_size)
    return order


def print_sas_generator(sas_generator):
    for from_fact in sorted(sas_generator.keys()):
        to_fact = sas_generator[from_fact]
        if from_fact != to_fact:
            print("{} -> {}".format(from_fact, sas_generator[from_fact]))


def pddl_to_sas(task):
    with timers.timing("Instantiating", block=True):
        (relaxed_reachable, atoms, actions, axioms,
         reachable_action_params) = instantiate.explore(task)

    if not relaxed_reachable:
        return unsolvable_sas_task("No relaxed solution")

    # HACK! Goals should be treated differently.
    if isinstance(task.goal, pddl.Conjunction):
        goal_list = task.goal.parts
    else:
        goal_list = [task.goal]
    for item in goal_list:
        assert isinstance(item, pddl.Literal)

    with timers.timing("Computing fact groups", block=True):
        groups, mutex_groups, translation_key = fact_groups.compute_groups(
            task, atoms, reachable_action_params)

    with timers.timing("Building STRIPS to SAS dictionary"):
        ranges, strips_to_sas = strips_to_sas_dictionary(
            groups, assert_partial=options.use_partial_encoding)

    sas_generators = []
    with timers.timing("Symmetries2 grounding generators into SAS", block=True):
        # For each generator, create its sas mapping from var-vals to var-vals
        for generator in task.generators:
            if DUMP:
                print("Considering generator: ")
                generator.dump()
            sas_generator = {}
            valid_generator = True
            for atom, var_val_list in strips_to_sas.items():
                if not len(var_val_list) == 1:
                    raise NotImplementedError("Using the option --full-encoding "
                    "with --compute-symmetries is not implemented!")
                mapped_atom = generator.apply_to_atom(atom)
                mapped_var_val_list = strips_to_sas.get(mapped_atom, None)
                if DUMP:
                    if atom != mapped_atom:
                        print("mapping atom {} to atom {}".format(atom, mapped_atom))
                if mapped_var_val_list is None:
                    if DUMP:
                        print("need to skip generator because it maps an atom to some "
                              "atom which does not exist in the sas representation")
                    valid_generator = False
                    break
                if not len(mapped_var_val_list) == 1:
                    raise NotImplementedError("Using the option --full-encoding "
                    "with --compute-symmetries is not implemented!")
                mapped_var_val = mapped_var_val_list[0]
                var_val = var_val_list[0]
                sas_generator[var_val] = mapped_var_val
            if valid_generator:
                if DUMP:
                    print("Transformed generator: ")
                    print_sas_generator(sas_generator)
                assert is_permutation(sas_generator)
                if not is_identity(sas_generator):
                    sas_generators.append(sas_generator)
                else:
                    if DUMP:
                        print("need to skip generator because it is the identiy")
        if task.generators:
            print("{} out of {} generators left after grounding them".format(len(sas_generators), len(task.generators)))


    with timers.timing("Building dictionary for full mutex groups"):
        mutex_ranges, mutex_dict = strips_to_sas_dictionary(
            mutex_groups, assert_partial=False)

    if options.add_implied_preconditions:
        with timers.timing("Building implied facts dictionary..."):
            implied_facts = build_implied_facts(strips_to_sas, groups,
                                                mutex_groups)
    else:
        implied_facts = {}

    with timers.timing("Building mutex information", block=True):
        mutex_key = build_mutex_key(strips_to_sas, mutex_groups)

    with timers.timing("Translating task", block=True):
        sas_task = translate_task(
            strips_to_sas, ranges, translation_key,
            mutex_dict, mutex_ranges, mutex_key,
            task.init, goal_list, actions, axioms, task.use_min_cost_metric,
            implied_facts)

    print("%d effect conditions simplified" %
          simplified_effect_condition_counter)
    print("%d implied preconditions added" %
          added_implied_precondition_counter)

    with timers.timing("Symmetries3 add none-of-those mappings and remove deleted facts", block=True):
        if sas_generators:
            # Go over all facts of the sas task and all generators and remove
            # all facts from the generators that are not present in the task
            # anymore. We do not add mappings for none-of-those values.
            facts = []
            for var, var_range in enumerate(sas_task.variables.ranges):
                for val in range(var_range):
                    facts.append((var, val))
            for sas_generator in sas_generators:
                for from_var_val, to_var_val in sas_generator.items():
                    if from_var_val not in facts or to_var_val not in facts:
                        del sas_generator[from_var_val]
            sas_generators = filter_out_identities_or_nonpermutations(sas_generators)
            if DUMP:
                for sas_generator in sas_generators:
                    print("generator: ")
                    print_sas_generator(sas_generator)
            print("{} out of {} generators left after the sas task has been created".format(len(sas_generators), len(task.generators)))

    if options.filter_unreachable_facts:
        with timers.timing("Detecting unreachable propositions", block=True):
            try:
                sas_generators = simplify.filter_unreachable_propositions(sas_task, sas_generators)
            except simplify.Impossible:
                return unsolvable_sas_task("Simplified to trivially false goal")
            except simplify.TriviallySolvable:
                return solvable_sas_task("Simplified to empty goal")
            if sas_generators:
                sas_generators = filter_out_identities_or_nonpermutations(sas_generators)
                if DUMP:
                    for sas_generator in sas_generators:
                        print("generator: ")
                        print_sas_generator(sas_generator)
                print("{} out of {} generators left after filtering unreachable propositions".format(len(sas_generators), len(task.generators)))

    if options.reorder_variables or options.filter_unimportant_vars:
        with timers.timing("Reordering and filtering variables", block=True):
            sas_generators = variable_order.find_and_apply_variable_order(
                sas_task,
                sas_generators,
                options.reorder_variables,
                options.filter_unimportant_vars)
            if sas_generators:
                sas_generators = filter_out_identities_or_nonpermutations(sas_generators)
                if DUMP:
                    for sas_generator in sas_generators:
                        print("generator: ")
                        print_sas_generator(sas_generator)
                print("{} out of {} generators left after reordering and filtering variables".format(len(sas_generators), len(task.generators)))

    if task.generators:
        print("Number of remaining valid generators: {}".format(len(sas_generators)))
        print("Removed generators: {}".format(len(task.generators) - len(sas_generators)))
        order_to_generator_count = defaultdict(int)
        for sas_generator in sas_generators:
            order = compute_order(sas_generator)
            order_to_generator_count[order] += 1
        printable_order_to_count = [(order, count) for order, count in order_to_generator_count.items()]
        print("Generator orders: ", printable_order_to_count)
        for order in range(2, 10):
            print("Order {}: {}".format(order, order_to_generator_count[order]))

    with timers.timing("Symmetries4 transforming generators into search representation", block=True):
        if sas_generators:
            # Transform the sas generators into the format used by the search
            # component, i.e. [0...n-1; 0...range(var-1)-1, ..., 0...range(var-n)-1]
            # where the first n entries represent the mapping on variables, and
            # successive block represent the mapping of each variable's values.
            # For none-of-those-values, we use -1 to denote that the symmetry
            # is not defined for these.

            # Precompute some data structures to ease mapping from facts to indices
            # of the above representation.
            var_by_shifted_index = []
            var_to_start_index = []
            num_vars = len(sas_task.variables.ranges)
            num_indices = num_vars
            for var in range(num_vars):
                var_to_start_index.append(num_indices)
                num_indices += sas_task.variables.ranges[var]
                for val in range(sas_task.variables.ranges[var]):
                    var_by_shifted_index.append(var)

            def get_var_val_by_index(index):
                assert index >= num_vars
                var =  var_by_shifted_index[index - num_vars]
                val = index - var_to_start_index[var]
                return (var, val)

            def get_index_by_var_val((var, val)):
                index = var_to_start_index[var] + val
                assert num_vars <= index < num_indices
                return index

            facts = []
            for var, var_range in enumerate(sas_task.variables.ranges):
                for val in range(var_range):
                    facts.append((var, val))
            search_generators = []
            for sas_generator in sas_generators:
                transformed_generator = [-1 for x in range(num_indices)]
                for from_fact in facts:
                    to_fact = sas_generator.get(from_fact, None)
                    if to_fact is None:
                        continue
                    from_index = get_index_by_var_val(from_fact)
                    to_index = get_index_by_var_val(to_fact)
                    transformed_generator[from_index] = to_index

                    from_var = from_fact[0]
                    to_var = to_fact[0]
                    if transformed_generator[from_var] == -1:
                        transformed_generator[from_var] = to_var
                    else:
                        assert transformed_generator[from_var] == to_var
                if -1 in transformed_generator:
                    print("Transformed generator contains -1")

                search_generators.append(transformed_generator)
                #for from_index, to_index in enumerate(transformed_generator):
                    #if from_index < num_vars:
                        #continue
                    #from_fact = get_var_val_by_index(from_index)
                    #to_fact = get_var_val_by_index(to_index)
                    #assert sas_generator.get(from_fact, from_fact) == to_fact
                if DUMP:
                    print("original generator:")
                    print_sas_generator(sas_generator)
                    print("transformed_generator:")
                    print(transformed_generator)
            # Append the transformed generators to the task so that they are
            # written to the output.sas file.
            sas_task.search_generators = sas_tasks.SearchGenerators(
                var_by_shifted_index, var_to_start_index, search_generators)

    return sas_task


def build_mutex_key(strips_to_sas, groups):
    group_keys = []
    for group in groups:
        group_key = []
        for fact in group:
            if strips_to_sas.get(fact):
                for var, val in strips_to_sas[fact]:
                    group_key.append((var, val))
            else:
                print("not in strips_to_sas, left out:", fact)
        group_keys.append(group_key)
    return group_keys


def build_implied_facts(strips_to_sas, groups, mutex_groups):
    ## Compute a dictionary mapping facts (FDR pairs) to lists of FDR
    ## pairs implied by that fact. In other words, in all states
    ## containing p, all pairs in implied_facts[p] must also be true.
    ##
    ## There are two simple cases where a pair p implies a pair q != p
    ## in our FDR encodings:
    ## 1. p and q encode the same fact
    ## 2. p encodes a STRIPS proposition X, q encodes a STRIPS literal
    ##    "not Y", and X and Y are mutex.
    ##
    ## The first case cannot arise when we use partial encodings, and
    ## when we use full encodings, I don't think it would give us any
    ## additional information to exploit in the operator translation,
    ## so we only use the second case.
    ##
    ## Note that for a pair q to encode a fact "not Y", Y must form a
    ## fact group of size 1. We call such propositions Y "lonely".

    ## In the first step, we compute a dictionary mapping each lonely
    ## proposition to its variable number.
    lonely_propositions = {}
    for var_no, group in enumerate(groups):
        if len(group) == 1:
            lonely_prop = group[0]
            assert strips_to_sas[lonely_prop] == [(var_no, 0)]
            lonely_propositions[lonely_prop] = var_no

    ## Then we compute implied facts as follows: for each mutex group,
    ## check if prop is lonely (then and only then "not prop" has a
    ## representation as an FDR pair). In that case, all other facts
    ## in this mutex group imply "not prop".
    implied_facts = defaultdict(list)
    for mutex_group in mutex_groups:
        for prop in mutex_group:
            prop_var = lonely_propositions.get(prop)
            if prop_var is not None:
                prop_is_false = (prop_var, 1)
                for other_prop in mutex_group:
                    if other_prop is not prop:
                        for other_fact in strips_to_sas[other_prop]:
                            implied_facts[other_fact].append(prop_is_false)

    return implied_facts


def dump_statistics(sas_task):
    print("Translator variables: %d" % len(sas_task.variables.ranges))
    print(("Translator derived variables: %d" %
           len([layer for layer in sas_task.variables.axiom_layers
                if layer >= 0])))
    print("Translator facts: %d" % sum(sas_task.variables.ranges))
    print("Translator goal facts: %d" % len(sas_task.goal.pairs))
    print("Translator mutex groups: %d" % len(sas_task.mutexes))
    print(("Translator total mutex groups size: %d" %
           sum(mutex.get_encoding_size() for mutex in sas_task.mutexes)))
    print("Translator operators: %d" % len(sas_task.operators))
    print("Translator axioms: %d" % len(sas_task.axioms))
    print("Translator task size: %d" % sas_task.get_encoding_size())
    try:
        peak_memory = tools.get_peak_memory_in_kb()
    except Warning as warning:
        print(warning)
    else:
        print("Translator peak memory: %d KB" % peak_memory)

class Generator:
    def __init__(self, generator, task):
        # Transform generator into a tuple of dicts, mapping predicates
        # and objects, ignoring identity mappings.
        predicates = dict()
        objects = dict()
        for from_node, to_node in generator.items():
            assert isinstance(from_node, tuple)
            if (from_node[0] == symmetries_module.NodeType.predicate
                and from_node[1] != to_node[1]):
                predicates[from_node[1]] = to_node[1]
            if (from_node[0] == symmetries_module.NodeType.constant
                and from_node[1] != to_node[1]):
                objects[from_node[1]] = to_node[1]

            if from_node != to_node and from_node[0] in [symmetries_module.NodeType.operator, symmetries_module.NodeType.axiom]:
                print("Generator affects operator or axiom")
                assert len(from_node) == 3
                name = from_node[2]
                if name in [action.name for action in task.actions] or name in [axiom.name for axiom in task.axioms]:
                    print("Generator entirely maps operator or axioms")

        if predicates or objects:
            self.generator = (predicates, objects)
        else:
            self.generator = None

    def is_valid(self):
        return self.generator is not None

    def apply_to_atom(self, atom):
        assert self.is_valid()
        # If no entry is present, use identity mapping.
        predicate = self.generator[0].get(atom.predicate, atom.predicate)
        args = tuple(self.generator[1].get(a, a) for a in atom.args)
        return pddl.Atom(predicate, args)

    def dump(self):
        assert self.is_valid()
        print("Mapping objects: {}; Mapping predicates: {}".format(self.generator[0], self.generator[1]))

def main():
    timer = timers.Timer()
    with timers.timing("Parsing", True):
        task = pddl_parser.open(
            domain_filename=options.domain, task_filename=options.task)

    with timers.timing("Normalizing task"):
        normalize.normalize(task)

    if options.generate_relaxed_task:
        # Remove delete effects.
        for action in task.actions:
            for index, effect in reversed(list(enumerate(action.effects))):
                if effect.literal.negated:
                    del action.effects[index]

    if options.compute_symmetries:
        with timers.timing("Symmetries0 computing symmetries", block=True):
            only_object_symmetries = options.only_object_symmetries
            stabilize_initial_state = options.stabilize_initial_state
            time_limit = options.bliss_time_limit
            graph = symmetries_module.SymmetryGraph(task, only_object_symmetries, stabilize_initial_state)
            generators = graph.find_automorphisms(time_limit)
            if DUMP:
                graph.write_or_print_automorphisms(generators, dump=True)
            print("Number of lifted generators: {}".format(len(generators)))

        with timers.timing("Symmetries1 transforming generators into predicate object mappings", block=True):
            # Transform generators into suitable format, mapping predicates and objects.
            assert isinstance(task.generators, list)
            assert not task.generators
            for generator in generators:
                gen = Generator(generator, task)
                if gen.is_valid():
                    task.generators.append(gen)
                else:
                    print("Initial transformation already filtered out a generator")
            print("Number of lifted generators mapping predicates or objects: {}".format(len(task.generators)))

    sas_task = pddl_to_sas(task)
    dump_statistics(sas_task)

    with timers.timing("Writing output"):
        with open("output.sas", "w") as output_file:
            sas_task.output(output_file)
    print("Done! %s" % timer)


if __name__ == "__main__":
    main()
