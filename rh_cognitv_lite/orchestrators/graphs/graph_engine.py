"""Private in-house graph engine for the graphs orchestration layer.

Implements textbook algorithms over a plain adjacency representation.
No Pydantic, no public API — internal use by Graph and GraphBuilder only.

Algorithms:
  1. Entry / leaf node detection by in/out-degree      O(V+E)
  2. Iterative DFS cycle detection (three-colour)      O(V+E)
  3. Kahn's topological sort / generation batching     O(V+E)
  4. Iterative DFS reachability / descendants          O(V+E)
  5. BFS shortest path                                 O(V+E)
  6. Back-edge detection (DFS, three-colour)           O(V+E)
  7. Cycle membership — nodes_in_cycles                O(V*(V+E))
"""

from __future__ import annotations

from collections import deque
from typing import Iterator


class _GraphEngine:
    """Immutable directed graph engine operating on string node IDs.

    Constructed from a snapshot of node IDs and (source, target) edge tuples.
    All query methods are pure; no in-place mutation exists.  A new topology
    requires a new engine instance.

    The engine is cycle-safe: all traversal algorithms handle cyclic graphs
    correctly.  ``topological_generations`` is the sole exception — it raises
    ``ValueError`` when a cycle is detected, as topological order is undefined
    for cyclic graphs.  Callers should guard with ``has_cycle()`` first.
    """

    def __init__(
        self,
        nodes: set[str],
        edges: set[tuple[str, str]],
    ) -> None:
        self._nodes: frozenset[str] = frozenset(nodes)
        self._edges: frozenset[tuple[str, str]] = frozenset(edges)

        # Successor and predecessor adjacency maps — built once at init.
        self._succ: dict[str, set[str]] = {n: set() for n in self._nodes}
        self._pred: dict[str, set[str]] = {n: set() for n in self._nodes}
        for src, tgt in self._edges:
            self._succ[src].add(tgt)
            self._pred[tgt].add(src)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def nodes(self) -> frozenset[str]:
        return self._nodes

    @property
    def edges(self) -> frozenset[tuple[str, str]]:
        return self._edges

    # ── Algorithm 1: Entry / leaf detection by degree ─────────────────────────

    def entry_nodes(self) -> set[str]:
        """Return node IDs with in-degree 0 (no predecessors)."""
        return {n for n in self._nodes if not self._pred[n]}

    def leaf_nodes(self) -> set[str]:
        """Return node IDs with out-degree 0 (no successors)."""
        return {n for n in self._nodes if not self._succ[n]}

    # ── Algorithm 2: Iterative DFS cycle detection (three-colour) ─────────────

    def has_cycle(self) -> bool:
        """Return True if the graph contains at least one directed cycle.

        Uses iterative three-colour DFS:
          WHITE — not yet visited
          GRAY  — on the current DFS path (in the recursion stack)
          BLACK — fully explored

        A GRAY neighbour encountered during DFS signals a back-edge, which is
        both necessary and sufficient for a cycle in a directed graph.
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        colour: dict[str, int] = {n: WHITE for n in self._nodes}

        for start in self._nodes:
            if colour[start] != WHITE:
                continue

            colour[start] = GRAY
            stack: list[tuple[str, Iterator[str]]] = [
                (start, iter(self._succ[start]))
            ]

            while stack:
                node, children = stack[-1]
                try:
                    child = next(children)
                    if colour[child] == GRAY:
                        return True
                    if colour[child] == WHITE:
                        colour[child] = GRAY
                        stack.append((child, iter(self._succ[child])))
                except StopIteration:
                    colour[node] = BLACK
                    stack.pop()

        return False

    def would_create_cycle(self, source: str, target: str) -> bool:
        """Return True if adding edge (source → target) would create a cycle.

        A new edge creates a cycle iff target can already reach source (which
        would form a closed loop), or source == target (a self-loop).
        """
        if source == target:
            return True
        return self.is_reachable(target, source)

    # ── Algorithm 3: Kahn's topological sort / generation batching ────────────

    def topological_generations(self) -> list[set[str]]:
        """Return nodes partitioned into topological generations (Kahn's algorithm).

        Generation 0 contains all entry nodes.  Generation k contains all nodes
        whose predecessors are entirely in generations < k.  Nodes within the
        same generation may be executed in parallel.

        Raises ValueError if the graph contains a cycle.  Use ``has_cycle()``
        to guard before calling on graphs of unknown topology.
        """
        in_degree: dict[str, int] = {n: len(self._pred[n]) for n in self._nodes}
        queue: deque[str] = deque(n for n, d in in_degree.items() if d == 0)
        generations: list[set[str]] = []
        visited: int = 0

        while queue:
            generation: set[str] = set()
            # Snapshot the frontier size so newly-enqueued nodes land in the
            # *next* generation, not the current one.
            for _ in range(len(queue)):
                node = queue.popleft()
                generation.add(node)
                visited += 1
                for nbr in self._succ[node]:
                    in_degree[nbr] -= 1
                    if in_degree[nbr] == 0:
                        queue.append(nbr)
            generations.append(generation)

        if visited != len(self._nodes):
            raise ValueError(
                "Graph contains a cycle; topological sort is not possible."
            )

        return generations

    # ── Algorithm 4: Iterative DFS reachability / descendants ─────────────────

    def descendants_of(self, node_id: str) -> set[str]:
        """Return all node IDs reachable from node_id, excluding node_id itself.

        Cycle-safe: uses a visited set, so cyclic graphs do not cause
        infinite loops.
        """
        visited: set[str] = set()
        stack: list[str] = list(self._succ.get(node_id, set()))
        while stack:
            current = stack.pop()
            if current not in visited:
                visited.add(current)
                stack.extend(self._succ.get(current, set()))
        return visited

    def reachable_from(self, node_id: str) -> set[str]:
        """Alias for ``descendants_of`` with a more descriptive name."""
        return self.descendants_of(node_id)

    def is_reachable(self, source: str, target: str) -> bool:
        """Return True if there is a directed path from source to target.

        A node is trivially reachable from itself.
        """
        if source == target:
            return True
        return target in self.descendants_of(source)

    # ── Algorithm 5: BFS shortest path ───────────────────────────────────────

    def path_between(self, source: str, target: str) -> list[str] | None:
        """Return the shortest directed path from source to target, or None.

        The returned list includes both the source and target node IDs.
        Returns [source] when source == target.  Cycle-safe.
        """
        if source == target:
            return [source]

        visited: set[str] = {source}
        queue: deque[list[str]] = deque([[source]])

        while queue:
            path = queue.popleft()
            for nbr in self._succ.get(path[-1], set()):
                if nbr == target:
                    return path + [nbr]
                if nbr not in visited:
                    visited.add(nbr)
                    queue.append(path + [nbr])

        return None

    # ── Algorithm 6: Back-edge detection ──────────────────────────────────────

    def back_edges(self) -> set[tuple[str, str]]:
        """Return all back edges — edges whose target is a DFS ancestor of source.

        A back edge (u, v) means v is currently on the DFS call stack when u
        is being explored, which is both necessary and sufficient to indicate
        a cycle involving that edge.
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        colour: dict[str, int] = {n: WHITE for n in self._nodes}
        result: set[tuple[str, str]] = set()

        for start in self._nodes:
            if colour[start] != WHITE:
                continue

            colour[start] = GRAY
            stack: list[tuple[str, Iterator[str]]] = [
                (start, iter(self._succ[start]))
            ]

            while stack:
                node, children = stack[-1]
                try:
                    child = next(children)
                    if colour[child] == GRAY:
                        result.add((node, child))
                    elif colour[child] == WHITE:
                        colour[child] = GRAY
                        stack.append((child, iter(self._succ[child])))
                except StopIteration:
                    colour[node] = BLACK
                    stack.pop()

        return result

    # ── Algorithm 7: Cycle membership ─────────────────────────────────────────

    def nodes_in_cycles(self) -> set[str]:
        """Return all node IDs that participate in at least one directed cycle.

        A node n is in a cycle iff there is a directed path of length >= 1
        from n back to n, i.e., n appears in its own descendants set.
        """
        return {n for n in self._nodes if n in self.descendants_of(n)}

    # ── Convenience single-hop accessors ──────────────────────────────────────

    def successors_of(self, node_id: str) -> set[str]:
        """Return the direct successors of node_id (single hop)."""
        return set(self._succ.get(node_id, set()))

    def predecessors_of(self, node_id: str) -> set[str]:
        """Return the direct predecessors of node_id (single hop)."""
        return set(self._pred.get(node_id, set()))
