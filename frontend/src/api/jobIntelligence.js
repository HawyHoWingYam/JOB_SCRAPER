import {
  fetchCurrentCompanyIndustryTree,
  fetchCurrentJobTaxonomyTree,
} from './currentTaxonomies';

function englishLabel(node) {
  return node?.labels?.en || node?.code || '';
}

function normalizeJobTaxonomyTree(tree) {
  const nodes = Array.isArray(tree?.nodes) ? tree.nodes : [];
  const childrenByParent = new Map();

  for (const node of nodes) {
    const children = childrenByParent.get(node.parent_code) || [];
    children.push(node);
    childrenByParent.set(node.parent_code, children);
  }

  const orderedChildren = (parentCode) => (
    childrenByParent.get(parentCode) || []
  ).sort((left, right) => left.order - right.order);

  return {
    domains: orderedChildren(null).map((domain) => ({
      id: domain.code,
      code: domain.code,
      label: englishLabel(domain),
      categories: orderedChildren(domain.code).map((category) => ({
        id: category.code,
        code: category.code,
        label: englishLabel(category),
        subcategories: orderedChildren(category.code).map((subcategory) => ({
          id: subcategory.code,
          code: subcategory.code,
          label: englishLabel(subcategory),
        })),
      })),
    })),
  };
}

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

export async function fetchCanonicalTree(options) {
  return normalizeJobTaxonomyTree(
    await fetchCurrentJobTaxonomyTree(options),
  );
}

export async function fetchCompanyIndustryTree(filters = {}, options) {
  return normalizeCompanyIndustryNodes(
    await fetchCurrentCompanyIndustryTree(options),
    filters.parentId || null,
  );
}
