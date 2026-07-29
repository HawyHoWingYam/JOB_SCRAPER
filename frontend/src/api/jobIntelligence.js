import { fetchCurrentCompanyIndustryTree } from './currentTaxonomies';

function normalizeCompanyIndustryNodes(tree, parentCode) {
  const nodes = Array.isArray(tree?.nodes) ? tree.nodes : [];
  return {
    nodes: nodes
      .filter((node) => node.parent_code === parentCode)
      .sort((left, right) => left.order - right.order)
      .map((node) => ({
        ...node,
        id: node.code,
      })),
  };
}

export async function fetchCompanyIndustryTree(filters = {}, options) {
  return normalizeCompanyIndustryNodes(
    await fetchCurrentCompanyIndustryTree(options),
    filters.parentId || null,
  );
}
