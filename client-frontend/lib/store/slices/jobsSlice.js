import { createSlice } from '@reduxjs/toolkit';

const initialState = {
  listings: [],
  selectedJob: null,
  isLoading: false,
  error: null,
  totalResults: 0,
  page: 1,
  pageSize: 10,
};

export const jobsSlice = createSlice({
  name: 'jobs',
  initialState,
  reducers: {
    setJobs: (state, action) => {
      state.listings = action.payload;
      state.isLoading = false;
      state.error = null;
    },
    setSelectedJob: (state, action) => {
      state.selectedJob = action.payload;
    },
    startLoading: (state) => {
      state.isLoading = true;
      state.error = null;
    },
    setError: (state, action) => {
      state.isLoading = false;
      state.error = action.payload;
    },
    setPage: (state, action) => {
      state.page = action.payload;
    },
    setPageSize: (state, action) => {
      state.pageSize = action.payload;
    },
    setTotalResults: (state, action) => {
      state.totalResults = action.payload;
    },
  },
});

export const { 
  setJobs, 
  setSelectedJob, 
  startLoading,
  setError,
  setPage,
  setPageSize,
  setTotalResults
} = jobsSlice.actions;

export default jobsSlice.reducer;