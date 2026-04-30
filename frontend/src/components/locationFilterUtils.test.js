import { describe, expect, it } from 'vitest';

import {
    describeLocationFilterState,
    getAvailableDistricts,
    updateLocationFilters
} from './locationFilterUtils.js';

const locationHierarchy = [
    {
        region: 'Kowloon',
        districts: ['Kwun Tong District', 'Yau Tsim Mong District']
    },
    {
        region: 'New Territories',
        districts: ['Tsuen Wan District', 'Yuen Long District']
    }
];

describe('locationFilterUtils', () => {
    it('getAvailableDistricts returns only the selected region districts', () => {
        expect(getAvailableDistricts(locationHierarchy, 'New Territories')).toEqual([
            'Tsuen Wan District',
            'Yuen Long District'
        ]);
    });

    it('getAvailableDistricts returns an empty list when region is not selected', () => {
        expect(getAvailableDistricts(locationHierarchy, '')).toEqual([]);
    });

    it('updateLocationFilters clears district when region changes', () => {
        const nextFilters = updateLocationFilters(
            {
                region: 'Kowloon',
                district: 'Yau Tsim Mong District',
                employment_type: ''
            },
            'region',
            'New Territories'
        );

        expect(nextFilters.region).toBe('New Territories');
        expect(nextFilters.district).toBe('');
        expect(nextFilters.employment_type).toBe('');
    });

    it('updateLocationFilters preserves district for non-region changes', () => {
        const nextFilters = updateLocationFilters(
            {
                region: 'Kowloon',
                district: 'Yau Tsim Mong District',
                employment_type: ''
            },
            'employment_type',
            'Full time'
        );

        expect(nextFilters.region).toBe('Kowloon');
        expect(nextFilters.district).toBe('Yau Tsim Mong District');
        expect(nextFilters.employment_type).toBe('Full time');
    });

    it('describeLocationFilterState returns broad search when no region is selected', () => {
        expect(describeLocationFilterState({ region: '', district: '' })).toBe('Broad search');
    });

    it('describeLocationFilterState returns a regional summary when only region is selected', () => {
        expect(describeLocationFilterState({ region: 'Kowloon', district: '' })).toBe(
            'Regional match: Kowloon'
        );
    });

    it('describeLocationFilterState returns a district summary when both are selected', () => {
        expect(
            describeLocationFilterState({
                region: 'Kowloon',
                district: 'Yau Tsim Mong District'
            })
        ).toBe('Precision district filter: Yau Tsim Mong District');
    });
});
