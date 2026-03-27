"""Phase 2 unit tests — _GraphEngine (in-house graph algorithms)."""

from __future__ import annotations

import pytest

from rh_cognitv_lite.orchestrators.graphs.dag_engine import _GraphEngine


# ─────────────────────────────────────────────
# Shared test graph fixtures
# ─────────────────────────────────────────────

# EMPTY — no nodes, no edges
EMPTY = _GraphEngine(set(), set())

# SINGLE — one isolated node
SINGLE = _GraphEngine({"A"}, set())

# LINEAR — A → B → C
LINEAR = _GraphEngine({"A", "B", "C"}, {("A", "B"), ("B", "C")})

# DIAMOND — A → B, A → C, B → D, C → D
DIAMOND = _GraphEngine(
    {"A", "B", "C", "D"},
    {("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")},
)

# FORK — A → B, A → C  (two leaves)
FORK = _GraphEngine({"A", "B", "C"}, {("A", "B"), ("A", "C")})

# JOIN — A → C, B → C  (two entries)
JOIN = _GraphEngine({"A", "B", "C"}, {("A", "C"), ("B", "C")})

# WIDE — two independent chains: A→B and C→D
WIDE = _GraphEngine(
    {"A", "B", "C", "D"},
    {("A", "B"), ("C", "D")},
)

# CYCLIC — A → B → C → A
CYCLIC = _GraphEngine(
    {"A", "B", "C"},
    {("A", "B"), ("B", "C"), ("C", "A")},
)

# SELF_LOOP — single node with a self-edge
SELF_LOOP = _GraphEngine({"A"}, {("A", "A")})


# ─────────────────────────────────────────────
# entry_nodes / leaf_nodes
# ─────────────────────────────────────────────

class TestEntryAndLeafNodes:
    def test_empty_graph_has_no_entries(self):
        assert EMPTY.entry_nodes() == set()

    def test_empty_graph_has_no_leaves(self):
        assert EMPTY.leaf_nodes() == set()

    def test_single_node_is_both_entry_and_leaf(self):
        assert SINGLE.entry_nodes() == {"A"}
        assert SINGLE.leaf_nodes() == {"A"}

    def test_linear_entry(self):
        assert LINEAR.entry_nodes() == {"A"}

    def test_linear_leaf(self):
        assert LINEAR.leaf_nodes() == {"C"}

    def test_diamond_entry(self):
        assert DIAMOND.entry_nodes() == {"A"}

    def test_diamond_leaf(self):
        assert DIAMOND.leaf_nodes() == {"D"}

    def test_fork_single_entry_two_leaves(self):
        assert FORK.entry_nodes() == {"A"}
        assert FORK.leaf_nodes() == {"B", "C"}

    def test_join_two_entries_single_leaf(self):
        assert JOIN.entry_nodes() == {"A", "B"}
        assert JOIN.leaf_nodes() == {"C"}

    def test_wide_two_entries_two_leaves(self):
        assert WIDE.entry_nodes() == {"A", "C"}
        assert WIDE.leaf_nodes() == {"B", "D"}

    def test_cyclic_graph_has_no_entries(self):
        # Every node in a pure cycle has in-degree 1
        assert CYCLIC.entry_nodes() == set()

    def test_cyclic_graph_has_no_leaves(self):
        assert CYCLIC.leaf_nodes() == set()


# ─────────────────────────────────────────────
# has_cycle / would_create_cycle
# ─────────────────────────────────────────────

class TestCycleDetection:
    def test_empty_graph_is_acyclic(self):
        assert EMPTY.has_cycle() is False

    def test_single_node_is_acyclic(self):
        assert SINGLE.has_cycle() is False

    def test_linear_chain_is_acyclic(self):
        assert LINEAR.has_cycle() is False

    def test_diamond_is_acyclic(self):
        assert DIAMOND.has_cycle() is False

    def test_cyclic_graph_detected(self):
        assert CYCLIC.has_cycle() is True

    def test_self_loop_is_cyclic(self):
        assert SELF_LOOP.has_cycle() is True

    def test_would_create_cycle_back_edge(self):
        # C → A would close the chain A → B → C
        assert LINEAR.would_create_cycle("C", "A") is True

    def test_would_create_cycle_self_loop(self):
        assert LINEAR.would_create_cycle("A", "A") is True

    def test_would_not_create_cycle_forward_edge(self):
        # A → C skips B but does not close a loop
        assert LINEAR.would_create_cycle("A", "C") is False

    def test_would_not_create_cycle_new_leaf(self):
        # Adding D (new) as a successor of C cannot create a cycle
        assert LINEAR.would_create_cycle("C", "D") is False

    def test_would_create_cycle_diamond_closing_edge(self):
        # D → A would close the diamond back to the entry
        assert DIAMOND.would_create_cycle("D", "A") is True

    def test_would_not_create_cycle_cross_edge_in_diamond(self):
        # B → C is a valid cross-edge; C cannot reach B
        assert DIAMOND.would_create_cycle("B", "C") is False


