function hierarchyIndex(options) {
  const parentById = new Map(
    (options || []).map((option) => [option.id, option.parent_id || null]),
  );
  return { parentById };
}


function hasAncestor(id, ancestorId, parentById) {
  const visited = new Set();
  let parentId = parentById.get(id);
  while (parentId && !visited.has(parentId)) {
    if (parentId === ancestorId) return true;
    visited.add(parentId);
    parentId = parentById.get(parentId);
  }
  return false;
}


function orderedSelection(options, selectedIds) {
  const selected = new Set(selectedIds);
  const known = (options || [])
    .map((option) => option.id)
    .filter((id) => selected.has(id));
  const knownSet = new Set(known);
  return [
    ...known,
    ...selectedIds.filter((id) => !knownSet.has(id)),
  ];
}


export function toggleHierarchySelection(
  options,
  selectedIds,
  optionId,
  checked,
) {
  const current = Array.from(new Set(selectedIds || []));
  if (!checked) {
    return current.filter((id) => id !== optionId);
  }

  const { parentById } = hierarchyIndex(options);
  if (current.some((id) => hasAncestor(optionId, id, parentById))) {
    return orderedSelection(options, current);
  }

  const next = current.filter(
    (id) => id !== optionId && !hasAncestor(id, optionId, parentById),
  );
  next.push(optionId);
  return orderedSelection(options, next);
}


export function isHierarchyOptionCovered(options, selectedIds, optionId) {
  const { parentById } = hierarchyIndex(options);
  return (selectedIds || []).some(
    (selectedId) => selectedId !== optionId
      && hasAncestor(optionId, selectedId, parentById),
  );
}
