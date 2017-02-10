#include "group.h"

#include "graph_creator.h"
#include "permutation.h"

#include "../global_state.h"
#include "../option_parser.h"
#include "../per_state_information.h"
#include "../plugin.h"
#include "../state_registry.h"

#include <algorithm>
#include <iostream>
#include <queue>


using namespace std;
using namespace utils;

Group::Group(const options::Options &opts)
    : stabilize_initial_state(opts.get<bool>("stabilize_initial_state")),
      search_symmetries(SearchSymmetries(opts.get_enum("search_symmetries"))),
      initialized(false) {
    graph_creator = new GraphCreator(opts);
}

Group::~Group() {
    delete_generators();
    delete graph_creator;
}

void Group::delete_generators() {
    for (size_t i = 0; i < generators.size(); ++i) {
        delete generators[i];
    }
    generators.clear();
}

const Permutation *Group::get_permutation(int index) const {
    return generators[index];
}

void Group::compute_symmetries() {
    assert(!initialized);
    initialized = true;
    if (!generators.empty() || !graph_creator) {
        cerr << "Already computed symmetries" << endl;
        exit_with(ExitCode::CRITICAL_ERROR);
    }
    if (!graph_creator->compute_symmetries(this)) {
        // Computing symmetries ran out of memory
        delete_generators();
    }
    delete graph_creator;
    graph_creator = 0;
}

/**
 * Add new permutation to the list of permutations
 * The function will be called from bliss
 */
void Group::add_permutation(void* param, unsigned int, const unsigned int * full_perm){
    Permutation *perm = new Permutation(full_perm);
    if (!perm->identity()){
        ((Group*) param)->add_generator(perm);
    } else {
        delete perm;
    }
}

void Group::add_generator(const Permutation *gen) {
    generators.push_back(gen);
}

int Group::get_num_generators() const {
    return generators.size();
}

void Group::dump_generators() const {
    if (get_num_generators() == 0)
        return;
    for (int i = 0; i < get_num_generators(); i++) {
        cout << "Generator " << i << endl;
        get_permutation(i)->print_cycle_notation();
        get_permutation(i)->dump_var_vals();
    }

    cout << "Extra group info:" << endl;
    cout << "Permutation length: " << Permutation::length << endl;
    cout << "Permutation variables by values (" << g_variable_domain.size() << "): " << endl;
    for (int i = g_variable_domain.size(); i < Permutation::length; i++)
        cout << Permutation::get_var_by_index(i) << "  " ;
    cout << endl;
}

void Group::statistics() const {
    int num_gen = get_num_generators();
    cout << "Number of generators: " << num_gen << endl;
    cout << "Order of generators: [";
    for (int gen_no = 0; gen_no < num_gen; ++gen_no) {
        cout << get_permutation(gen_no)->get_order();
        if (gen_no != num_gen - 1)
            cout << ", ";
    }
    cout << "]" << endl;
}


// ===============================================================================
// Methods related to OSS

int *Group::get_canonical_representative(const GlobalState &state) const {
    int *canonical_state = new int[g_variable_domain.size()];
    for (size_t i = 0; i < g_variable_domain.size(); ++i) {
        canonical_state[i] = state[i];
    }

    int size = get_num_generators();
    if (size == 0)
        return canonical_state;

    bool changed = true;
    while (changed) {
        changed = false;
        for (int i=0; i < size; i++) {
            if (generators[i]->replace_if_less(canonical_state)) {
                changed =  true;
            }
        }
    }
    return canonical_state;
}

Permutation *Group::compose_permutation(const Trace& perm_index) const {
    Permutation *new_perm = new Permutation();
    for (size_t i = 0; i < perm_index.size(); ++i) {
        Permutation *tmp = new Permutation(new_perm, get_permutation(perm_index[i]));
        delete new_perm;
        new_perm = tmp;
    }
    return new_perm;
}

void Group::get_trace(const GlobalState &state, Trace& full_trace) const {
    int size = get_num_generators();
    if (size == 0)
        return;

    int *temp_state = new int[g_variable_domain.size()];
    for(size_t i = 0; i < g_variable_domain.size(); ++i)
        temp_state[i] = state[i];
    bool changed = true;
    while (changed) {
        changed = false;
        for (int i=0; i < size; i++) {
            if (generators[i]->replace_if_less(temp_state)) {
                full_trace.push_back(i);
                changed = true;
            }
        }
    }
}

Permutation *Group::create_permutation_from_state_to_state(
        const GlobalState& from_state, const GlobalState& to_state) const {
    Trace new_trace;
    Trace curr_trace;
    get_trace(from_state, curr_trace);
    get_trace(to_state, new_trace);

    Permutation *tmp = compose_permutation(new_trace);
    Permutation *p1 = new Permutation(tmp, true);  //inverse
    delete tmp;
    Permutation *p2 = compose_permutation(curr_trace);
    Permutation *result = new Permutation(p2, p1);
    delete p1;
    delete p2;
    return result;
}

static Group *_parse(OptionParser &parser) {
    // General Bliss options
    parser.add_option<int>("time_bound",
                           "Stopping after the Bliss software reached the time bound",
                           "0");
//    parser.add_option<int>("generators_bound",
//                           "Number of found generators after which Bliss is stopped",
//                           "0");
    parser.add_option<bool>("stabilize_initial_state",
                            "Compute symmetries stabilizing the initial state",
                            "false");

    // Type of search symmetries to be used
    vector<string> search_symmetries;
    search_symmetries.push_back("NOSEARCHSYMMETRIES");
    search_symmetries.push_back("OSS");
    search_symmetries.push_back("DKS");
    parser.add_enum_option("search_symmetries",
                           search_symmetries,
                           "Choose the type of structural symmetries that "
                           "should be used for pruning: OSS for orbit space "
                           "search or DKS for storing the canonical "
                           "representative of every state during search",
                           "NOSEARCHSYMMETRIES");

    Options opts = parser.parse();

    if (!parser.dry_run()) {
        bool use_search_symmetries = opts.get_enum("search_symmetries");
        if (!use_search_symmetries) {
            cerr << "You have specified a symmetries option which does use "
                    "no search symmetries" << endl;
            exit_with(ExitCode::INPUT_ERROR);
        }
        return new Group(opts);
    } else {
        return 0;
    }
}

static Plugin<Group> _plugin("structural_symmetries", _parse);