# ─────────────────────────────────────────────
# topological_generations
# ─────────────────────────────────────────────

class TestTopologicalGenerations:
    def test_empty_graph_returns_no_generations(self):
        assert TOPOLOGICAL_GENERATIONS_EMPTY() == []

    def test_single_node_one_generation(self):
        assert SINGLE.topological_generations() == [{"A"}]

    def test_linear_chain_three_generations(self):
        gens = LINEAR.topological_generations()
        assert gens == [{"A"}, {"B"}, {"C"}]

    def test_diamond_three_generations(self):
        gens = DIAMOND.topological_generations()
        assert len(gens) == 3
        assert gens[0] == {"A"}
        assert gens[1] == {"B", "C"}
        assert gens[2] == {"D"}

    def test_fork_two_generations(self):
        gens = FORK.topological_generations()
        assert len(gens) == 2
        assert gens[0] == {"A"}
        assert gens[1] == {"B", "C"}

    def test_join_two_generations(self):
        gens = JOIN.topological_generations()
        assert len(gens) == 2
        assert gens[0] == {"A", "B"}
        assert gens[1] == {"C"}

    def test_wide_two_independent_chains(self):
        gens = WIDE.topological_generations()
        assert len(gens) == 2
        assert gens[0] == {"A", "C"}
        assert gens[1] == {"B", "D"}

    def test_cyclic_graph_raises(self):
        with pytest.raises(ValueError, match="cycle"):
            CYCLIC.topological_generations()

    def test_all_nodes_covered(self):
        gens = DIAMOND.topological_generations()
        all_nodes = set().union(*gens)
        assert all_nodes == DIAMOND.nodes


def TOPOLOGICAL_GENERATIONS_EMPTY():
    return EMPTY.topological_generations()


# ─────────────────────────────────────────────
# descendants_of / is_reachable
# ─────────────────────────────────────────────

class TestReachability:
    def test_descendants_of_entry_in_linear(self):
        assert LINEAR.descendants_of("A") == {"B", "C"}

    def test_descendants_of_middle_in_linear(self):
        assert LINEAR.descendants_of("B") == {"C"}

    def test_descendants_of_leaf_is_empty(self):
        assert LINEAR.descendants_of("C") == set()

    def test_descendants_of_entry_in_diamond(self):
        assert DIAMOND.descendants_of("A") == {"B", "C", "D"}

    def test_descendants_of_middle_in_diamond(self):
        # B can reach D but not C (no B→C edge)
        assert DIAMOND.descendants_of("B") == {"D"}
        assert DIAMOND.descendants_of("C") == {"D"}

    def test_descendants_excludes_self(self):
        assert "A" not in LINEAR.descendants_of("A")

    def test_descendants_of_single_node(self):
        assert SINGLE.descendants_of("A") == set()

    def test_is_reachable_direct_edge(self):
        assert LINEAR.is_reachable("A", "B") is True

    def test_is_reachable_transitive(self):
        assert LINEAR.is_reachable("A", "C") is True

    def test_is_reachable_self(self):
        assert LINEAR.is_reachable("A", "A") is True

    def test_is_not_reachable_reverse_direction(self):
        assert LINEAR.is_reachable("C", "A") is False

    def test_is_not_reachable_disconnected(self):
        assert WIDE.is_reachable("A", "C") is False
        assert WIDE.is_reachable("A", "D") is False

    def test_is_reachable_across_diamond(self):
        assert DIAMOND.is_reachable("A", "D") is True
        assert DIAMOND.is_reachable("B", "D") is True
        # D cannot reach A
        assert DIAMOND.is_reachable("D", "A") is False


# ─────────────────────────────────────────────
# path_between
# ─────────────────────────────────────────────

class TestPathBetween:
    def test_path_self(self):
        assert LINEAR.path_between("A", "A") == ["A"]

    def test_path_direct_edge(self):
        assert LINEAR.path_between("A", "B") == ["A", "B"]

    def test_path_two_hops(self):
        assert LINEAR.path_between("A", "C") == ["A", "B", "C"]

    def test_path_unreachable_returns_none(self):
        assert LINEAR.path_between("C", "A") is None

    def test_path_disconnected_returns_none(self):
        assert WIDE.path_between("A", "C") is None

    def test_path_in_diamond_is_shortest(self):
        # Both A→B→D and A→C→D are length 3; result is one of them
        path = DIAMOND.path_between("A", "D")
        assert path is not None
        assert path[0] == "A"
        assert path[-1] == "D"
        assert len(path) == 3

    def test_path_includes_endpoints(self):
        path = LINEAR.path_between("A", "C")
        assert path[0] == "A"
        assert path[-1] == "C"

    def test_no_path_in_empty_graph(self):
        assert EMPTY.path_between("X", "Y") is None

    def test_path_in_fork(self):
        assert FORK.path_between("A", "B") == ["A", "B"]
        assert FORK.path_between("A", "C") == ["A", "C"]
        assert FORK.path_between("B", "C") is None
