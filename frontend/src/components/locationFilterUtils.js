export function getAvailableDistricts(locationHierarchy, region) {
    if (!region) {
        return []
    }

    const matchedRegion = locationHierarchy.find((item) => item.region === region)
    return matchedRegion?.districts || []
}

export function updateLocationFilters(filters, field, value) {
    if (field === 'region') {
        return {
            ...filters,
            region: value,
            district: ''
        }
    }

    return {
        ...filters,
        [field]: value
    }
}

export function describeLocationFilterState(filters) {
    if (!filters.region) {
        return 'Broad search'
    }

    if (filters.district) {
        return `Precision district filter: ${filters.district}`
    }

    return `Regional match: ${filters.region}`
}
