/**
 * Flattening a parent-linked list into indented rows.
 *
 * Extracted from the Milestone 9 dossier section tree so the blueprint library
 * can reuse the algorithm rather than grow a second copy of it. What is shared
 * is the *flattening*, not the presentation: a dossier row shows readiness and
 * blockers, a blueprint row shows required/optional and draft controls, and
 * forcing one component to do both would be worse than two small ones.
 *
 * The output is deliberately flat. A version can hold hundreds of sections, and
 * nesting them produces hundreds-deep DOM containers that are slow to lay out
 * and impossible to virtualise later. Depth becomes `paddingLeft`, and
 * collapsing filters the visible list rather than unmounting a subtree.
 */

/** The minimum a node must expose to be placed in a tree. */
export interface TreeNode {
  public_id: string;
  parent_public_id: string | null;
  sequence: number;
}

export interface TreeRowOf<T> {
  section: T;
  depth: number;
  hasChildren: boolean;
}

/**
 * Depth-first rows, siblings ordered by `sequence` with `public_id` as a stable
 * tiebreak so two rows sharing a sequence never render in fetch order.
 *
 * Nodes whose parent is missing from `nodes` are treated as roots rather than
 * dropped: a filtered or partial list should still render everything it was
 * given, and silently swallowing rows would hide data from the user.
 */
export function buildTreeRows<T extends TreeNode>(
  nodes: T[],
  collapsed: Set<string>
): TreeRowOf<T>[] {
  const present = new Set(nodes.map((n) => n.public_id));
  const childrenOf = new Map<string | null, T[]>();

  for (const node of nodes) {
    const key =
      node.parent_public_id && present.has(node.parent_public_id) ? node.parent_public_id : null;
    if (!childrenOf.has(key)) childrenOf.set(key, []);
    childrenOf.get(key)!.push(node);
  }
  for (const list of childrenOf.values()) {
    list.sort((a, b) => a.sequence - b.sequence || a.public_id.localeCompare(b.public_id));
  }

  const rows: TreeRowOf<T>[] = [];
  const walk = (parentId: string | null, depth: number) => {
    for (const node of childrenOf.get(parentId) ?? []) {
      const kids = childrenOf.get(node.public_id) ?? [];
      rows.push({ section: node, depth, hasChildren: kids.length > 0 });
      if (!collapsed.has(node.public_id)) walk(node.public_id, depth + 1);
    }
  };
  walk(null, 0);
  return rows;
}
