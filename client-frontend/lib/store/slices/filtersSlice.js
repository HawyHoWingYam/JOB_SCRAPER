import { createSlice } from '@reduxjs/toolkit';

const initialState = {
  searchQuery: '',
  location: '',
  jobType: [],
  experienceLevel: [],
  salary: {
    min: null,
    max: null,
  },
  datePosted: null,
  sortBy: 'relevance',
};

export const filtersSlice = createSlice({
  name: 'filters',
  initialState,
  reducers: {
    setSearchQuery: (state, action) => {
      state.searchQuery = action.payload;
    },
    setLocation: (state, action) => {
      state.location = action.payload;
    },
    setJobType: (state, action) => {
      state.jobType = action.payload;
    },
    setExperienceLevel: (state, action) => {
      state.experienceLevel = action.payload;
    },
    setSalaryRange: (state, action) => {
      state.salary = action.payload;
    },
    setDatePosted: (state, action) => {
      state.datePosted = action.payload;
    },
    setSortBy: (state, action) => {
      state.sortBy = action.payload;
    },
    resetFilters: (state) => {
      return initialState;
    },
  },
});

export const {
  setSearchQuery,
  setLocation,
  setJobType,
  setExperienceLevel,
  setSalaryRange,
  setDatePosted,
  setSortBy,
  resetFilters,
} = filtersSlice.actions;

export default filtersSlice.reducer;